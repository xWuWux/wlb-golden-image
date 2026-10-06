#!/usr/bin/env bash
# Stage 6a: benchmarki wydajności zbudowanego obrazu względem ci/perf-budget.env.
#   ci/perf.sh [obraz.qcow2]       # domyślnie najnowszy z output/
#   PERF_ENFORCE=0 ci/perf.sh      # tylko raport, bez bramki
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
# shellcheck source=tests/lib/local-common.sh
. tests/lib/local-common.sh
IMAGE=${1:-$(find output -name '*.qcow2' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)}
[[ -f $IMAGE ]] || {
  echo "Brak obrazu — najpierw stage 5 albo make build"
  exit 1
}
mkdir -p build/perf
RESULTS=build/perf/results.txt
SAMPLES=build/perf/samples.txt
: >"$RESULTS"
: >"$SAMPLES"

# VM dobrana do hosta (bez nadsubskrypcji zagnieżdżonej wirtualizacji) i liczba powtórzeń (#10).
# PERF_REPEAT dotyczy tanich metryk w VM; boot jest kosztowny, więc ma osobny (domyślnie 1)
# PERF_BOOT_REPEAT — 5 pełnych bootów łatwo przekroczyłoby limit czasu etapu 6a.
perf_vm_resources
REPEAT=${PERF_REPEAT:-1}
[[ $REPEAT =~ ^[0-9]+$ ]] && ((REPEAT >= 1)) || REPEAT=1
BOOT_REPEAT=${PERF_BOOT_REPEAT:-1}
[[ $BOOT_REPEAT =~ ^[0-9]+$ ]] && ((BOOT_REPEAT >= 1)) || BOOT_REPEAT=1

# boot_to_ready: BOOT_REPEAT osobnych startów VM; mediana jako wartość, próbki do kalibracji
boot_samples=()
for _ in $(seq 1 "$BOOT_REPEAT"); do
  tests/stop-local.sh >/dev/null
  t0=$(date +%s)
  tests/run-local.sh "$IMAGE" >/dev/null
  boot_samples+=("$(($(date +%s) - t0))")
done
boot_median=$(printf '%s\n' "${boot_samples[@]}" | sort -n | awk '{ a[NR] = $0 } END { print a[int((NR - 1) / 2) + 1] }')
echo "boot_to_ready_s $boot_median s" >>"$RESULTS"
echo "SAMPLE boot_to_ready_s ${boot_samples[*]}" >>"$SAMPLES"

# środowisko pomiaru (host vs gość) — kontekst do interpretacji i kalibracji budżetów
{
  echo "host_cpus $(nproc)"
  echo "host_mem_total_kb $(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  echo "host_cpu_model $(lscpu 2>/dev/null | sed -n 's/^Model name:[[:space:]]*//p' | head -1)"
  echo "vm_cpus $VM_CPUS"
  echo "vm_memory_mb $VM_MEMORY"
  # polecenie ma się wykonać w VM — cudzysłów pojedynczy jest zamierzony (nproc gościa, nie hosta)
  # shellcheck disable=SC2016
  "${SSH[@]}" 'echo "guest_cpus $(nproc)"; grep MemTotal /proc/meminfo' 2>/dev/null
} >build/perf/env.txt

# pozostałe metryki w działającej VM (ostatni boot zostawił ją uruchomioną)
remote_run tests/perf-remote.sh "$REPEAT" >build/perf/remote.out || true
grep '^SAMPLE ' build/perf/remote.out >>"$SAMPLES" || true
grep -v '^SAMPLE ' build/perf/remote.out >>"$RESULTS" || true
tests/stop-local.sh >/dev/null

status=0
python3 - "$RESULTS" ci/perf-budget.env "${PERF_ENFORCE:-1}" <<'PY' || status=$?
import sys
results, budget_file, enforce = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
budget = {}
for line in open(budget_file):
    line = line.split("#", 1)[0].strip()
    if line:
        key, value = line.split("=")
        budget[key.strip()] = float(value)
rows, over = [], 0
measured = {}
for line in open(results):
    parts = line.split()
    if len(parts) == 3 and parts[1].replace(".", "").isdigit():
        measured[parts[0]] = (float(parts[1]), parts[2])
for key, limit in budget.items():
    if key not in measured:
        rows.append(f"| {key} | — | {limit:g} | brak pomiaru |")
        over += 1
        continue
    value, unit = measured[key]
    ok = value >= limit if key.endswith("_mbps") else value <= limit
    over += not ok
    rows.append(f"| {key} | {value:g} {unit} | {'≥' if key.endswith('_mbps') else '≤'} {limit:g} | {'OK' if ok else 'PRZEKROCZONY'} |")
text = "\n".join(["### Benchmarki wydajności", "", "| Metryka | Wynik | Budżet | Status |", "|---|---|---|---|", *rows, ""])
print(text)
open("build/perf/summary.md", "w").write(text)
sys.exit(1 if over and enforce else 0)
PY
summary <build/perf/summary.md >/dev/null
exit $status
