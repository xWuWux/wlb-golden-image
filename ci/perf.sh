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

tests/stop-local.sh >/dev/null
t0=$(date +%s)
tests/run-local.sh "$IMAGE" >/dev/null
echo "boot_to_ready_s $(($(date +%s) - t0)) s" >"$RESULTS"
remote_run tests/perf-remote.sh >>"$RESULTS" || true
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
