# shellcheck shell=bash
# Wspólne funkcje skryptów wykonywanych w VM testowej jako root.
# Dołączane przed właściwym skryptem: cat remote-common.sh skrypt.sh | ssh ... sudo bash -s

HUB=http://127.0.0.1
PASS=0 FAIL=0 SKIP=0

ok() {
  echo "  PASS  $*"
  PASS=$((PASS + 1))
}
ko() {
  echo "  FAIL  $*"
  FAIL=$((FAIL + 1))
}
skip() {
  echo "  SKIP  $*"
  SKIP=$((SKIP + 1))
}
expect_ok() {
  local d=$1
  shift
  if "$@" >/dev/null 2>&1; then ok "$d"; else ko "$d"; fi
}
expect_fail() {
  local d=$1
  shift
  if "$@" >/dev/null 2>&1; then ko "$d"; else ok "$d"; fi
}
summary() {
  echo
  echo "Wynik: $PASS PASS, $FAIL FAIL, $SKIP SKIP"
  [[ $FAIL -eq 0 ]]
}

# polecenie jako badacz (konto systemowe TLJH: jupyter-<login>)
as() {
  local u=$1
  shift
  (cd / && sudo -u "jupyter-$u" -H "$@")
}

# logowanie formularzem Native Authenticator; wypisuje kod HTTP (302 = sukces)
hub_login() {
  local user=$1 pass=$2 jar=/tmp/wlb-test-$1.jar xsrf
  rm -f "$jar"
  xsrf=$(curl -s -c "$jar" -b "$jar" "$HUB/hub/login" | grep -oP 'name="_xsrf"\s+value="\K[^"]+' | head -1)
  curl -s -o /dev/null -w '%{http_code}' -c "$jar" -b "$jar" \
    --data-urlencode "_xsrf=$xsrf" --data-urlencode "username=$user" --data-urlencode "password=$pass" \
    "$HUB/hub/login"
}

# uruchomienie serwera notebooków zalogowanego użytkownika; czeka na konto systemowe
hub_spawn() {
  local user=$1
  curl -s -o /dev/null -b "/tmp/wlb-test-$user.jar" -c "/tmp/wlb-test-$user.jar" -L "$HUB/hub/spawn"
  for _ in $(seq 1 60); do
    id "jupyter-$user" &>/dev/null && return 0
    sleep 2
  done
  return 1
}
