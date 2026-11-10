#!/usr/bin/env bash
# Stage 4b: testy mutacyjne (BLOKUJĄCE).
#
# Python: mutmut 3.x mutuje ci/verify_platform_images.py i uruchamia jego testy jednostkowe.
# Wynik liczymy tylko z mutantów pokrytych testami — „no tests” nie wchodzi do mianownika, bo
# luki w pokryciu pilnuje osobny próg w stage 4. Timeout mutanta jest błędem: mutant „ucieka”
# przez zawieszenie testów, a nie przez ich jakość.
#
# Powłoka: harness tabelaryczny (ci/mutations/bash-mutations.tsv). Każda celowa mutacja skryptu
# obrazu MUSI zostać zabita przez wskazany test bats; przeżycie = luka w testach = czerwony stage.
#
# Progi można podnosić — nie obniżać bez uzasadnienia w PR.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require mutmut bats python3

PYTHON_MUTATION_MIN=${PYTHON_MUTATION_MIN:-70}
MUTMUT_MAX_CHILDREN=${MUTMUT_MAX_CHILDREN:-4}
MUT=build/mutation
rm -rf "$MUT" mutants .mutmut-cache
mkdir -p "$MUT"

python_mutations() {
  local log=$MUT/mutmut.log
  if ! mutmut run --max-children "$MUTMUT_MAX_CHILDREN" >"$log" 2>&1; then
    echo "mutmut run nie powiódł się (ostatnie 40 linii):"
    tail -n 40 "$log"
    return 1
  fi
  mutmut results --all true >"$MUT/python-results.txt" || return 1
  python3 - "$MUT" "$PYTHON_MUTATION_MIN" <<'PY'
import sys
from pathlib import Path

out = Path(sys.argv[1])
minimum = float(sys.argv[2])
statuses: dict[str, list[str]] = {}
for line in (out / "python-results.txt").read_text().splitlines():
    if ": " not in line:
        continue
    name, status = line.rsplit(": ", 1)
    statuses.setdefault(status, []).append(name.strip())

known = {"killed", "survived", "no tests", "timeout"}
unknown = {status: len(names) for status, names in statuses.items() if status not in known}
killed = len(statuses.get("killed", []))
survived = statuses.get("survived", [])
no_tests = len(statuses.get("no tests", []))
timeouts = len(statuses.get("timeout", []))
scored = killed + len(survived)
score = (100.0 * killed / scored) if scored else 0.0

lines = [
    "### Mutacje Pythona (mutmut, `ci/verify_platform_images.py`)",
    "",
    "| Zabite | Przeżyły | Bez testów | Timeout | Wynik | Próg |",
    "|---|---|---|---|---|---|",
    f"| {killed} | {len(survived)} | {no_tests} | {timeouts} | **{score:.1f}%** | {minimum:g}% |",
    "",
]
if survived:
    lines += ["Przeżyłe mutanty (do pokrycia testem albo świadomej allowlisty):", ""]
    lines += [f"- `{name}`" for name in survived]
    lines.append("")
text = "\n".join(lines)
print(text)
(out / "python-summary.md").write_text(text)

if scored == 0:
    sys.exit("Brak mutantów w zakresie — sprawdź sekcję [mutmut] w setup.cfg")
if unknown:
    detail = ", ".join(f"{status}={count}" for status, count in sorted(unknown.items()))
    sys.exit(f"Nieznane statusy mutmut ({detail}) — nie mogą po cichu wypadać z progu")
if timeouts:
    sys.exit(f"{timeouts} mutantów przekroczyło timeout — testy się zawieszają")
sys.exit(0 if score >= minimum else f"Wynik mutacji {score:.1f}% < {minimum:g}%")
PY
}

bash_mutations() {
  ci/mutation-bash.sh --output "$MUT/bash-summary.md"
}

run_check "Mutacje Pythona (mutmut, próg ${PYTHON_MUTATION_MIN}%)" python_mutations
run_check "Mutacje powłoki (każda mutacja musi zostać zabita)" bash_mutations
cat "$MUT"/*-summary.md 2>/dev/null | summary >/dev/null || true
finish
