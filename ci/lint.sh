#!/usr/bin/env bash
# Stage 1: lint, format i skan sekretów (najszybszy etap, bez sieci poza narzędziami).
#   FIX=1 ci/lint.sh   # poprawia formatowanie zamiast tylko je sprawdzać
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require shellcheck shfmt gitleaks ruff yamllint ansible-lint packer actionlint

SHFMT_FLAGS=(-i 2 -ci)
if [[ ${FIX:-0} == 1 ]]; then
  shfmt -w "${SHFMT_FLAGS[@]}" "${SHELL_SCRIPTS[@]}" tests/unit/helpers.bash tests/*-remote.sh tests/acceptance.d/*.sh
  ruff format "${PYTHON_FILES[@]}"
  ruff check --fix "${PYTHON_FILES[@]}"
  packer fmt packer/
fi

run_check "shellcheck (skrypty)" shellcheck -x "${SHELL_SCRIPTS[@]}" tests/*-remote.sh
run_check "shellcheck (testy bats)" shellcheck -x "${BATS_FILES[@]}"
# Fragmenty acceptance.d/ odwołują się do funkcji/zmiennych z prefiksu (remote-common.sh + prep),
# więc lintujemy ZŁOŻONY skrypt — dokładnie tak, jak trafia na VM (tests/acceptance.sh).
# $(mktemp)/$f mają się rozwinąć w wewnętrznym bashu — pojedyncze cudzysłowy zamierzone.
# shellcheck disable=SC2016
run_check "shellcheck (acceptance złożone)" bash -c '
  f=$(mktemp)
  cat tests/lib/remote-common.sh tests/acceptance-remote.sh tests/acceptance.d/*.sh >"$f"
  printf "\nsummary\n" >>"$f"
  shellcheck -x "$f"; rc=$?; rm -f "$f"; exit $rc'
run_check "shfmt (formatowanie powłoki)" shfmt -d "${SHFMT_FLAGS[@]}" "${SHELL_SCRIPTS[@]}" tests/unit/helpers.bash tests/*-remote.sh tests/acceptance.d/*.sh
run_check "ruff (lint Pythona)" ruff check "${PYTHON_FILES[@]}"
run_check "ruff format" ruff format --check "${PYTHON_FILES[@]}"
run_check "yamllint" yamllint --strict .
run_check "ansible-lint" bash -c 'cd ansible && ansible-lint --strict site.yml'
# actionlint uruchamia też shellcheck na blokach run: w workflow
run_check "actionlint (GitHub Actions)" actionlint
run_check "packer fmt" packer fmt -check -diff -recursive packer/
# znaczniki konfliktu trafiaja do repo nawet gdy linter znajomego jezyka ich nie widzi (.md, .txt) — f0b4b5a
run_check "znaczniki konfliktu (merge markers)" python3 ci/conflict_markers.py
# historia commitów (to, co trafia do repozytorium) i drzewo robocze (niezacommitowane zmiany)
run_check "gitleaks (historia git)" gitleaks git --redact --no-banner .
run_check "gitleaks (drzewo robocze)" gitleaks dir --redact --no-banner .
finish
