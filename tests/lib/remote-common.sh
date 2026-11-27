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

# #349 A1: report-only JUnit XML for the acceptance harness.  The harness keeps
# emitting its historical PASS/FAIL/SKIP lines; the XML is an additional
# artifact consumed by the stage-5 parser.  No new dependency is required.
WLB_JUNIT_TMP=${WLB_JUNIT_TMP:-/tmp/wlb-acceptance-junit.xml}
WLB_JUNIT_OUT=${WLB_JUNIT_OUT:-/tmp/acceptance.xml}
JUNIT_SUITE_START=${JUNIT_SUITE_START:-${SECONDS:-0}}
JUNIT_START=${JUNIT_START:-${SECONDS:-0}}
declare -A JUNIT_SEEN=()
: >"$WLB_JUNIT_TMP" 2>/dev/null || true

_xml_escape() {
  local s=${1:-}
  # W replacement Bash interpretuje & jako dopasowanie; \& daje literalny znak.
  s=${s//&/\&amp;}
  s=${s//</\&lt;}
  s=${s//>/\&gt;}
  s=${s//\"/\&quot;}
  printf '%s' "$s"
}

# _junit_record STATUS OPIS [POWÓD] — dopisuje <testcase> do strumienia.
# Czas jest liczony z SECONDS; to wystarcza do raportu, nie do benchmarku.
_junit_record() {
  local status=${1:-} desc=${2:-unnamed} reason=${3:-${2:-unnamed}}
  local now=${SECONDS:-0}
  local elapsed=$((now - JUNIT_START))
  ((elapsed < 0)) && elapsed=0
  JUNIT_START=$now
  desc=${desc//$'\n'/ }
  desc=${desc//$'\t'/ }
  desc=${desc//$'\r'/ }
  reason=${reason//$'\n'/ }
  reason=${reason//$'\t'/ }
  reason=${reason//$'\r'/ }
  local prev=${JUNIT_SEEN["$desc"]:-0}
  local count=$((prev + 1))
  JUNIT_SEEN["$desc"]=$count
  local name=$desc
  ((count > 1)) && name="$desc #$count"
  local xname xreason
  xname=$(_xml_escape "$name")
  xreason=$(_xml_escape "$reason")
  case $status in
    PASS)
      printf '  <testcase name="%s" time="%d.000"/>\n' "$xname" "$elapsed" >>"$WLB_JUNIT_TMP" 2>/dev/null || true
      ;;
    FAIL)
      printf '  <testcase name="%s" time="%d.000"><failure message="%s"/></testcase>\n' \
        "$xname" "$elapsed" "$xreason" >>"$WLB_JUNIT_TMP" 2>/dev/null || true
      ;;
    SKIP)
      printf '  <testcase name="%s" time="%d.000"><skipped message="%s"/></testcase>\n' \
        "$xname" "$elapsed" "$xreason" >>"$WLB_JUNIT_TMP" 2>/dev/null || true
      ;;
  esac
}

# junit_finalize — owiń zebrane testcase w <testsuite> i zapisz na VM.
junit_finalize() {
  local tests failures skipped elapsed
  [[ -f $WLB_JUNIT_TMP ]] || : >"$WLB_JUNIT_TMP"
  tests=$(grep -c '<testcase ' "$WLB_JUNIT_TMP" 2>/dev/null || true)
  failures=$(grep -c '<failure ' "$WLB_JUNIT_TMP" 2>/dev/null || true)
  skipped=$(grep -c '<skipped ' "$WLB_JUNIT_TMP" 2>/dev/null || true)
  elapsed=$((${SECONDS:-0} - JUNIT_SUITE_START))
  ((elapsed < 0)) && elapsed=0
  {
    printf '<?xml version="1.0" encoding="UTF-8"?>\n'
    printf '<testsuite name="acceptance-stage5" tests="%s" failures="%s" skipped="%s" time="%d.000">\n' \
      "${tests:-0}" "${failures:-0}" "${skipped:-0}" "$elapsed"
    cat "$WLB_JUNIT_TMP"
    printf '</testsuite>\n'
  } >"$WLB_JUNIT_OUT"
}

# median LICZBY... — mediana liczb całkowitych; przy parzystej liczbie próbek średnia
# dwóch środkowych wartości (np. 10 20 30 40 -> 25). Dolna środkowa nie jest medianą
# i przy parzystym n zaniża latencje (#10).
median() {
  (($# > 0)) || return 1
  local sorted n
  mapfile -t sorted < <(printf '%s\n' "$@" | sort -n)
  n=${#sorted[@]}
  if ((n % 2)); then
    echo "${sorted[$((n / 2))]}"
  else
    awk -v a="${sorted[$((n / 2 - 1))]}" -v b="${sorted[$((n / 2))]}" \
      'BEGIN { printf "%.3f\n", (a + b) / 2 }'
  fi
}

ok() {
  echo "  PASS  $*"
  PASS=$((PASS + 1))
  _junit_record PASS "$*"
}
ko() {
  echo "  FAIL  $*"
  FAIL=$((FAIL + 1))
  _junit_record FAIL "$*"
}
skip() {
  echo "  SKIP  $*"
  SKIP=$((SKIP + 1))
  _junit_record SKIP "$*"
}
expect_ok() {
  local d=$1
  shift
  JUNIT_START=${SECONDS:-0}
  if "$@" >/dev/null 2>&1; then ok "$d"; else ko "$d"; fi
}
expect_fail() {
  local d=$1
  shift
  JUNIT_START=${SECONDS:-0}
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

# uruchomienie serwera notebooków zalogowanego użytkownika; czeka na konto systemowe i aktywną jednostkę
hub_spawn() {
  local user=$1
  curl -s -o /dev/null -b "/tmp/wlb-test-$user.jar" -c "/tmp/wlb-test-$user.jar" -L "$HUB/hub/spawn"
  for _ in $(seq 1 60); do
    id "jupyter-$user" &>/dev/null && systemctl is-active --quiet "jupyter-$user" && return 0
    sleep 2
  done
  return 1
}

# zatrzymanie serwera notebooków zalogowanego użytkownika; czeka na wyłączenie jednostki
hub_stop() {
  local user=$1 jar=/tmp/wlb-test-$1.jar xsrf code
  if [ -f "$jar" ]; then
    xsrf=$(grep -oP '\t_xsrf\t\K\S+' "$jar" | tail -1)
    [ -n "$xsrf" ] || xsrf=$(curl -s -b "$jar" -c "$jar" "$HUB/hub/home" | grep -oP 'name="_xsrf"\s+value="\K[^"]+' | head -1)
    code=$(curl -s -o /dev/null -w '%{http_code}' -X DELETE -b "$jar" -c "$jar" \
      -H "X-XSRFToken: $xsrf" -H "Referer: $HUB/hub/home" \
      "$HUB/hub/api/users/$user/server?_xsrf=$xsrf")
  else
    code=000
  fi
  if [[ ! "$code" =~ ^(200|202|204)$ ]]; then
    local tok
    tok=$(/opt/tljh/hub/bin/python -c '
import sys
from jupyterhub.orm import User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
db = sessionmaker(bind=create_engine("sqlite:////workspace/.wlb-hub/jupyterhub.sqlite"))()
u = db.query(User).filter_by(name=sys.argv[1]).first()
if u:
    t = u.new_api_token(note="hub_stop_token")
    db.commit()
    sys.stdout.write(t)
' "$user" 2>/dev/null || true)
    if [ -n "$tok" ]; then
      curl -s -o /dev/null -X DELETE -H "Authorization: token $tok" "$HUB/hub/api/users/$user/server"
      /opt/tljh/hub/bin/python -c '
import sys
from jupyterhub.orm import APIToken
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
db = sessionmaker(bind=create_engine("sqlite:////workspace/.wlb-hub/jupyterhub.sqlite"))()
for t in db.query(APIToken).filter_by(note="hub_stop_token").all():
    db.delete(t)
db.commit()
' 2>/dev/null || true
    fi
  fi
  for _ in $(seq 1 30); do
    systemctl is-active --quiet "jupyter-$user" || return 0
    sleep 1
  done
  return 1
}
