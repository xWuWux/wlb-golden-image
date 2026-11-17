#!/usr/bin/env bats
# scan_with_status (ci/common.sh): kod wyjścia skanera SARIF dla Code scanning (#257).

load helpers

setup() {
  SCA="$BATS_TEST_TMPDIR/sca"
  mkdir -p "$SCA"
  # osobny plik zamiast `bash -c`: pod kcov (BASH_ENV z pułapką DEBUG) `bash -c` nie ma BASH_SOURCE,
  # a common.sh działa z set -u
  SCAN="$BATS_TEST_TMPDIR/scan.sh"
  cat >"$SCAN" <<EOF
#!/usr/bin/env bash
. "$REPO_ROOT/ci/common.sh"
scan_with_status "\$@"
EOF
  chmod +x "$SCAN"
}

@test "kod wyjścia skanera zapisany i przekazany dalej, także znaleziska (#257)" {
  # shellcheck disable=SC2016  # $0 rozwija powłoka potomna
  run "$SCAN" "$SCA" semgrep bash -c 'echo "{}" >"$0/semgrep.sarif"; exit 1' "$SCA"
  [ "$status" -eq 1 ]
  [ "$(cat "$SCA/semgrep.exit")" = 1 ]
  [ -f "$SCA/semgrep.sarif" ]
}

@test "czysty skan: kod 0 zapisany (#257)" {
  run "$SCAN" "$SCA" semgrep true
  [ "$status" -eq 0 ]
  [ "$(cat "$SCA/semgrep.exit")" = 0 ]
}

@test "katalog raportów tworzony, gdy go nie ma (#257)" {
  run "$SCAN" "$SCA/nowy" checkov true
  [ "$status" -eq 0 ]
  [ "$(cat "$SCA/nowy/checkov.exit")" = 0 ]
}

@test "stary raport i status usunięte przed skanem — awaria nie zostawia poprzedniego wyniku (#257)" {
  echo stary >"$SCA/semgrep.sarif"
  echo 0 >"$SCA/semgrep.exit"
  echo inny >"$SCA/checkov.sarif"
  run "$SCAN" "$SCA" semgrep bash -c 'exit 7'
  [ "$status" -eq 7 ]
  [ ! -e "$SCA/semgrep.sarif" ]
  [ "$(cat "$SCA/semgrep.exit")" = 7 ]
  # raport innego narzędzia nie jest kasowany
  [ "$(cat "$SCA/checkov.sarif")" = inny ]
}

@test "skaner zabity przed zakończeniem: brak pliku .exit, czyli not_run, nie clean (#257)" {
  echo 0 >"$SCA/semgrep.exit"
  # shellcheck disable=SC2016  # $PPID rozwija powłoka potomna (rodzic = skrypt ze scan_with_status)
  run "$SCAN" "$SCA" semgrep bash -c 'kill -9 $PPID'
  [ "$status" -ne 0 ]
  [ ! -e "$SCA/semgrep.exit" ]
}
