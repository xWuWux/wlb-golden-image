#!/usr/bin/env bash
# Stage 5: testy integracyjne i migracji na prawdziwym obrazie.
#   1. budowanie golden image (Packer + Ansible, QEMU/KVM)
#   2. VM z cloud-init Laboratorium testowego + kryteria akceptacji MVP
#   3. migracja: nowa VM na istniejącym dysku roboczym (konta, UID, pliki, baza huba)
#   4. obserwowalność: zdarzenia z observability/contract.yml docierają do logu centralnego
#      (testowy odbiornik SIEM na hoście, VM wysyła do niego rsyslogiem), a dekodery i reguły
#      Wazuh parsują ten log na nazwane pola i rozpoznają podrobione wpisy (#17)
#   5. dryf zamrożonych wersji: czy budowanie odtworzyło dokładnie envs/*.lock
#   6. utwardzenie systemu: raport Lynis z VM testowej (hardening index + ostrzeżenia/sugestie) — #11
#   7. podatności pakietów zainstalowanych w obrazie: systemowe (bez jądra), R, Python (raport) — osobno:
#      ci/integration.sh image-sca  (w CI jako osobny krok, po zapisaniu artefaktów)
#
#   PREV_IMAGE=stary.qcow2   migracja z poprzedniej wersji obrazu (domyślnie: ten sam obraz)
#   REUSE_IMAGE=1            nie buduj ponownie, jeśli obraz tej wersji już jest w output/
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
# shellcheck source=ci/image-meta.sh
. "$(dirname "$0")/image-meta.sh"
require packer ansible-playbook qemu-system-x86_64 qemu-img cloud-localds osv-scanner oscap python3

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
# 2,5 GB zostaje poza VM: strażnik (--memory auto) trzyma cały etap o 1 GB poniżej pamięci maszyny,
# a w tej samej cgroup działają też QEMU, Packer i narzędzia testowe
MEM_MB=$(($(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 - 2560))
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
  image_provenance # GIT_COMMIT/GIT_DESCRIBE/GIT_DIRTY/BUILD_RUN do metadanych obrazu (#12a)
  # Tylko baza (wlb.qemu.wlb). Bez -only Packer buduje też flavory (wlb-memory, wlb-radiologia)
  # RÓWNOLEGLE z bazą — a te mają disk_image=true z base_image=output/wlb-general.qcow2
  # (placeholder) i padają natychmiast, bo bazy jeszcze nie ma. Flavory buduje się warstwowo
  # osobno (runbooki RB-build-*), z realnym -var base_image. Integracja testuje bazę.
  if ! PACKER_LOG=1 PACKER_LOG_PATH="$LOGS/packer.log" packer build -color=false -only='wlb.qemu.wlb' \
    -var "image_version=$IMAGE_VERSION" -var "image_date=$IMAGE_DATE" \
    -var "build_cpus=$BUILD_CPUS" -var "build_memory=$BUILD_MEMORY" \
    -var "git_commit=$GIT_COMMIT" -var "git_describe=$GIT_DESCRIBE" \
    -var "git_dirty=$GIT_DIRTY" -var "build_run=$BUILD_RUN" packer/; then
    # budowanie przerwane przez niedostępne repozytoria pakietów (PyPI, conda-forge, CRAN, apt), a nie
    # przez błąd w kodzie: adnotacja INFRA — ci-retry.yml ponowi przebieg jeden raz. Przy zbiegu
    # z prawdziwym błędem kosztem jest jedno zbędne ponowienie.
    if grep -qE 'Read timed out|ConnectTimeout|Temporary failure in name resolution|Backend is unhealthy|HTTP Error 50[234]|CondaHTTPError|Failed to fetch .* 50[234]' "$LOGS/packer.log"; then
      echo "::error title=INFRA: repozytorium pakietów niedostępne::Budowanie obrazu przerwane przez błędy sieci (zob. packer.log w artefaktach etapu 5)"
    fi
    return 1
  fi
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
  # $1 obraz (domyślnie baza), $2 nazwa logu — reużywane dla flavora wlb-radiologia (#135)
  local img=${1:-$IMAGE} logname=${2:-acceptance}
  local rc=0 sink ntp="" ntp_flag="" proxy=""
  # testowy SIEM: VM (sieć QEMU user) wysyła logi po TLS do hosta 10.0.2.2:5514 — tests/cloud-init/user-data.yaml
  rm -f "$LOGS/siem.log"
  tests/lib/test-pki.sh build/test
  python3 tests/syslog_sink.py --port 5514 --out "$LOGS/siem.log" --tls-cert build/test/siem.pem --tls-key build/test/siem.key &
  sink=$!
  sleep 1
  # odbiornik musi słuchać, zanim wystartuje VM — inaczej zdarzenia trafią gdzie indziej
  # (np. do odbiornika z ręcznego testu, który nadal trzyma port) i wynik będzie mylący
  if ! kill -0 "$sink" 2>/dev/null; then
    echo "Testowy odbiornik SIEM nie wystartował — port 5514 zajęty? (ss -ltnp 'sport = :5514')"
    return 1
  fi
  # testowy serwer czasu: VM (chrony) synchronizuje się z 10.0.2.2:123 — tests/ntp_sink.py (#36).
  # Port 123 jest uprzywilejowany → przez sudo (na runnerze CI bez hasła). Bez sudo pomijamy serwer:
  # test synchronizacji w VM dostanie wtedy SKIP (flaga --ntp-sync nieprzekazana), a nie fałszywy wynik.
  if sudo -n true 2>/dev/null; then
    sudo python3 tests/ntp_sink.py --port 123 &
    ntp=$!
    sleep 1
    if kill -0 "$ntp" 2>/dev/null; then
      ntp_flag=1
    else
      echo "Testowy serwer NTP nie wystartował — port 123 zajęty? (ss -lunp 'sport = :123')"
      ntp=""
    fi
  else
    echo "Bez sudo — testowy serwer NTP pominięty (test synchronizacji w VM zrobi SKIP)"
  fi
  # testowy proxy z allowlistą: badacz wychodzi wyłącznie przez 10.0.2.2:3128 — tests/proxy_sink.py (#16).
  # Przepuszcza tylko mirrory (allowlista), resztę (w tym API LLM) odrzuca 403. Port nieuprzywilejowany
  # (bez sudo). W etapie 5 brak fixture jest błędem, nigdy pominięciem testu (#16, #63).
  python3 tests/proxy_sink.py --port 3128 --allow pypi.mirror.local,cran.mirror.local &
  proxy=$!
  sleep 1
  if ! kill -0 "$proxy" 2>/dev/null; then
    echo "Testowy proxy nie wystartował — integracja przerwana (#16, #63)"
    kill "$sink" 2>/dev/null || true
    wait "$sink" 2>/dev/null || true
    if [[ -n $ntp ]]; then
      sudo kill "$ntp" 2>/dev/null || true
      wait "$ntp" 2>/dev/null || true
    fi
    wait "$proxy" 2>/dev/null || true
    return 1
  fi
  tests/run-local.sh "$img" || rc=$?
  if [[ $rc -eq 0 ]]; then
    WLB_TEST_NTP=$ntp_flag WLB_TEST_PROXY=1 tests/acceptance.sh | tee "$LOGS/$logname.log" || rc=$?
    # brak podsumowania = test urwał się w połowie, nawet jeśli kod wyjścia jest 0
    grep -q '^Wynik:' "$LOGS/$logname.log" || {
      echo "Test akceptacyjny nie doszedł do końca (brak linii 'Wynik:')"
      rc=1
    }
    # pakiety systemowe faktycznie zainstalowane w obrazie (dla skanu podatności)
    "${SSH[@]}" 'cat /var/lib/dpkg/status' >"$ARTIFACTS/dpkg-status" || true
    # tozsamosc systemu z TEJ SAMEJ VM co dpkg-status (#129): osv-scanner ekosystem pakietow
    # deb wnosi z /etc/os-release WLASNEGO procesu, nie z obrazu; bez tej pary raport SCA/SBOM
    # moze dotyczyc zlego wydania po cichu.
    "${SSH[@]}" 'cat /etc/os-release' >"$ARTIFACTS/os-release" || true
    # skan utwardzenia (Lynis) na działającej VM — raport, nie bramka (#11); nigdy nie psuje akceptacji
    "${SSH[@]}" 'sudo lynis audit system --quick --no-colors' >"$LOGS/lynis.log" 2>&1 || true
    "${SSH[@]}" 'sudo cat /var/log/lynis-report.dat' >"$ARTIFACTS/lynis-report.dat" 2>/dev/null || true
  fi
  sleep 10 # dostarczenie ostatnich zdarzeń z kolejki rsyslog
  collect_vm_logs acceptance
  tests/stop-local.sh
  kill "$sink" 2>/dev/null
  wait "$sink" 2>/dev/null
  if [[ -n $ntp ]]; then
    sudo kill "$ntp" 2>/dev/null # $ntp to PID sudo; SIGTERM przekazywany do serwera (działa jako root)
    wait "$ntp" 2>/dev/null
  fi
  if [[ -n $proxy ]]; then
    kill "$proxy" 2>/dev/null
    wait "$proxy" 2>/dev/null
  fi
  {
    echo "### Kryteria akceptacji MVP"
    echo
    echo '```'
    grep -E '^(==|  (PASS|FAIL|SKIP)|Wynik)' "$LOGS/$logname.log" 2>/dev/null || echo "VM nie wystartowała — zob. artefakty ci-logs"
    echo '```'
  } | summary >/dev/null
  return $rc
}

siem_delivery() {
  [[ -s $LOGS/siem.log ]] || {
    echo "Odbiornik SIEM nie dostał żadnych zdarzeń"
    return 1
  }
  echo "Odebrano $(wc -l <"$LOGS/siem.log") zdarzeń"
  python3 ci/observability_contract.py verify-log "$LOGS/siem.log" --expect-untrusted sluza_out.export_request
}

# Ten sam log, który dotarł do testowego SIEM, przez prawdziwy menedżer Wazuh (#17). Próbka w etapie 3.5
# sprawdza wszystkie zdarzenia; tu — że dekodery nadążają za tym, co obraz faktycznie wysyła.
siem_wazuh() {
  [[ -s $LOGS/siem.log ]] || return 1
  ci/wazuh-logtest.sh "$LOGS/siem.log" --expect-untrusted sluza_out.export_request
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
  local rc=0
  python3 - "$ARTIFACTS" <<'PY' || rc=$?
import json, sys
from pathlib import Path
art = Path(sys.argv[1])
problems, notes = [], []

# locki wygenerowane przy budowaniu muszą zawierać pakiety — inaczej zamrożenie wersji nie działa
built_r = json.loads((art / "renv.lock").read_text()).get("Packages", {})
if not built_r:
    problems.append("renv.lock z obrazu nie zawiera pakietów")

r_repo = json.loads(Path("envs/r/renv.lock").read_text())
if r_repo.get("Packages"):
    r_built = json.loads((art / "renv.lock").read_text())
    want = {k: v.get("Version") for k, v in r_repo["Packages"].items()}
    got = {k: v.get("Version") for k, v in r_built["Packages"].items()}
    problems += [f"R {k}: lock {want.get(k)} != obraz {got.get(k)}" for k in sorted(set(want) | set(got)) if want.get(k) != got.get(k)]
else:
    notes.append("renv.lock bez pakietów — wygenerowany lock w artefaktach (make freeze)")

for n in notes:
    print("uwaga:", n)
for p in problems:
    print("DRYF:", p)
sys.exit(1 if problems else 0)
PY
  if [[ ! -s $ARTIFACTS/environment.lock.yml ]]; then
    echo "DRYF: brak environment.lock.yml z obrazu"
    return 1
  fi
  if [[ ! -s envs/python/environment.lock.yml ]]; then
    echo "uwaga: environment.lock.yml nie istnieje — wygenerowany lock w artefaktach (make freeze)"
    return $rc
  fi
  # Porównanie Pythona ma własny moduł (testowany jednostkowo): patrzy na wersje ponad działami
  # menedżerów, bo migracja conda <-> pip przy tej samej wersji nie jest suchym dryfem
  python3 ci/lock_drift.py envs/python/environment.lock.yml "$ARTIFACTS/environment.lock.yml" || rc=1
  return $rc
}

kernel_single() {
  # Twarde kryterium #9: dokładnie jedna wersja linux-image/modules/headers/tools w obrazie.
  # dpkg-status z VM testowej zebrany w acceptance(); logika w ci/kernel_check.py (testowana jednostkowo).
  [[ -s $ARTIFACTS/dpkg-status ]] || {
    echo "Brak dpkg-status z VM — pomijam"
    return 0
  }
  python3 ci/kernel_check.py "$ARTIFACTS/dpkg-status"
}

image_sca() {
  # #129 (recenzja #179): raport bez pakietów systemowych jest niekompletny, a bez
  # tożsamości OS — niedowiarygodny. Oba warunki zatrzymują skan PRZED ścieżką
  # "pomijam" dla locków, żeby żadna wcześniejsza asymetria wejść nie ominęła bramki.
  [[ -s $ARTIFACTS/dpkg-status ]] || {
    echo "Brak dpkg-status z VM — skan pakietow systemowych niemożliwy (#129)" >&2
    return 1
  }
  python3 ci/image_identity.py "$ARTIFACTS" || return 1
  [[ -s $ARTIFACTS/renv.lock && -s $ARTIFACTS/environment.lock.yml ]] || {
    echo "Brak locków z obrazu — pomijam"
    return 0
  }
  python3 ci/sca_requirements.py "$ARTIFACTS/environment.lock.yml" build/sca/image-requirements.txt
  local inputs=(-L "$ARTIFACTS/renv.lock" -L build/sca/image-requirements.txt)
  # pakiety systemowe (dpkg-status z VM testowej) — bez pakietu źródłowego "linux", który wywołuje
  # nieograniczone zużycie pamięci w osv-scanner (ci/osv-scanner-image.toml, issue #2)
  inputs+=(-L "dpkg-status:$ARTIFACTS/dpkg-status")
  # Raport, nie bramka: pakiety systemowe Ubuntu mają zwykle CVE bez poprawki w dystrybucji;
  # poprawki wchodzą przez nową wersję obrazu. Strażnik pilnuje pamięci (pomiar: ~1,3 GB) i czasu.
  ci/guard.sh --name "osv-scanner (obraz)" --optional --ok-codes 0,1 --timeout 10m --memory 2500M -- \
    osv-scanner scan source --no-resolve --config ci/osv-scanner-image.toml \
    --format markdown --output-file build/sca/image-osv.md "${inputs[@]}"
  local pending
  pending=$(grep -oP '^PENDING_UPGRADES=\K\d+' "$ARTIFACTS/image-release" 2>/dev/null || echo "?")
  {
    echo "### Podatności pakietów w obrazie (raport)"
    echo
    echo "Zaległe aktualizacje pakietów systemowych w chwili budowania: **$pending**"
    echo
    echo "<details><summary>osv-scanner: pakiety systemowe (bez jądra) + R + Python</summary>"
    echo
    cat build/sca/image-osv.md 2>/dev/null || echo "brak wyniku — zob. build/ci-logs/guard.jsonl"
    echo "</details>"
  } | summary >/dev/null
}

image_oval() {
  [[ -s $ARTIFACTS/dpkg-status ]] || {
    echo "Brak dpkg-status z VM — pomijam OVAL"
    return 0
  }
  # OVAL Canonical (USN): CVE pakietów NIE-jądrowych (oscap) + sygnał świeżości jądra (oval_summary.py),
  # bo oscap nie flaguje jądra (USN kluczują poprawki na wersjonowanych binarkach linux-image-*-NNN).
  # Domyka ślepą plamkę po override "linux" w osv-scanner (#2/#3). Pomiar lokalny: ~0,7 GB / ~6 s.
  ci/guard.sh --name "oscap OVAL (obraz, jądro)" --optional --timeout 10m --memory 1500M -- \
    ci/image_oval.sh "$ARTIFACTS/dpkg-status" build/sca
  {
    echo "### Skan OVAL Canonical (USN) obrazu — jądro i pakiety (#3)"
    echo
    cat build/sca/oval-summary.md 2>/dev/null || echo "brak wyniku — zob. build/ci-logs/guard.jsonl"
  } | summary >/dev/null
}

hardening_report() {
  # Raport utwardzenia z VM testowej (zebrany w acceptance). Krok opcjonalny: zawsze zwraca 0,
  # bo audyt walidują osobne testy akceptacyjne, a odstępstwa są świadome i opisane (#11).
  if [[ ! -s $ARTIFACTS/lynis-report.dat ]]; then
    echo "Brak raportu Lynis (VM nie wystartowała lub skan się nie wykonał) — pomijam"
    return 0
  fi
  python3 ci/lynis_report.py "$ARTIFACTS/lynis-report.dat" | summary >/dev/null
  grep -oP '^hardening_index=\K\d+' "$ARTIFACTS/lynis-report.dat" |
    tail -1 | sed 's/^/Lynis hardening index: /' || true
}

# Flavor wlb-radiologia (#135): opt-in (etykieta build-radiologia / zmiana plików flavora / nocny build —
# workflow ustawia WLB_BUILD_RADIOLOGIA=1). Buduje warstwowo na obrazie bazowym i uruchamia tę samą
# akceptację (adaptacyjne 70-radiologia + 40-pulpit wykryją flavor). Łapie błędy runtime (np. installer FSL).
radiologia_flavor() {
  [[ ${WLB_BUILD_RADIOLOGIA:-0} == 1 ]] || {
    echo "pominięto: brak etykiety build-radiologia ani zmiany plików flavora (#135)"
    return 0
  }
  local rad_full="wlb-radiologia-$IMAGE_VERSION-$IMAGE_DATE" rad_img
  rad_img="$REPO_ROOT/output/$rad_full/$rad_full.qcow2"
  rm -rf "output/$rad_full"
  echo "== Build flavora wlb-radiologia (base_image=$IMAGE) =="
  if ! PACKER_LOG=1 PACKER_LOG_PATH="$LOGS/packer-radiologia.log" packer build -color=false -only='wlb-radiologia.*' \
    -var "image_version=$IMAGE_VERSION" -var "image_date=$IMAGE_DATE" \
    -var "build_cpus=$BUILD_CPUS" -var "build_memory=$BUILD_MEMORY" \
    -var "git_commit=$GIT_COMMIT" -var "git_describe=$GIT_DESCRIBE" \
    -var "git_dirty=$GIT_DIRTY" -var "build_run=$BUILD_RUN" -var "base_image=$IMAGE" packer/; then
    echo "build flavora wlb-radiologia nieudany (packer-radiologia.log w artefaktach etapu 5)"
    return 1
  fi
  echo "== Akceptacja wlb-radiologia =="
  acceptance "$rad_img" acceptance-radiologia
}

mkdir -p build/sca "$ARTIFACTS"
if [[ ${1:-} == image-sca ]]; then
  # osobny krok CI: artefakty ostatniego budowania, niezależnie od daty w nazwie
  # (najnowszy katalog, który faktycznie zawiera locki — mkdir powyżej mógł utworzyć pusty)
  if [[ ! -s $ARTIFACTS/renv.lock ]]; then
    latest=$(find build/artifacts -mindepth 2 -maxdepth 2 -name renv.lock -printf '%T@ %h\n' | sort -nr | head -1 | cut -d' ' -f2-)
    [[ -n $latest ]] && ARTIFACTS=$latest
  fi
  echo "Artefakty: $ARTIFACTS"
  run_check "Podatności pakietów w obrazie (raport)" image_sca
  run_check "Skan OVAL Canonical obrazu (raport)" image_oval
  finish
  exit
fi
step "Budowanie obrazu $FULL"
build_image
endstep
run_check "Kryteria akceptacji MVP" acceptance
run_check "Obserwowalność: zdarzenia z kontraktu w logu centralnym (SIEM)" siem_delivery
run_check "Wazuh: dekodery i reguły na logu z SIEM (#17)" siem_wazuh
run_check "Migracja na istniejącym dysku roboczym" migration
run_check "Dryf zamrożonych wersji (envs/*.lock vs obraz)" lock_drift
run_check "Jedno jądro w obrazie (#9)" kernel_single
run_check "Utwardzenie systemu (Lynis, raport)" hardening_report
run_check "Flavor wlb-radiologia: build + akceptacja (#135)" radiologia_flavor
finish
