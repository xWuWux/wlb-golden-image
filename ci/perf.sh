#!/usr/bin/env bash
# Stage 6a: benchmarki wydajności zbudowanego obrazu względem ci/perf-budget.env.
#   ci/perf.sh [obraz.qcow2]       # domyślnie jedyny obraz wlb-general-* w output/
#   PERF_IMAGE=... ci/perf.sh      # jawny obraz, gdy w output/ jest więcej niż jeden
#   PERF_ENFORCE=0 ci/perf.sh      # przekroczenia budżetu tylko raportowane; błędy pomiaru blokują
#   PERF_VERIFY_IMAGE=0 ci/perf.sh # świadome pominięcie weryfikacji sumy sha256 obrazu
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
# shellcheck source=tests/lib/local-common.sh
. tests/lib/local-common.sh

mkdir -p build/perf
RESULTS=build/perf/results.txt
SAMPLES=build/perf/samples.txt
: >"$RESULTS"
: >"$SAMPLES"

SUMMARY_READY=0
# shellcheck disable=SC2329 # wywoływana przez trap EXIT
on_exit() {
  local rc=$?
  if ((rc != 0 && SUMMARY_READY == 0)); then
    {
      echo "### Benchmarki wydajności"
      echo
      echo "**BŁĄD POMIARU/KONFIGURACJI:** skrypt przerwany (kod $rc)."
      echo
      echo "Zobacz log joba oraz build/perf/remote.out i build/perf/remote.err."
    } >build/perf/summary.md
    summary <build/perf/summary.md >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap on_exit EXIT

perf_die() {
  {
    echo "### Benchmarki wydajności"
    echo
    echo "**BŁĄD POMIARU/KONFIGURACJI:** $*"
    echo
    echo "Nie oceniano budżetów; szczegóły w logu joba."
  } >build/perf/summary.md
  summary <build/perf/summary.md >/dev/null 2>&1 || true
  SUMMARY_READY=1
  echo "BŁĄD: $*" >&2
  exit 2
}

parse_bool() {
  case ${1,,} in
    1 | true | yes | on) echo 1 ;;
    0 | false | no | off) echo 0 ;;
    *) return 1 ;;
  esac
}

positive_int() {
  local value=$1 maximum=$2
  if [[ ! $value =~ ^[1-9][0-9]*$ ]] || ((value > maximum)); then
    return 1
  fi
  echo "$value"
}

# perf_die MUSI działać w głównej powłoce (nie w subshellu $(...)), inaczej jego komunikat
# i kod wyjścia giną, a trap EXIT raportuje tylko ogólne „skrypt przerwany”.
if ! ENFORCE=$(parse_bool "${PERF_ENFORCE:-1}"); then
  perf_die "PERF_ENFORCE=${PERF_ENFORCE:-}: oczekiwano 0/1, true/false, yes/no albo on/off"
fi
if ! REPEAT=$(positive_int "${PERF_REPEAT:-1}" 20); then
  perf_die "PERF_REPEAT=${PERF_REPEAT:-}: oczekiwano liczby całkowitej 1..20"
fi
if ! BOOT_REPEAT=$(positive_int "${PERF_BOOT_REPEAT:-1}" 5); then
  perf_die "PERF_BOOT_REPEAT=${PERF_BOOT_REPEAT:-}: oczekiwano liczby całkowitej 1..5"
fi
if ! VERIFY_IMAGE=$(parse_bool "${PERF_VERIFY_IMAGE:-1}"); then
  perf_die "PERF_VERIFY_IMAGE=${PERF_VERIFY_IMAGE:-}: oczekiwano wartości logicznej"
fi

# Wybór obrazu jest jawny: argument, PERF_IMAGE albo dokładnie jeden obraz wlb-general-*.
# `find ... | head -1` wybierał przypadkowy/najnowszy plik, niekoniecznie ten z etapu 5 (#10).
IMAGE=${1:-${PERF_IMAGE:-}}
if [[ -z $IMAGE ]]; then
  mapfile -t candidates < <(find output -mindepth 2 -maxdepth 2 -type f -name 'wlb-general-*.qcow2' -print 2>/dev/null | sort)
  case ${#candidates[@]} in
    0) perf_die "brak obrazu wlb-general-* w output/ — najpierw stage 5 albo make build" ;;
    1) IMAGE=${candidates[0]} ;;
    *) perf_die "niejednoznaczny obraz; podaj argument lub PERF_IMAGE. Kandydaci: ${candidates[*]}" ;;
  esac
fi
[[ -f $IMAGE && ! -L $IMAGE && -s $IMAGE ]] || perf_die "obraz nie jest niepustym zwykłym plikiem: $IMAGE"
if ! command -v qemu-img >/dev/null || ! qemu-img info "$IMAGE" >/dev/null 2>&1; then
  perf_die "qemu-img nie potrafi odczytać obrazu: $IMAGE"
fi

IMAGE_SHA256=unverified
if ((VERIFY_IMAGE)); then
  checksum_file=$IMAGE.sha256
  [[ -f $checksum_file ]] || perf_die "brak sumy $checksum_file; ustaw PERF_VERIFY_IMAGE=0 tylko świadomie"
  # Packer zapisuje sumę w formacie "<hash>  <plik>" albo "sha256:<hash>"; liczy się
  # dokładnie jeden 64-znakowy hash, a nie konkretny układ białych znaków.
  mapfile -t checksum_hashes < <(grep -oE '[0-9a-fA-F]{64}' "$checksum_file")
  ((${#checksum_hashes[@]} == 1)) ||
    perf_die "$checksum_file: oczekiwano dokładnie jednego sha256"
  expected_checksum=${checksum_hashes[0]}
  actual_checksum=$(sha256sum "$IMAGE" | awk '{print $1}')
  [[ ${actual_checksum,,} == "${expected_checksum,,}" ]] ||
    perf_die "suma obrazu nie zgadza się z $checksum_file"
  IMAGE_SHA256=$actual_checksum
fi

# VM dobrana do hosta (bez nadsubskrypcji zagnieżdżonej wirtualizacji) i liczba powtórzeń (#10).
# PERF_REPEAT dotyczy tanich metryk w VM; boot jest kosztowny, więc ma osobny PERF_BOOT_REPEAT
# (lokalnie domyślnie 1, w CI 2) — 5 pełnych bootów łatwo przekroczyłoby limit czasu etapu 6a.
perf_vm_resources

# boot_to_ready: BOOT_REPEAT osobnych startów VM; mediana jako wartość, próbki do kalibracji.
# Metryka obejmuje CAŁY tests/run-local.sh (overlay, PKI, seed, QEMU, SSH, cloud-init,
# firstboot), nie sam boot gościa ani gotowość UI — dlatego nie wolno porównywać jej z SLA.
boot_samples=()
boot_failed=0
for attempt in $(seq 1 "$BOOT_REPEAT"); do
  tests/stop-local.sh >/dev/null 2>&1 || true
  t0=$(date +%s)
  if ! tests/run-local.sh "$IMAGE" >/dev/null 2>&1; then
    echo "ERROR boot_to_ready_s expected=$BOOT_REPEAT observed=${#boot_samples[@]} reason=provisioning_failed attempt=$attempt" >>"$RESULTS"
    boot_failed=1
    break
  fi
  elapsed=$(($(date +%s) - t0))
  if ((elapsed > 0)); then
    boot_samples+=("$elapsed")
  else
    echo "ERROR boot_to_ready_s expected=$BOOT_REPEAT observed=${#boot_samples[@]} reason=zero_duration attempt=$attempt" >>"$RESULTS"
    boot_failed=1
    break
  fi
done
if ((boot_failed == 0)); then
  boot_median=$(printf '%s\n' "${boot_samples[@]}" | sort -n |
    awk '{ a[NR] = $1 } END { if (NR % 2) print a[(NR + 1) / 2]; else printf "%.3f\n", (a[NR / 2] + a[NR / 2 + 1]) / 2 }')
  echo "boot_to_ready_s $boot_median s" >>"$RESULTS"
  echo "SAMPLE boot_to_ready_s ${boot_samples[*]}" >>"$SAMPLES"
fi

# środowisko pomiaru (host vs gość) — kontekst do interpretacji i kalibracji budżetów
{
  echo "image_path $IMAGE"
  echo "image_size_bytes $(stat -c %s "$IMAGE")"
  echo "image_sha256 $IMAGE_SHA256"
  echo "git_sha $(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "git_dirty $(git diff --quiet HEAD 2>/dev/null && echo 0 || echo 1)"
  echo "runner ${GITHUB_RUN_ID:-local}"
  echo "perf_repeat $REPEAT"
  echo "perf_boot_repeat $BOOT_REPEAT"
  echo "perf_enforce $ENFORCE"
  echo "host_cpus $(nproc)"
  echo "host_mem_total_kb $(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  echo "host_cpu_model $(lscpu 2>/dev/null | sed -n 's/^Model name:[[:space:]]*//p' | head -1)"
  echo "cgroup_memory_max $(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo unknown)"
  echo "cgroup_cpu_max $(cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo unknown)"
  echo "qemu $(qemu-img --version 2>/dev/null | head -1)"
  echo "vm_cpus $VM_CPUS"
  echo "vm_memory_mb $VM_MEMORY"
  # polecenie ma się wykonać w VM — cudzysłów pojedynczy jest zamierzony (nproc gościa, nie hosta)
  # shellcheck disable=SC2016
  "${SSH[@]}" 'echo "guest_cpus $(nproc)"; grep MemTotal /proc/meminfo' 2>/dev/null || echo "guest_env unavailable"
} >build/perf/env.txt

# pozostałe metryki w działającej VM (ostatni boot zostawił ją uruchomioną)
remote_status=0
remote_run tests/perf-remote.sh "$REPEAT" >build/perf/remote.out 2>build/perf/remote.err || remote_status=$?
grep '^SAMPLE ' build/perf/remote.out >>"$SAMPLES" || true
grep -v '^SAMPLE ' build/perf/remote.out >>"$RESULTS" || true
tests/stop-local.sh >/dev/null 2>&1 || true

status=0
python3 ci/perf_summary.py \
  --results "$RESULTS" \
  --samples "$SAMPLES" \
  --budget ci/perf-budget.env \
  --remote-status "$remote_status" \
  --enforce "$ENFORCE" \
  --output build/perf/summary.md || status=$?
SUMMARY_READY=1
summary <build/perf/summary.md >/dev/null 2>&1 || true
exit "$status"
