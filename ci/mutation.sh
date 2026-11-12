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
  # Ocena wyniku jest w ci/mutation_score.py — ma testy jednostkowe (tests/unit/test_mutation_score.py).
  python3 ci/mutation_score.py --results "$MUT/python-results.txt" --allowlist "$allowlist" \
    --minimum "$PYTHON_MUTATION_MIN" --summary "$MUT/python-summary.md"
}

bash_mutations() {
  ci/mutation-bash.sh --output "$MUT/bash-summary.md"
}

run_check "Mutacje Pythona (mutmut, próg ${PYTHON_MUTATION_MIN}%)" python_mutations
run_check "Mutacje powłoki (każda mutacja musi zostać zabita)" bash_mutations
cat "$MUT"/*-summary.md 2>/dev/null | summary >/dev/null || true
finish
