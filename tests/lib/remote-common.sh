# shellcheck shell=bash
# Wspólne funkcje skryptów wykonywanych w VM testowej jako root.
# Dołączane przed właściwym skryptem: cat remote-common.sh skrypt.sh | ssh ... sudo bash -s

# Transport huba zależy od HUB_TLS w lab.env (#18, firstboot: domyślnie 1). HUB_TLS=0 → HTTP (dev);
# inaczej HTTPS po nazwie z weryfikacją testowej CA (cert ma SAN localhost/127.0.0.1) — bez -k.
# CURL_CA_BUNDLE sprawia, że KAŻDY curl do $HUB weryfikuje CA; hub-ca.pem wstrzyknięte przez cloud-init.
if grep -qE '^[[:space:]]*HUB_TLS=0[[:space:]]*$' /etc/wlb/lab.env 2>/dev/null; then
  HUB=http://127.0.0.1
else
  HUB=https://localhost
  export CURL_CA_BUNDLE=/etc/wlb/hub-ca.pem
fi
PASS=0 FAIL=0 SKIP=0

# median LICZBY... — wypisuje medianę liczb całkowitych (dolna przy parzystej liczbie próbek).
# Używane w pomiarach wydajności (#10): wartość kanoniczna metryki to mediana powtórzeń.
median() {
  (($# > 0)) || return 1
  local sorted
  mapfile -t sorted < <(printf '%s\n' "$@" | sort -n)
  echo "${sorted[$(((${#sorted[@]} - 1) / 2))]}"
}

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

# in_unit LOGIN POLECENIE... — jako badacz, ale w cgroup jego serwera notebooków (limity jednostki
# SystemdSpawnera: pamięć, CPU, TasksMax) i z jego oom_score_adj (jak kernele uruchomione z JupyterLab).
# as() działa poza jednostką, więc limitów nie sprawdza; bez oom_score_adj proces testu dziedziczyłby
# wartość sesji SSH i OOM killer wybrałby serwer notebooków zamiast procesu, który przekroczył limit.
in_unit() {
  local u=$1 cg adj
  shift
  cg=$(systemctl show -p ControlGroup --value "jupyter-$u")
  [[ -n $cg ]] || return 1
  adj=$(cat "/proc/$(systemctl show -p MainPID --value "jupyter-$u")/oom_score_adj")
  (cd / && bash -c 'echo $$ >"/sys/fs/cgroup$0/cgroup.procs" && echo "$1" >/proc/self/oom_score_adj &&
    exec sudo -u "jupyter-$2" -H "${@:3}"' "$cg" "$adj" "$u" "$@")
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
