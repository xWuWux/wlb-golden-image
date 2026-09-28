#!/usr/bin/env bash
# Stage 4: testy jednostkowe (bats dla skryptów powłoki, pytest dla Pythona) z progami pokrycia.
# Progi można podnosić — nie obniżać bez uzasadnienia w PR.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require bats pytest coverage
# kcov mapuje ślad wykonania (xtrace) na wiersze skryptów; bez locale UTF-8 wiersze z polskimi
# znakami nie są rozpoznawane i pokrycie wychodzi 0% (np. w kontenerach bez ustawionego LANG)
[[ ${LC_ALL:-${LANG:-}} == *UTF-8* ]] || export LANG=C.UTF-8
BASH_COVERAGE_MIN=${BASH_COVERAGE_MIN:-85}
PYTHON_COVERAGE_MIN=${PYTHON_COVERAGE_MIN:-90}
COV=build/coverage
rm -rf "$COV"
mkdir -p "$COV"

shell_tests() {
  if ! command -v kcov >/dev/null; then
    if [[ -n ${CI:-} ]]; then
      echo "kcov jest wymagany w CI"
      return 1
    fi
    echo "kcov niedostępny — testy bez pomiaru pokrycia (sudo apt install kcov)"
    bats tests/unit
    return
  fi
  # pokrycie tylko skryptów instalowanych w obrazie (nie atrap i nie samych testów)
  kcov --include-path="$REPO_ROOT/ansible/roles" "$COV/bash" bats tests/unit
}

shell_coverage_gate() {
  command -v kcov >/dev/null || return 0
  python3 - "$COV/bash" "$BASH_COVERAGE_MIN" <<'PY'
import json, sys
from pathlib import Path
root, minimum = Path(sys.argv[1]), float(sys.argv[2])
report = json.loads(next(root.glob("bats*/coverage.json")).read_text())
lines = [f"| `{f['file'].split('ansible/roles/')[-1]}` | {f['percent_covered']}% |" for f in report["files"]]
total = float(report["percent_covered"])
text = "\n".join(["### Pokrycie skryptów powłoki (kcov)", "", "| Plik | Pokrycie |", "|---|---|", *lines,
                  f"| **razem** | **{total}%** (próg {minimum:g}%) |", ""])
print(text)
open("build/coverage/bash-summary.md", "w").write(text)
sys.exit(0 if total >= minimum else f"Pokrycie powłoki {total}% < {minimum:g}%")
PY
}

python_tests() {
  coverage run --branch --data-file="$COV/.coverage" \
    --include='ci/*.py,ansible/roles/tljh/files/*' -m pytest -q -p no:cacheprovider tests/unit
}

python_coverage_gate() {
  coverage xml --data-file="$COV/.coverage" -o "$COV/python-coverage.xml" -q
  {
    echo "### Pokrycie Pythona (coverage.py, gałęzie)"
    echo
    coverage report --data-file="$COV/.coverage" --format=markdown
    echo
    echo "Próg: ${PYTHON_COVERAGE_MIN}%"
  } | tee "$COV/python-summary.md"
  coverage report --data-file="$COV/.coverage" --fail-under="$PYTHON_COVERAGE_MIN" >/dev/null
}

run_check "Testy powłoki (bats)" shell_tests
run_check "Próg pokrycia powłoki (${BASH_COVERAGE_MIN}%)" shell_coverage_gate
run_check "Testy Pythona (pytest)" python_tests
run_check "Próg pokrycia Pythona (${PYTHON_COVERAGE_MIN}%)" python_coverage_gate
cat "$COV"/*-summary.md 2>/dev/null | summary >/dev/null || true
finish
