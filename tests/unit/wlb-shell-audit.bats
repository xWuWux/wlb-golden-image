#!/usr/bin/env bats
# shellcheck disable=SC2016  # polecenia w pojedynczych cudzysłowach rozwija powłoka testowana, nie bats
# Rejestrowanie poleceń powłoki badaczy (szablon roli logging, renderowany z UID 10000–59999).

load helpers

setup() {
  setup_sandbox
  stub logger
  SCRIPT="$BATS_TEST_TMPDIR/wlb-shell-audit.sh"
  sed -e 's/{{ wlb_researcher_uid_min }}/10000/g' -e 's/{{ wlb_researcher_uid_max }}/59999/g' \
    "$REPO_ROOT/ansible/roles/logging/templates/wlb-shell-audit.sh.j2" >"$SCRIPT"
}

# uruchamia polecenie w bashu z podstawionym UID i załadowanym skryptem
with_uid() {
  local uid=$1
  shift
  bash -c "id() { echo $uid; }; set -o history; . '$SCRIPT'; $*"
}

@test "badacz: PROMPT_COMMAND ustawiony i tylko do odczytu" {
  run with_uid 10001 'echo "$PROMPT_COMMAND"; (PROMPT_COMMAND=x) 2>/dev/null || echo readonly'
  [ "${lines[0]}" = __wlb_log_cmd ]
  [ "${lines[1]}" = readonly ]
}

@test "badacz: polecenie trafia do syslogu z identyfikatorem sesji" {
  with_uid 10001 'history -s "cat /data-mart/kohorta.csv"; __wlb_log_cmd; __wlb_log_cmd'
  calls | grep -Eq '^logger -p local6.info -t wlb-shell -- user=.* session=[0-9]+-[0-9]+ cwd=.* cmd=cat /data-mart/kohorta.csv$'
  # to samo polecenie nie jest logowane dwa razy
  [ "$(calls | wc -l)" -eq 1 ]
}

@test "administrator platformy (UID < 10000) nie jest objęty" {
  run with_uid 1001 'echo "[${PROMPT_COMMAND:-}]"'
  [ "$output" = "[]" ]
}

@test "podwójne załadowanie nie powoduje błędu" {
  run with_uid 10001 ". '$SCRIPT' && echo ok"
  [ "$status" -eq 0 ]
  [ "$output" = ok ]
}
