#!/usr/bin/env bats
# scan_with_status (ci/common.sh): kod wyjścia skanera SARIF dla Code scanning (#257).

load helpers

setup() {
  SCA="$BATS_TEST_TMPDIR/sca"
  mkdir -p "$SCA"
}

# scan KOD [POLECENIE] — uruchamia scan_with_status w osobnej powłoce (common.sh ustawia set -e i cd)
scan() {
  run bash -c '. "$1/ci/common.sh"; shift; scan_with_status "$@"' _ "$REPO_ROOT" "$SCA" semgrep "${@}"
}

@test "kod wyjścia skanera zapisany i przekazany dalej, także znaleziska (#257)" {
  # shellcheck disable=SC2016  # $0 rozwija powłoka potomna
  scan bash -c 'echo "{}" >"$0/semgrep.sarif"; exit 1' "$SCA"
  [ "$status" -eq 1 ]
  [ "$(cat "$SCA/semgrep.exit")" = 1 ]
  [ -f "$SCA/semgrep.sarif" ]
}

@test "czysty skan: kod 0 zapisany (#257)" {
  scan true
  [ "$status" -eq 0 ]
  [ "$(cat "$SCA/semgrep.exit")" = 0 ]
}

@test "stary raport i status usunięte przed skanem — awaria nie zostawia poprzedniego wyniku (#257)" {
  echo stary >"$SCA/semgrep.sarif"
  echo 0 >"$SCA/semgrep.exit"
  echo inny >"$SCA/checkov.sarif"
  scan bash -c 'exit 7'
  [ "$status" -eq 7 ]
  [ ! -e "$SCA/semgrep.sarif" ]
  [ "$(cat "$SCA/semgrep.exit")" = 7 ]
  # raport innego narzędzia nie jest kasowany
  [ "$(cat "$SCA/checkov.sarif")" = inny ]
}

@test "skaner zabity przed zakończeniem: brak pliku .exit, czyli not_run, nie clean (#257)" {
  echo 0 >"$SCA/semgrep.exit"
  run bash -c '. "$1/ci/common.sh"; scan_with_status "$2" semgrep bash -c "kill -9 \$PPID"' _ "$REPO_ROOT" "$SCA"
  [ "$status" -ne 0 ]
  [ ! -e "$SCA/semgrep.exit" ]
}
