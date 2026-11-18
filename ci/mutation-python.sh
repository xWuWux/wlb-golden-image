#!/usr/bin/env bash
# Adapter mutmut dla etapu 4b.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
MUT=build/mutation
PYTHON_MUTATION_MIN=${PYTHON_MUTATION_MIN:-85}
MUTMUT_MAX_CHILDREN=${MUTMUT_MAX_CHILDREN:-4}
log=$MUT/mutmut.log
allowlist=ci/mutations/python-allowlist.txt
if ! mutmut run --max-children "$MUTMUT_MAX_CHILDREN" >"$log" 2>&1; then
  echo "mutmut run nie powiódł się (ostatnie 40 linii):"
  tail -n 40 "$log"
  exit 1
fi
mutmut results --all true >"$MUT/python-results.txt" || exit 1
# Ocena wyniku jest w ci/mutation_score.py — ma testy jednostkowe (tests/unit/test_mutation_score.py).
python3 ci/mutation_score.py --results "$MUT/python-results.txt" --allowlist "$allowlist" \
  --minimum "$PYTHON_MUTATION_MIN" --summary "$MUT/python-summary.md"
