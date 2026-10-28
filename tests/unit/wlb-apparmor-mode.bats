#!/usr/bin/env bats
# Testy jednostkowe wlb-apparmor-mode (#6, #65): tryb profilu z aa-status --json, odporny na
# formatowanie i na inny profil z "enforce" w tej samej linii. aa-status atrapowane (stub).

load helpers

APPARMOR_MODE="$REPO_ROOT/ansible/roles/base/files/wlb-apparmor-mode"

setup() {
  setup_sandbox
}

@test "rsyslogd enforce -> enforce" {
  stub aa-status 0 '{"profiles": {"/usr/sbin/rsyslogd": "enforce"}}'
  run "$APPARMOR_MODE" rsyslogd
  [ "$status" -eq 0 ]
  [ "$output" = enforce ]
}

@test "rsyslogd unconfined + inny profil enforce w tej samej linii -> unconfined (#65 regresja)" {
  # Stary 'aa-status --json | grep rsyslogd | grep enforce' zwracał tu kod 0 (fałszywie zaliczał
  # profil unconfined). Parser porównuje wartość dokładnego klucza i zwraca unconfined.
  stub aa-status 0 '{"profiles": {"/usr/sbin/rsyslogd": "unconfined", "/usr/bin/x": "enforce"}}'
  run "$APPARMOR_MODE" rsyslogd
  [ "$status" -eq 0 ]
  [ "$output" = unconfined ]
}

@test "brak pasującego profilu -> puste (nieładowany)" {
  stub aa-status 0 '{"profiles": {"/usr/bin/x": "enforce"}}'
  run "$APPARMOR_MODE" rsyslogd
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "rsyslogd complain -> complain" {
  stub aa-status 0 '{"profiles": {"/usr/sbin/rsyslogd": "complain"}}'
  run "$APPARMOR_MODE" rsyslogd
  [ "$output" = complain ]
}

@test "kilka profili rsyslogd o różnych trybach -> niejednoznaczne, != enforce" {
  stub aa-status 0 '{"profiles": {"/usr/sbin/rsyslogd": "enforce", "rsyslogd//helper": "complain"}}'
  run "$APPARMOR_MODE" rsyslogd
  [ "$output" = 'complain,enforce' ]
}

@test "błąd aa-status -> kod != 0 (nie zalicza po cichu)" {
  stub aa-status 1 ''
  run "$APPARMOR_MODE" rsyslogd
  [ "$status" -ne 0 ]
}

@test "brak argumentu podciągu -> błąd użycia" {
  run "$APPARMOR_MODE"
  [ "$status" -ne 0 ]
}
