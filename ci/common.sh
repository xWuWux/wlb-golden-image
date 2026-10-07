# shellcheck shell=bash disable=SC2034  # tablice plików używane przez skrypty dołączające
# Wspólne ustawienia skryptów CI (dołączane przez ci/*.sh).
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TOOLS_DIR=${TOOLS_DIR:-$REPO_ROOT/.tools}
PATH="$TOOLS_DIR/bin:$TOOLS_DIR/bats/bin:$TOOLS_DIR/venv-lint/bin:$TOOLS_DIR/venv-unit/bin:$TOOLS_DIR/venv-security/bin:$PATH"
export REPO_ROOT TOOLS_DIR PATH
cd "$REPO_ROOT"

# Pliki objęte lintem i testami
SHELL_SCRIPTS=(
  przewodnik-vm.sh
  ci/*.sh
  packer/scripts/*.sh
  tests/*.sh tests/lib/*.sh
  ansible/roles/lab_config/files/wlb-firstboot
  ansible/roles/storage/files/wlb-sluza-out-mover
)
BATS_FILES=(tests/unit/*.bats tests/unit/helpers.bash)
PYTHON_FILES=(ci/*.py tests/*.py tests/unit/*.py ansible/roles/tljh/files/wlb-hub-user)

step() {
  if [[ -n ${GITHUB_ACTIONS:-} ]]; then echo "::group::$*"; else echo && echo "== $*"; fi
}
endstep() { [[ -z ${GITHUB_ACTIONS:-} ]] || echo "::endgroup::"; }

# die KOMUNIKAT — wypisuje błąd na stderr i kończy z kodem 1
die() {
  echo "BŁĄD: $*" >&2
  exit 1
}

# summary <<EOF — dopisuje markdown do podsumowania joba w GitHub Actions (lokalnie: na stdout)
summary() {
  if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then cat >>"$GITHUB_STEP_SUMMARY"; else cat; fi
}

require() {
  local tool
  for tool in "$@"; do
    command -v "$tool" >/dev/null || {
      echo "Brak narzędzia: $tool — uruchom ci/install-tools.sh"
      exit 1
    }
  done
}

# Uruchamia wszystkie sprawdzenia i raportuje wszystkie błędy naraz (nie kończy na pierwszym)
FAILED=()
run_check() {
  local name=$1
  shift
  step "$name"
  if "$@"; then
    endstep
  else
    endstep
    echo "BŁĄD: $name"
    FAILED+=("$name")
  fi
}
finish() {
  if ((${#FAILED[@]})); then
    printf '\nNie przeszło (%d):\n' "${#FAILED[@]}"
    printf '  - %s\n' "${FAILED[@]}"
    exit 1
  fi
  echo
  echo "Wszystkie sprawdzenia przeszły."
}
