#!/usr/bin/env bash
# Stage 4b: testy mutacyjne (BLOKUJĄCE).
#
# Python: mutmut 3.x mutuje ci/verify_platform_images.py i uruchamia jego testy jednostkowe.
# Mianownik progu to killed + unlisted (mutanty pokryte testami, bez allowlisty): „no tests” nie
# wchodzi, bo globalny próg pokrycia stage 4 nie pilnuje pojedynczego pliku (znana luka — do
# domknięcia testami main()), a mutanty z allowlisty są równoważne z definicji. Timeout mutanta
# jest błędem: mutant „ucieka” przez zawieszenie testów, a nie przez ich jakość.
#
# Powłoka: harness tabelaryczny (ci/mutations/bash-mutations.tsv). Każda celowa mutacja skryptu
# obrazu MUSI zostać zabita przez wskazany test bats; przeżycie = luka w testach = czerwony stage.
#
# Bramka: brak przeżytych mutantów spoza allowlisty (`ci/mutations/python-allowlist.txt` — tylko
# mutanty równoważne, z uzasadnieniem) ORAZ wynik >= PYTHON_MUTATION_MIN. Progi podnosić, nie obniżać.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require mutmut bats python3

PYTHON_MUTATION_MIN=${PYTHON_MUTATION_MIN:-85}
MUTMUT_MAX_CHILDREN=${MUTMUT_MAX_CHILDREN:-4}
MUT=build/mutation
rm -rf "$MUT" mutants .mutmut-cache
mkdir -p "$MUT"

python_mutations() {
  local log=$MUT/mutmut.log
  local allowlist=ci/mutations/python-allowlist.txt
  if ! mutmut run --max-children "$MUTMUT_MAX_CHILDREN" >"$log" 2>&1; then
    echo "mutmut run nie powiódł się (ostatnie 40 linii):"
    tail -n 40 "$log"
    return 1
  fi
  mutmut results --all true >"$MUT/python-results.txt" || return 1
  python3 - "$MUT" "$PYTHON_MUTATION_MIN" "$allowlist" <<'PY'
import sys
from pathlib import Path

out = Path(sys.argv[1])
minimum = float(sys.argv[2])
allowlist_path = Path(sys.argv[3])

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

allowed: set[str] = set()
allowlist_errors: list[str] = []
if allowlist_path.is_file():
    for number, raw in enumerate(allowlist_path.read_text().splitlines(), 1):
        name, _, reason = raw.partition("#")
        name = name.strip()
        if not name:
            continue
        if not reason.strip():
            allowlist_errors.append(f"{allowlist_path}:{number}: brak uzasadnienia po #")
        allowed.add(name)
allowed_hit = [name for name in survived if name in allowed]
unlisted = [name for name in survived if name not in allowed]
stale = sorted(allowed - set(survived))

scored = killed + len(unlisted)
score = (100.0 * killed / scored) if scored else 0.0

lines = [
    "### Mutacje Pythona (mutmut, `ci/verify_platform_images.py`)",
    "",
    "| Zabite | Przeżyły | z allowlisty | spoza allowlisty | Bez testów | Timeout | Wynik | Próg |",
    "|---|---|---|---|---|---|---|---|",
    f"| {killed} | {len(survived)} | {len(allowed_hit)} | {len(unlisted)} | {no_tests} | {timeouts} | "
    f"**{score:.1f}%** | {minimum:g}% |",
    "",
]
if unlisted:
    lines += ["Przeżyłe mutanty **spoza allowlisty** (dopisz test albo uzasadnij w allowliście):", ""]
    lines += [f"- `{name}`" for name in unlisted]
    lines.append("")
if allowed_hit:
    lines += ["Przeżyłe mutanty z allowlisty (równoważne):", ""]
    lines += [f"- `{name}`" for name in allowed_hit]
    lines.append("")
if stale:
    lines += ["Allowlista nieaktualna — te mutanty już nie przeżywają (usuń wpisy):", ""]
    lines += [f"- `{name}`" for name in stale]
    lines.append("")
text = "\n".join(lines)
print(text)
(out / "python-summary.md").write_text(text)

if allowlist_errors:
    sys.exit("Allowlista bez uzasadnienia:\n" + "\n".join(allowlist_errors))
if scored == 0:
    sys.exit("Brak mutantów w zakresie — sprawdź sekcję [mutmut] w setup.cfg")
if unknown:
    detail = ", ".join(f"{status}={count}" for status, count in sorted(unknown.items()))
    sys.exit(f"Nieznane statusy mutmut ({detail}) — nie mogą po cichu wypadać z progu")
if timeouts:
    sys.exit(f"{timeouts} mutantów przekroczyło timeout — testy się zawieszają")
if unlisted:
    sys.exit(f"{len(unlisted)} przeżyłych mutantów spoza allowlisty — dopisz test albo uzasadnij wpis")
if score < minimum:
    sys.exit(f"Wynik mutacji {score:.1f}% < {minimum:g}%")
PY
}

bash_mutations() {
  ci/mutation-bash.sh --output "$MUT/bash-summary.md"
}

run_check "Mutacje Pythona (mutmut, próg ${PYTHON_MUTATION_MIN}%)" python_mutations
run_check "Mutacje powłoki (każda mutacja musi zostać zabita)" bash_mutations
cat "$MUT"/*-summary.md 2>/dev/null | summary >/dev/null || true
finish
