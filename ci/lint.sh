#!/usr/bin/env bash
# Stage 1: lint, format i skan sekretów (najszybszy etap, bez sieci poza narzędziami).
#   FIX=1 ci/lint.sh   # poprawia formatowanie zamiast tylko je sprawdzać
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require shellcheck shfmt gitleaks ruff yamllint ansible-lint packer actionlint

SHFMT_FLAGS=(-i 2 -ci)
if [[ ${FIX:-0} == 1 ]]; then
  shfmt -w "${SHFMT_FLAGS[@]}" "${SHELL_SCRIPTS[@]}" tests/unit/helpers.bash tests/*-remote.sh
  ruff format "${PYTHON_FILES[@]}"
  ruff check --fix "${PYTHON_FILES[@]}"
  packer fmt packer/
fi

run_check "shellcheck (skrypty)" shellcheck -x "${SHELL_SCRIPTS[@]}" tests/*-remote.sh
run_check "shellcheck (testy bats)" shellcheck -x "${BATS_FILES[@]}"
run_check "shfmt (formatowanie powłoki)" shfmt -d "${SHFMT_FLAGS[@]}" "${SHELL_SCRIPTS[@]}" tests/unit/helpers.bash tests/*-remote.sh
run_check "ruff (lint Pythona)" ruff check "${PYTHON_FILES[@]}"
run_check "ruff format" ruff format --check "${PYTHON_FILES[@]}"
run_check "yamllint" yamllint --strict .
run_check "ansible-lint" bash -c 'cd ansible && ansible-lint --strict site.yml'
# actionlint uruchamia też shellcheck na blokach run: w workflow
run_check "actionlint (GitHub Actions)" actionlint
run_check "packer fmt" packer fmt -check -diff -recursive packer/
# historia commitów (to, co trafia do repozytorium) i drzewo robocze (niezacommitowane zmiany)
run_check "gitleaks (historia git)" gitleaks git --redact --no-banner .
run_check "gitleaks (drzewo robocze)" gitleaks dir --redact --no-banner .
finish
