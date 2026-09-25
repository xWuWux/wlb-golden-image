#!/usr/bin/env bash
# Stage 5: testy integracyjne i migracji na prawdziwym obrazie.
#   1. budowanie golden image (Packer + Ansible, QEMU/KVM)
#   2. VM z cloud-init Laboratorium testowego + kryteria akceptacji MVP
#   3. migracja: nowa VM na istniejącym dysku roboczym (konta, UID, pliki, baza huba)
#   4. dryf zamrożonych wersji: czy budowanie odtworzyło dokładnie envs/*.lock
#   5. podatności pakietów faktycznie zainstalowanych w obrazie (raport) — osobno:
#      ci/integration.sh image-sca  (w CI jako osobny krok, po zapisaniu artefaktów)
#
#   PREV_IMAGE=stary.qcow2   migracja z poprzedniej wersji obrazu (domyślnie: ten sam obraz)
#   REUSE_IMAGE=1            nie buduj ponownie, jeśli obraz tej wersji już jest w output/
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require packer ansible-playbook qemu-system-x86_64 qemu-img cloud-localds osv-scanner python3

IMAGE_VERSION=${IMAGE_VERSION:-0.0.0-ci}
IMAGE_DATE=${IMAGE_DATE:-$(date +%Y%m%d)}
FULL=wlb-general-$IMAGE_VERSION-$IMAGE_DATE
IMAGE=$REPO_ROOT/output/$FULL/$FULL.qcow2
ARTIFACTS=build/artifacts/$FULL
LOGS=build/ci-logs
mkdir -p "$LOGS"
[[ -w /dev/kvm ]] || {
  echo "Brak dostępu do /dev/kvm — stage 5 wymaga KVM"
  exit 1
}
# Zasoby VM dopasowane do maszyny (runnery GitHub dla repozytoriów prywatnych: 2 vCPU, ~7 GB RAM).
# Maszyna budująca i VM testowa nie działają jednocześnie, więc obie mogą wziąć tyle samo.
CPUS=$(nproc)
MEM_MB=$(($(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 - 2048)) # 2 GB zostawiamy hostowi
export VM_CPUS=${VM_CPUS:-$((CPUS < 4 ? CPUS : 4))}
export VM_MEMORY=${VM_MEMORY:-$((MEM_MB < 8192 ? MEM_MB : 8192))}
BUILD_CPUS=${BUILD_CPUS:-$VM_CPUS}
BUILD_MEMORY=${BUILD_MEMORY:-$((VM_MEMORY < 6144 ? VM_MEMORY : 6144))}
echo "Zasoby: host $CPUS CPU; VM $VM_CPUS vCPU / $VM_MEMORY MB; budowanie $BUILD_CPUS vCPU / $BUILD_MEMORY MB"
SSH=(ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i build/test/id_ed25519 -p 2222 wlbadmin@127.0.0.1)

build_image() {
  if [[ ${REUSE_IMAGE:-0} == 1 && -f $IMAGE ]]; then
    echo "Używam istniejącego obrazu $IMAGE"
    return 0
  fi
  [[ -f build/packer_ed25519 ]] || ssh-keygen -q -t ed25519 -N '' -C wlb-packer-build -f build/packer_ed25519
  rm -rf "output/$FULL"
  packer init packer/ >/dev/null
  PACKER_LOG=1 PACKER_LOG_PATH="$LOGS/packer.log" packer build -color=false \
    -var "image_version=$IMAGE_VERSION" -var "image_date=$IMAGE_DATE" \
    -var "build_cpus=$BUILD_CPUS" -var "build_memory=$BUILD_MEMORY" packer/
  ls -lh "output/$FULL/"
}

# zapis logów VM przed jej zatrzymaniem (do artefaktów CI)
collect_vm_logs() {
  local name=$1
  "${SSH[@]}" 'sudo journalctl -b --no-pager' >"$LOGS/$name-journal.log" 2>/dev/null || true
  "${SSH[@]}" 'sudo ausearch --input-logs -k wlb_sluza_out -k wlb_sluza_in -i' >"$LOGS/$name-audit.log" 2>/dev/null || true
  cp build/test/serial.log "$LOGS/$name-serial.log" 2>/dev/null || true
}

acceptance() {
  local rc=0
  tests/run-local.sh "$IMAGE" || rc=$?
  if [[ $rc -eq 0 ]]; then
    tests/acceptance.sh | tee "$LOGS/acceptance.log" || rc=$?
    # brak podsumowania = test urwał się w połowie, nawet jeśli kod wyjścia jest 0
    grep -q '^Wynik:' "$LOGS/acceptance.log" || {
      echo "Test akceptacyjny nie doszedł do końca (brak linii 'Wynik:')"
      rc=1
    }
    # pakiety systemowe faktycznie zainstalowane w obrazie (dla skanu podatności)
    "${SSH[@]}" 'cat /var/lib/dpkg/status' >"$ARTIFACTS/dpkg-status" || true
  fi
  collect_vm_logs acceptance
  tests/stop-local.sh
  {
    echo "### Kryteria akceptacji MVP"
    echo
    echo '```'
    grep -E '^(==|  (PASS|FAIL|SKIP)|Wynik)' "$LOGS/acceptance.log" 2>/dev/null || echo "VM nie wystartowała — zob. artefakty ci-logs"
    echo '```'
  } | summary >/dev/null
  return $rc
}

migration() {
  local rc=0
  tests/migration.sh "${PREV_IMAGE:-$IMAGE}" "$IMAGE" | tee "$LOGS/migration.log" || rc=$?
  [[ $rc -eq 0 ]] || collect_vm_logs migration
  tests/stop-local.sh
  {
    echo "### Migracja (dysk roboczy -> nowa VM)"
    echo
    echo '```'
    cat "$LOGS/migration.log"
    echo '```'
  } | summary >/dev/null
  return $rc
}

lock_drift() {
  python3 - "$ARTIFACTS" <<'PY'
import json, sys
from pathlib import Path
import yaml
art = Path(sys.argv[1])
problems, notes = [], []

# locki wygenerowane przy budowaniu muszą zawierać pakiety — inaczej zamrożenie wersji nie działa
built_r = json.loads((art / "renv.lock").read_text()).get("Packages", {})
if not built_r:
    problems.append("renv.lock z obrazu nie zawiera pakietów")
if not (art / "environment.lock.yml").is_file():
    problems.append("brak environment.lock.yml z obrazu")

r_repo = json.loads(Path("envs/r/renv.lock").read_text())
if r_repo.get("Packages"):
    r_built = json.loads((art / "renv.lock").read_text())
    want = {k: v.get("Version") for k, v in r_repo["Packages"].items()}
    got = {k: v.get("Version") for k, v in r_built["Packages"].items()}
    problems += [f"R {k}: lock {want.get(k)} != obraz {got.get(k)}" for k in sorted(set(want) | set(got)) if want.get(k) != got.get(k)]
else:
    notes.append("renv.lock bez pakietów — wygenerowany lock w artefaktach (make freeze)")

py_lock = Path("envs/python/environment.lock.yml")
if py_lock.exists():
    def deps(p):
        d = yaml.safe_load(p.read_text())["dependencies"]
        return sorted(x for x in d if isinstance(x, str)), sorted(next((x["pip"] for x in d if isinstance(x, dict)), []))
    want, got = deps(py_lock), deps(art / "environment.lock.yml")
    for label, w, g in (("conda", want[0], got[0]), ("pip", want[1], got[1])):
        problems += [f"Python/{label}: tylko w locku {x}" for x in sorted(set(w) - set(g))]
        problems += [f"Python/{label}: tylko w obrazie {x}" for x in sorted(set(g) - set(w))]
else:
    notes.append("environment.lock.yml nie istnieje — wygenerowany lock w artefaktach (make freeze)")

for n in notes:
    print("uwaga:", n)
for p in problems:
    print("DRYF:", p)
sys.exit(1 if problems else 0)
PY
}

image_sca() {
  [[ -s $ARTIFACTS/dpkg-status ]] || {
    echo "Brak listy pakietów z VM — pomijam"
    return 0
  }
  python3 ci/sca_requirements.py "$ARTIFACTS/environment.lock.yml" build/sca/image-requirements.txt
  # raport, nie bramka: pakiety systemowe Ubuntu mają zwykle otwarte CVE bez poprawki w dystrybucji;
  # aktualizacje wchodzą przez nową wersję obrazu
  timeout 600 osv-scanner scan source --no-resolve --format markdown --output-file build/sca/image-osv.md \
    -L "dpkg-status:$ARTIFACTS/dpkg-status" -L "$ARTIFACTS/renv.lock" -L build/sca/image-requirements.txt ||
    echo "osv-scanner: kod $? (124 = przekroczony czas)" | tee -a build/sca/image-osv.md
  {
    echo "### Podatności pakietów w obrazie (raport)"
    echo
    echo "<details><summary>osv-scanner: dpkg + R + Python</summary>"
    echo
    cat build/sca/image-osv.md
    echo "</details>"
  } | summary >/dev/null
}

mkdir -p build/sca "$ARTIFACTS"
if [[ ${1:-} == image-sca ]]; then
  # osobny krok CI: artefakty ostatniego budowania, niezależnie od daty w nazwie
  [[ -d $ARTIFACTS ]] || ARTIFACTS=$(find build/artifacts -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  run_check "Podatności pakietów w obrazie (raport)" image_sca
  finish
  exit
fi
step "Budowanie obrazu $FULL"
build_image
endstep
run_check "Kryteria akceptacji MVP" acceptance
run_check "Migracja na istniejącym dysku roboczym" migration
run_check "Dryf zamrożonych wersji (envs/*.lock vs obraz)" lock_drift
finish
