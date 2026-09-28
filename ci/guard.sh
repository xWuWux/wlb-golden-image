#!/usr/bin/env bash
# Strażnik zasobów: uruchamia polecenie z limitem czasu i pamięci i klasyfikuje wynik.
#
#   ci/guard.sh --name NAZWA [--timeout 30m] [--memory 2G] [--optional] [--ok-codes 0,1] -- POLECENIE...
#
# Po co: proces, który zużyje całą pamięć runnera, zabija też agenta GitHub Actions — job kończy się
# wtedy "The operation was canceled" bez logów i artefaktów (tak było z osv-scanner na dpkg-status).
# Pod strażnikiem OOM zabija tylko to polecenie, a runner dokańcza job i zapisuje logi.
#
# Limit pamięci przez cgroup (systemd-run --scope, w CI przez sudo); bez systemd tylko limit czasu.
# Wynik (dopisywany do build/ci-logs/guard.jsonl i adnotacji GitHub):
#   OK        kod 0
#   FAIL      polecenie zakończyło się błędem (kod != 0) — zwykły błąd testu/narzędzia
#   TIMEOUT   przekroczony limit czasu (kod 124)
#   OOM       zabite przez limit pamięci (kod 137)
# --memory auto: cała pamięć maszyny minus 1 GB — zapas, który zawsze zostaje dla agenta runnera.
# --optional: błąd nie przerywa (kod 0), ale jest raportowany jako ostrzeżenie.
# --ok-codes: kody wyjścia oznaczające sukces (np. osv-scanner: 1 = znaleziono podatności — dla raportu to OK).
set -uo pipefail

NAME="" TIMEOUT=30m MEMORY="" OPTIONAL=0 OK_CODES=0
while [[ $# -gt 0 ]]; do
  case $1 in
    --name) NAME=$2 && shift 2 ;;
    --timeout) TIMEOUT=$2 && shift 2 ;;
    --memory) MEMORY=$2 && shift 2 ;;
    --optional) OPTIONAL=1 && shift ;;
    --ok-codes) OK_CODES=$2 && shift 2 ;;
    --) shift && break ;;
    *) echo "guard: nieznana opcja $1" >&2 && exit 2 ;;
  esac
done
[[ -n $NAME && $# -gt 0 ]] || {
  echo "użycie: ci/guard.sh --name NAZWA [--timeout 30m] [--memory 2G] [--optional] -- POLECENIE..." >&2
  exit 2
}
if [[ $MEMORY == auto ]]; then
  MEMORY="$(($(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 - 1024))M"
fi
LOG_DIR=${GUARD_LOG_DIR:-build/ci-logs}
RUNBOOK=${GUARD_RUNBOOK:-docs/ci-runbook.md}
mkdir -p "$LOG_DIR"

# Limit pamięci: cgroup przez systemd-run (użytkownika albo przez sudo, jak na runnerach GitHub).
# Jednostka ma nazwę, żeby po zakończeniu odczytać jej wynik: OOM rozpoznajemy po Result=oom-kill,
# bo po zabiciu procesu systemd dobija resztę SIGTERM i kod wyjścia bywa 143, a nie 137.
limiter=() ctl=()
unit="guard-$$-$RANDOM"
if [[ -n $MEMORY && ${GUARD_NO_CGROUP:-0} != 1 ]]; then
  if systemd-run --user --scope -q -p MemoryMax=64M true 2>/dev/null; then
    limiter=(systemd-run --user --scope -q --unit="$unit" -p "MemoryMax=$MEMORY" -p MemorySwapMax=0)
    ctl=(systemctl --user)
  elif sudo -n systemd-run --scope -q -p MemoryMax=64M true 2>/dev/null; then
    # sudo czyści PATH/HOME i zawsze usuwa LD_* (Python z setup-python potrzebuje LD_LIBRARY_PATH) —
    # przekazujemy je jawnie i wracamy do bieżącego użytkownika
    ctl=(sudo -n systemctl)
    limiter=(sudo -n --preserve-env systemd-run --scope -q --unit="$unit" -p "MemoryMax=$MEMORY" -p MemorySwapMax=0
      --uid="$(id -u)" --gid="$(id -g)" env "PATH=$PATH" "HOME=$HOME"
      ${LD_LIBRARY_PATH:+"LD_LIBRARY_PATH=$LD_LIBRARY_PATH"})
  else
    echo "guard: brak cgroup (systemd-run) — $NAME bez limitu pamięci, tylko limit czasu" >&2
  fi
fi

start=$(date +%s)
"${limiter[@]}" timeout --kill-after=30s "$TIMEOUT" "$@"
code=$?
elapsed=$(($(date +%s) - start))

case $code in
  124) status=TIMEOUT ;;
  137) status=OOM ;; # SIGKILL: OOM killer cgroup (albo timeout --kill-after)
  *) status=FAIL ;;
esac
[[ ",$OK_CODES," == *",$code,"* ]] && status=OK
[[ $status == OOM && -z ${limiter[*]} ]] && status=FAIL # bez cgroup SIGKILL nie oznacza OOM
if ((${#ctl[@]})); then
  result=$("${ctl[@]}" show -p Result --value "$unit.scope" 2>/dev/null)
  "${ctl[@]}" reset-failed "$unit.scope" 2>/dev/null
  [[ $result == oom-kill ]] && status=OOM
fi

printf '{"name": "%s", "status": "%s", "exit_code": %d, "seconds": %d, "timeout": "%s", "memory": "%s", "optional": %s}\n' \
  "$NAME" "$status" "$code" "$elapsed" "$TIMEOUT" "${MEMORY:-brak}" "$([[ $OPTIONAL == 1 ]] && echo true || echo false)" \
  >>"$LOG_DIR/guard.jsonl"

annotate() { # annotate POZIOM TYTUŁ TREŚĆ — adnotacja GitHub (lokalnie: stderr)
  if [[ -n ${GITHUB_ACTIONS:-} ]]; then echo "::$1 title=$2::$3"; else echo "guard: [$2] $3" >&2; fi
}
level=error
[[ $OPTIONAL == 1 ]] && level=warning
case $status in
  OK) exit 0 ;; # także kody z --ok-codes
  TIMEOUT) annotate "$level" "TIMEOUT: $NAME" "Przekroczony limit czasu $TIMEOUT po ${elapsed}s. Ścieżka: $RUNBOOK#timeout" ;;
  OOM) annotate "$level" "OOM: $NAME" "Przekroczony limit pamięci $MEMORY — proces zabity, runner działa dalej. Ścieżka: $RUNBOOK#oom" ;;
  FAIL) annotate "$level" "FAIL: $NAME" "Kod wyjścia $code po ${elapsed}s. Ścieżka: $RUNBOOK#test" ;;
esac
[[ $OPTIONAL == 1 ]] && exit 0
exit "$code"
