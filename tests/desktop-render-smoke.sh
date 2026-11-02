#!/usr/bin/env bash
# desktop-render-smoke.sh — render-smoke pulpitu (#205, etap 1 testów wizualnych; pulpit #106).
#
# Co robi: wstaje prywatny serwer X (TigerVNC) z sesją XFCE, czeka na gotowość X/WM/panelu/D-Bus,
# otwiera kontrolowane okno xmessage, sprawdza jego geometrię i piksele tekstu, a potem przesuwa
# i skaluje okno oraz sprawdza, że obraz regionu się zmienił. Liczba kolorów jest tylko diagnostyką.
#
# Test jest RUNTIME (nie sprawdza obecności pakietów), więc pozostaje samodzielny i NIE jest
# wpięty w bramkującą akceptację (stage 5) — patrz #205 i dokumentacja runbooka.
#
# Wymaga pakietów roli desktop (TigerVNC, XFCE, dbus-x11, x11-utils, wmctrl, scrot) oraz Pillow
# z env badaczy. Uruchamiać JAKO badacz (nie root — XFCE pod rootem jest niewspierany):
#   sudo -iu <badacz> /opt/wlb/tests/desktop-render-smoke.sh
#
# Kody wyjścia: 0 = render OK; 1 = błąd środowiska/startu/gotowości; 2 = błąd renderu
# (brak okna, brak tekstu, brak reakcji na interakcję); 130/143 = przerwanie sygnałem.
#
# Parametry (env):
#   WLB_SMOKE_DISPLAY(:auto)        display :N; puste = pierwszy wolny z zakresu :99..:199
#   WLB_SMOKE_GEOMETRY(1280x800)    rozdzielczość ekranu
#   WLB_SMOKE_TIMEOUT(90)           deadline całego przebiegu w sekundach (1..3600)
#   WLB_SMOKE_MIN_COLORS(64)        próg tylko diagnostyczny; NIE decyduje o PASS
#   WLB_SMOKE_ARTIFACT_DIR          katalog artefaktów (domyślnie ~/.local/state/wlb/...)
#   WLB_SMOKE_PYTHON                Python z Pillow (domyślnie /opt/tljh/user/bin/python)
#
# Bezpieczeństwo: RFB tylko na prywatnym gnieździe Unix w katalogu 0700, bez TCP
# (-rfbport -1), bez nieuwierzytelnionego nasłuchu sieciowego. Cleanup zabija wyłącznie
# własną grupę procesów (token w środowisku), nigdy `vncserver -kill` ani cudzy display.
set -euo pipefail
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HELPER="$SCRIPT_DIR/desktop_render_smoke.py"

DISPLAY_NUM=${WLB_SMOKE_DISPLAY:-}
GEOMETRY=${WLB_SMOKE_GEOMETRY:-1280x800}
TIMEOUT=${WLB_SMOKE_TIMEOUT:-90}
MIN_COLORS=${WLB_SMOKE_MIN_COLORS:-64}
PY=${WLB_SMOKE_PYTHON:-/opt/tljh/user/bin/python}
ARTIFACT_DIR=${WLB_SMOKE_ARTIFACT_DIR:-}
# Katalogi X11 można nadpisać wyłącznie w testach jednostkowych (izolacja od /tmp).
X11_LOCK_DIR=${WLB_SMOKE_X11_LOCK_DIR:-/tmp}
X11_SOCKET_DIR=${WLB_SMOKE_X11_SOCKET_DIR:-/tmp/.X11-unix}

BG_COLOR="#ff00ff"
FG_COLOR="#000000"
WINDOW_W=560
WINDOW_H=200
WINDOW_X=100
WINDOW_Y=80

ARG_ERROR=""
if (($#)); then
  case $1 in
    -h | --help)
      sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) ARG_ERROR="nieznany argument: $1" ;;
  esac
fi

# --- Infrastruktura wyniku i artefaktów -----------------------------------------------------
if [[ -z $ARTIFACT_DIR ]]; then
  ARTIFACT_DIR="${XDG_STATE_HOME:-${HOME:-/tmp}/.local/state}/wlb/desktop-render-smoke/$(date -u +%Y%m%dT%H%M%SZ)-$$"
fi
if [[ $ARTIFACT_DIR != /* || $ARTIFACT_DIR == *$'\n'* ]]; then
  printf 'render-smoke: BŁĄD — WLB_SMOKE_ARTIFACT_DIR musi być ścieżką bezwzględną bez nowej linii\n' >&2
  exit 1
fi
if [[ -L $ARTIFACT_DIR ]]; then
  printf 'render-smoke: BŁĄD — katalog artefaktów nie może być dowiązaniem: %s\n' "$ARTIFACT_DIR" >&2
  exit 1
fi
if ! mkdir -p -- "$ARTIFACT_DIR"; then
  printf 'render-smoke: BŁĄD — nie można utworzyć katalogu artefaktów: %s\n' "$ARTIFACT_DIR" >&2
  exit 1
fi
chmod 0700 "$ARTIFACT_DIR"

RUN_LOG="$ARTIFACT_DIR/run.log"
RESULT_FILE="$ARTIFACT_DIR/result.json"
PIDFILE="$ARTIFACT_DIR/vnc.pid"
XLOG="$ARTIFACT_DIR/vnc.log"
XSTART="$ARTIFACT_DIR/xstartup.sh"
XAUTHORITY="$ARTIFACT_DIR/Xauthority"
VNC_RUN_DIR=""
VNC_SOCKET=""
SHOT1=""
SHOT2=""
START_EPOCH=$(date +%s)
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RUN_TOKEN="wlb-$$-${RANDOM}-${RANDOM}"
export WLB_SMOKE_RUN_TOKEN="$RUN_TOKEN"
export XAUTHORITY
: >"$XAUTHORITY"
chmod 0600 "$XAUTHORITY"
: >"$RUN_LOG"

say() {
  printf 'render-smoke: %s\n' "$*"
  printf 'render-smoke: %s\n' "$*" >>"$RUN_LOG"
}

STATUS=fail
REASON=unexpected_exit
MESSAGE=""
EXIT_CODE=1
RESULT_WRITTEN=0
CLEANED=0
DEADLINE=$START_EPOCH
SESSION_PID=""
SESSION_STARTTIME=""
XMESSAGE_PID=""
XMESSAGE_STARTTIME=""
WM_WINDOW=""
WID=""
WIN_TITLE=""
WIN_GEOM_BEFORE=""
WIN_GEOM_AFTER=""
CURRENT_GEOM=""
CUR_X=0
CUR_Y=0
CUR_W=0
CUR_H=0
INIT_X=0
INIT_Y=0
INIT_W=0
INIT_H=0
SCREEN_COLORS=""
WINDOW_COLORS=""
BG_PIXELS=""
FG_PIXELS=""
BG_FRACTION=""
CHK_X=0
CHK_VNC=0
CHK_WM=0
CHK_SESSION=0
CHK_PANEL=0
CHK_DBUS=0
CHK_WINDOW=0
CHK_IMAGE=0
CHK_INTERACTION=0

# Bezpieczne wartości JSON: niepoprawny parametr nie może wywrócić zapisu result.json.
json_uint() {
  if [[ ${1:-} =~ ^[0-9]+$ ]]; then
    printf '%s' "$((10#$1))"
  else
    printf 'null'
  fi
}

json_number() {
  if [[ ${1:-} =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
    printf '%s' "$1"
  else
    printf 'null'
  fi
}

write_result() {
  ((RESULT_WRITTEN == 0)) || return 0
  local duration tmp
  duration=$(($(date +%s) - START_EPOCH))
  tmp="$RESULT_FILE.tmp.$$"
  if jq -n \
    --arg schema "wlb.desktop-render-smoke/v1" \
    --arg status "$STATUS" \
    --arg reason "$REASON" \
    --arg message "$MESSAGE" \
    --arg started_at "$STARTED_AT" \
    --arg finished_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson duration_s "$duration" \
    --argjson exit_code "$EXIT_CODE" \
    --arg display "$DISPLAY_NUM" \
    --arg geometry "$GEOMETRY" \
    --argjson timeout_s "$(json_uint "$TIMEOUT")" \
    --argjson min_colors "$(json_uint "$MIN_COLORS")" \
    --arg artifact_dir "$ARTIFACT_DIR" \
    --arg shot1 "$SHOT1" \
    --arg shot2 "$SHOT2" \
    --arg window_id "$WID" \
    --arg window_title "$WIN_TITLE" \
    --arg geom_before "$WIN_GEOM_BEFORE" \
    --arg geom_after "$WIN_GEOM_AFTER" \
    --argjson screen_colors "$(json_uint "$SCREEN_COLORS")" \
    --argjson window_colors "$(json_uint "$WINDOW_COLORS")" \
    --argjson bg_pixels "$(json_uint "$BG_PIXELS")" \
    --argjson fg_pixels "$(json_uint "$FG_PIXELS")" \
    --argjson bg_fraction "$(json_number "$BG_FRACTION")" \
    --argjson session_pid "$(json_uint "$SESSION_PID")" \
    --arg chk_x "$CHK_X" \
    --arg chk_vnc "$CHK_VNC" \
    --arg chk_wm "$CHK_WM" \
    --arg chk_session "$CHK_SESSION" \
    --arg chk_panel "$CHK_PANEL" \
    --arg chk_dbus "$CHK_DBUS" \
    --arg chk_window "$CHK_WINDOW" \
    --arg chk_image "$CHK_IMAGE" \
    --arg chk_interaction "$CHK_INTERACTION" \
    '{
      schema: $schema,
      status: $status,
      reason: $reason,
      message: (if $message == "" then null else $message end),
      started_at: $started_at,
      finished_at: $finished_at,
      duration_s: $duration_s,
      exit_code: $exit_code,
      display: (if $display == "" then null else $display end),
      geometry: $geometry,
      timeout_s: $timeout_s,
      min_colors: $min_colors,
      artifact_dir: $artifact_dir,
      session_pid: $session_pid,
      screenshots: {
        initial: (if $shot1 == "" then null else $shot1 end),
        interaction: (if $shot2 == "" then null else $shot2 end)
      },
      window: {
        id: (if $window_id == "" then null else $window_id end),
        title: (if $window_title == "" then null else $window_title end),
        geometry_before: (if $geom_before == "" then null else $geom_before end),
        geometry_after: (if $geom_after == "" then null else $geom_after end)
      },
      colors: {
        screen: $screen_colors,
        window: $window_colors,
        background_pixels: $bg_pixels,
        foreground_pixels: $fg_pixels,
        background_fraction: $bg_fraction
      },
      checks: {
        x: ($chk_x == "1"),
        vnc_socket: ($chk_vnc == "1"),
        wm: ($chk_wm == "1"),
        session: ($chk_session == "1"),
        panel: ($chk_panel == "1"),
        dbus: ($chk_dbus == "1"),
        window: ($chk_window == "1"),
        image: ($chk_image == "1"),
        interaction: ($chk_interaction == "1")
      }
    }' >"$tmp"; then
    chmod 0600 "$tmp"
    mv -f "$tmp" "$RESULT_FILE"
    RESULT_WRITTEN=1
    printf 'render-smoke: wynik: %s\n' "$RESULT_FILE"
  else
    rm -f "$tmp"
    printf 'render-smoke: BŁĄD — nie można zapisać %s\n' "$RESULT_FILE" >&2
  fi
}

fail() {
  local reason=$1 message=${2:-} code=${3:-1}
  REASON=$reason
  MESSAGE=$message
  EXIT_CODE=$code
  STATUS=fail
  say "FAIL — ${reason}${message:+: $message}"
  write_result
  exit "$code"
}

# Pola /proc/<pid>/stat po ostatnim ")" — odporne na spacje w nazwie procesu.
process_state() {
  sed -n 's/^.*) //p' "/proc/$1/stat" 2>/dev/null | awk '{print $1}'
}

process_starttime() {
  sed -n 's/^.*) //p' "/proc/$1/stat" 2>/dev/null | awk '{print $20}'
}

# Żywy proces o podanym PID i czasie startu; zombie (Z) nie jest żywy, choć /proc jeszcze istnieje.
process_matches() {
  local pid=$1 start=$2 state
  state=$(process_state "$pid")
  [[ -n $state && $state != Z && $(process_starttime "$pid") == "$start" ]]
}

session_alive() {
  [[ -n ${SESSION_PID:-} && -n ${SESSION_STARTTIME:-} ]] || return 1
  process_matches "$SESSION_PID" "$SESSION_STARTTIME"
}

group_owned() {
  [[ -n ${SESSION_PID:-} && -n ${RUN_TOKEN:-} ]] || return 1
  local pid
  while read -r pid; do
    [[ -n $pid && -r /proc/$pid/environ ]] || continue
    if tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null | grep -qxF "WLB_SMOKE_RUN_TOKEN=$RUN_TOKEN"; then
      return 0
    fi
  done < <(ps -eo pid=,pgid= 2>/dev/null | awk -v pg="$SESSION_PID" '$2 == pg {print $1}')
  return 1
}

stop_owned_group() {
  [[ -n ${SESSION_PID:-} ]] || return 0
  if group_owned; then
    kill -TERM -- "-$SESSION_PID" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 -- "-$SESSION_PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL -- "-$SESSION_PID" 2>/dev/null || true
  fi
  SESSION_PID=""
  SESSION_STARTTIME=""
}

# shellcheck disable=SC2329  # wywoływane przez trap
cleanup() {
  ((CLEANED == 0)) || return 0
  CLEANED=1
  if process_matches "${XMESSAGE_PID:-}" "${XMESSAGE_STARTTIME:-}"; then
    kill -TERM "$XMESSAGE_PID" 2>/dev/null || true
  fi
  XMESSAGE_PID=""
  XMESSAGE_STARTTIME=""
  stop_owned_group
  [[ -z ${VNC_RUN_DIR:-} ]] || rm -rf -- "$VNC_RUN_DIR"
}

# shellcheck disable=SC2329  # wywoływane przez trap
on_signal() {
  local name=$1 code=$2
  REASON="signal_${name,,}"
  MESSAGE="przerwano sygnałem $name"
  EXIT_CODE=$code
  STATUS=fail
  say "FAIL — $MESSAGE"
  write_result
  exit "$code"
}

# shellcheck disable=SC2329  # wywoływane przez trap
on_exit() {
  local rc=$?
  if ((RESULT_WRITTEN == 0)); then
    EXIT_CODE=$rc
    if ((rc == 0)); then
      STATUS=pass
      REASON=ok
    else
      STATUS=fail
      [[ $REASON != ok ]] || REASON=unexpected_exit
    fi
    write_result
  fi
  cleanup
}

trap on_exit EXIT
trap 'on_signal TERM 143' TERM
trap 'on_signal INT 130' INT
trap 'on_signal HUP 129' HUP

# --- Walidacja parametrów i zależności ------------------------------------------------------
[[ -z $ARG_ERROR ]] || fail invalid_arguments "$ARG_ERROR" 1
[[ $(id -u) -ne 0 ]] || fail not_researcher "uruchom jako badacz, nie root (XFCE pod rootem jest niewspierany)" 1

if [[ -n $DISPLAY_NUM ]]; then
  if [[ ! $DISPLAY_NUM =~ ^:[0-9]{1,3}$ ]]; then
    fail invalid_display "WLB_SMOKE_DISPLAY musi mieć postać :N (1..999), jest: $DISPLAY_NUM" 1
  fi
  display_n=$((10#${DISPLAY_NUM#:}))
  ((display_n >= 1 && display_n <= 999)) || fail invalid_display "numer display spoza zakresu 1..999: $DISPLAY_NUM" 1
fi

if [[ $GEOMETRY =~ ^([0-9]+)x([0-9]+)$ ]]; then
  geometry_w=$((10#${BASH_REMATCH[1]}))
  geometry_h=$((10#${BASH_REMATCH[2]}))
else
  fail invalid_geometry "WLB_SMOKE_GEOMETRY musi mieć postać WxH, jest: $GEOMETRY" 1
fi
((geometry_w >= 320 && geometry_w <= 7680 && geometry_h >= 240 && geometry_h <= 4320)) ||
  fail invalid_geometry "WLB_SMOKE_GEOMETRY poza zakresem 320..7680 x 240..4320: $GEOMETRY" 1
((WINDOW_W < geometry_w && WINDOW_H < geometry_h && WINDOW_X + WINDOW_W < geometry_w && WINDOW_Y + WINDOW_H < geometry_h)) ||
  fail invalid_geometry "okno kontrolne nie mieści się na ekranie $GEOMETRY" 1

[[ $TIMEOUT =~ ^[0-9]+$ ]] || fail invalid_timeout "WLB_SMOKE_TIMEOUT musi być liczbą całkowitą, jest: $TIMEOUT" 1
TIMEOUT=$((10#$TIMEOUT))
((TIMEOUT >= 1 && TIMEOUT <= 3600)) || fail invalid_timeout "WLB_SMOKE_TIMEOUT spoza zakresu 1..3600: $TIMEOUT" 1
DEADLINE=$((START_EPOCH + TIMEOUT))

[[ $MIN_COLORS =~ ^[0-9]+$ ]] || fail invalid_min_colors "WLB_SMOKE_MIN_COLORS musi być liczbą całkowitą, jest: $MIN_COLORS" 1
MIN_COLORS=$((10#$MIN_COLORS))
((MIN_COLORS >= 0 && MIN_COLORS <= 1000000)) || fail invalid_min_colors "WLB_SMOKE_MIN_COLORS spoza zakresu 0..1000000: $MIN_COLORS" 1

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail missing_dependency "brak polecenia: $1 (rola desktop)" 1
}
VNCSERVER=$(command -v tigervncserver || command -v vncserver || true)
[[ -n $VNCSERVER ]] || fail missing_dependency "brak tigervncserver/vncserver (rola desktop)" 1
for cmd in startxfce4 dbus-launch scrot xdpyinfo xprop xwininfo wmctrl xmessage setsid timeout pgrep ps jq xauth; do
  require_cmd "$cmd"
done
PY_ORIG=$PY
PY=$(command -v "$PY" || true)
[[ -n $PY && -x $PY ]] || fail missing_pillow "brak Pythona env badaczy: $PY_ORIG (oczekiwano Pillow)" 1
timeout 15 "$PY" -c 'import PIL' >/dev/null 2>&1 ||
  fail missing_pillow "Python $PY nie ma Pillow — regresja env badaczy" 1
[[ -f $HELPER ]] || fail missing_helper "brak analizatora obrazu: $HELPER" 1

# --- Wybór displayu i start prywatnego serwera X --------------------------------------------
display_busy() {
  local d=${1#:}
  [[ -e "$X11_LOCK_DIR/.X${d}-lock" || -e "$X11_SOCKET_DIR/X${d}" ]]
}

pick_free_display() {
  local start=${1:-99} n
  for ((n = start; n <= 199; n++)); do
    display_busy ":${n}" || {
      printf ':%s\n' "$n"
      return 0
    }
  done
  return 1
}

cat >"$XSTART" <<'EOF'
#!/bin/sh
exec dbus-launch --exit-with-session startxfce4
EOF
chmod 0700 "$XSTART"

# Gniazdo Unix ma limit ~108 znaków, a katalog artefaktów bywa głęboki — trzymamy je krótko w /tmp.
VNC_RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/wlb-smoke.XXXXXX") ||
  fail runtime_dir "nie można utworzyć prywatnego katalogu na gniazdo VNC" 1
chmod 0700 "$VNC_RUN_DIR"
VNC_SOCKET="$VNC_RUN_DIR/vnc.sock"

start_vnc() {
  local d=$1
  DISPLAY_NUM=$d
  export DISPLAY="$DISPLAY_NUM"
  : >"$XLOG"
  : >"$PIDFILE"
  rm -f "$VNC_SOCKET"
  say "start TigerVNC na ${DISPLAY_NUM} (RFB tylko Unix socket, bez TCP)"
  # $$ i "$@" mają się rozwinąć w wewnętrznym bashu, nie tutaj.
  # shellcheck disable=SC2016
  setsid bash -c 'printf "%s\n" "$$" >"$1"; shift; exec "$@"' _ "$PIDFILE" \
    "$VNCSERVER" "$DISPLAY_NUM" -geometry "$GEOMETRY" -depth 24 \
    -SecurityTypes None -localhost yes \
    -rfbunixpath "$VNC_SOCKET" -rfbunixmode 0600 -rfbport -1 \
    -xstartup "$XSTART" -fg >>"$XLOG" 2>&1 &
  for _ in $(seq 1 50); do
    [[ -s $PIDFILE ]] && break
    (($(date +%s) < DEADLINE)) || return 1
    sleep 0.1
  done
  if [[ ! -s $PIDFILE ]]; then
    return 1
  fi
  SESSION_PID=$(head -n 1 "$PIDFILE")
  if [[ ! $SESSION_PID =~ ^[0-9]+$ ]]; then
    SESSION_PID=""
    return 1
  fi
  SESSION_STARTTIME=$(process_starttime "$SESSION_PID")
  if [[ -z $SESSION_STARTTIME ]]; then
    # Proces zdążył zniknąć przed odczytem /proc — komunikat wrappera mówi, czy display był zajęty.
    SESSION_PID=""
    if grep -qiE 'already running|is taken because of' "$XLOG" 2>/dev/null; then
      return 2
    fi
    return 1
  fi

  # Czekamy na WŁASNE gniazdo VNC i na X. Samo xdpyinfo nie wystarcza: na zajętym
  # displayu odpowiada cudzy serwer X, a nasz wrapper kończy się komunikatem o błędzie.
  for _ in $(seq 1 100); do
    if [[ -S $VNC_SOCKET ]] && timeout 5 xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1; then
      return 0
    fi
    if ! session_alive; then
      if grep -qiE 'already running|is taken because of' "$XLOG" 2>/dev/null; then
        return 2
      fi
      return 1
    fi
    (($(date +%s) < DEADLINE)) || return 1
    sleep 0.1
  done
  return 1
}

if [[ -n $DISPLAY_NUM ]]; then
  if display_busy "$DISPLAY_NUM"; then
    fail display_busy "display $DISPLAY_NUM jest zajęty; wybierz inny WLB_SMOKE_DISPLAY" 1
  fi
  if start_vnc "$DISPLAY_NUM"; then
    :
  else
    rc=$?
    if ((rc == 2)); then
      fail display_busy "display $DISPLAY_NUM jest zajęty; wybierz inny WLB_SMOKE_DISPLAY" 1
    fi
    fail vnc_start_failed "serwer VNC nie wstał: $(tail -n 5 "$XLOG" | tr '\n' ' ')" 1
  fi
else
  started=0
  next_display=99
  for _ in $(seq 1 20); do
    (($(date +%s) < DEADLINE)) || fail timeout_start "przekroczono WLB_SMOKE_TIMEOUT=${TIMEOUT}s przed startem sesji" 1
    candidate=$(pick_free_display "$next_display") || fail no_free_display "brak wolnego displayu w zakresie :99..:199" 1
    next_display=$((${candidate#:} + 1))
    if start_vnc "$candidate"; then
      started=1
      break
    else
      rc=$?
      stop_owned_group
      if ((rc == 2)); then
        say "display $candidate zajęty — próbuję następny"
        continue
      fi
      fail vnc_start_failed "serwer VNC nie wstał: $(tail -n 5 "$XLOG" | tr '\n' ' ')" 1
    fi
  done
  ((started == 1)) || fail no_free_display "nie udało się uruchomić serwera VNC na wolnym displayu" 1
fi

export DISPLAY="$DISPLAY_NUM"

# --- Gotowość: X, VNC socket, WM, sesja, panel, D-Bus — deadline zamiast sleep --------------
wm_window() {
  local out id
  out=$(timeout 5 xprop -display "$DISPLAY_NUM" -root _NET_SUPPORTING_WM_CHECK 2>/dev/null) || return 1
  id=$(awk -F'# ' '/window id #/ {print $2; exit}' <<<"$out")
  [[ $id =~ ^0x[0-9a-fA-F]+$ && $id != 0x0 ]] || return 1
  timeout 5 xprop -display "$DISPLAY_NUM" -id "$id" _NET_WM_NAME 2>/dev/null | grep -q '"' || return 1
  WM_WINDOW=$id
}

session_has() {
  local name=$1 pid environ
  # Najpierw grupa procesów własnej sesji (xfce4-session/panel dziedziczą PGID wrappera).
  if pgrep -g "$SESSION_PID" -x "$name" >/dev/null 2>&1; then
    return 0
  fi
  # D-Bus z dbus-launch może daemonizować się poza PGID — wtedy szukamy po środowisku sesji.
  while read -r pid; do
    [[ -n $pid && -r /proc/$pid/environ ]] || continue
    environ=$(tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null || true)
    if grep -qxF "WLB_SMOKE_RUN_TOKEN=$RUN_TOKEN" <<<"$environ"; then
      return 0
    fi
    # Fallback wyłącznie dla dbus-daemon, który nie zawsze dziedziczy token.
    if [[ $name == dbus-daemon ]] && grep -qxF "DISPLAY=$DISPLAY_NUM" <<<"$environ"; then
      return 0
    fi
  done < <(pgrep -u "$(id -u)" -x "$name" 2>/dev/null || true)
  return 1
}

check_readiness() {
  MISSING=()
  CHK_X=0 CHK_VNC=0 CHK_WM=0 CHK_SESSION=0 CHK_PANEL=0 CHK_DBUS=0
  if timeout 5 xdpyinfo -display "$DISPLAY_NUM" >/dev/null 2>&1; then CHK_X=1; else MISSING+=(X); fi
  if [[ -S $VNC_SOCKET ]]; then CHK_VNC=1; else MISSING+=(vnc-socket); fi
  if ((CHK_X == 1)) && wm_window; then CHK_WM=1; else MISSING+=(WM); fi
  if session_has xfce4-session; then CHK_SESSION=1; else MISSING+=(sesja); fi
  if session_has xfce4-panel; then CHK_PANEL=1; else MISSING+=(panel); fi
  if session_has dbus-daemon; then CHK_DBUS=1; else MISSING+=(D-Bus); fi
  ((${#MISSING[@]} == 0))
}

while :; do
  if ! session_alive; then
    fail vnc_start_failed "proces sesji zakończył się przed osiągnięciem gotowości: $(tail -n 5 "$XLOG" | tr '\n' ' ')" 1
  fi
  if check_readiness; then
    break
  fi
  if (($(date +%s) >= DEADLINE)); then
    if ((CHK_X == 1)); then
      timeout 10 scrot -o "$ARTIFACT_DIR/failure-readiness.png" >/dev/null 2>&1 || true
      [[ -s $ARTIFACT_DIR/failure-readiness.png ]] && SHOT1="$ARTIFACT_DIR/failure-readiness.png"
    fi
    fail readiness_timeout "brak: ${MISSING[*]} (limit ${TIMEOUT}s)" 1
  fi
  sleep 0.25
done
say "gotowość OK: X ${DISPLAY_NUM}, WM ${WM_WINDOW}, sesja/panel/D-Bus żyją"

# --- Kontrolowane okno xmessage -------------------------------------------------------------
MARKER="WLB-SMOKE-${RUN_TOKEN:0:8}-$$"
DISPLAY="$DISPLAY_NUM" XAUTHORITY="$XAUTHORITY" \
  xmessage -name wlb-render-smoke -title "$MARKER" -bg "$BG_COLOR" -fg "$FG_COLOR" \
  -buttons OK:0 -default OK -geometry "${WINDOW_W}x${WINDOW_H}+${WINDOW_X}+${WINDOW_Y}" \
  "$MARKER" >>"$RUN_LOG" 2>&1 &
XMESSAGE_PID=$!
for _ in $(seq 1 20); do
  XMESSAGE_STARTTIME=$(process_starttime "$XMESSAGE_PID")
  [[ -n $XMESSAGE_STARTTIME ]] && break
  sleep 0.05
done

while :; do
  WID=$(timeout 5 xwininfo -display "$DISPLAY_NUM" -root -tree 2>/dev/null |
    awk -v marker="$MARKER" 'index($0, marker) {print $1; exit}' || true)
  [[ -n $WID ]] && break
  if ! process_matches "${XMESSAGE_PID:-}" "${XMESSAGE_STARTTIME:-}"; then
    fail window_start_failed "xmessage zakończył się przed utworzeniem okna" 2
  fi
  (($(date +%s) < DEADLINE)) || fail window_not_found "brak okna kontrolnego $MARKER w drzewie X" 2
  sleep 0.2
done

if ! timeout 5 wmctrl -l 2>/dev/null | grep -Fq "$MARKER"; then
  fail window_mismatch "WM nie widzi okna $MARKER (oczekiwano na liście wmctrl -l)" 2
fi

read_window_geometry() {
  local info
  info=$(timeout 5 xwininfo -display "$DISPLAY_NUM" -id "$WID" 2>/dev/null) || return 1
  grep -q 'Map State: IsViewable' <<<"$info" || return 1
  local x y w h
  x=$(awk -F: '/Absolute upper-left X/ {gsub(/ /, "", $2); print $2}' <<<"$info")
  y=$(awk -F: '/Absolute upper-left Y/ {gsub(/ /, "", $2); print $2}' <<<"$info")
  w=$(awk -F: '/^[[:space:]]*Width:/ {gsub(/ /, "", $2); print $2}' <<<"$info")
  h=$(awk -F: '/^[[:space:]]*Height:/ {gsub(/ /, "", $2); print $2}' <<<"$info")
  [[ $x =~ ^-?[0-9]+$ && $y =~ ^-?[0-9]+$ && $w =~ ^[0-9]+$ && $h =~ ^[0-9]+$ ]] || return 1
  CUR_X=$x CUR_Y=$y CUR_W=$w CUR_H=$h
  CURRENT_GEOM="${w}x${h}+${x}+${y}"
}

read_window_geometry || fail window_mismatch "nie można odczytać geometrii okna $WID" 2
WIN_GEOM_BEFORE=$CURRENT_GEOM
WIN_X=$CUR_X WIN_Y=$CUR_Y WIN_W=$CUR_W WIN_H=$CUR_H
INIT_X=$CUR_X
INIT_Y=$CUR_Y
INIT_W=$CUR_W
INIT_H=$CUR_H
WIN_TITLE_RAW=$(timeout 5 xprop -display "$DISPLAY_NUM" -id "$WID" WM_NAME _NET_WM_NAME 2>/dev/null || true)
grep -Fq "$MARKER" <<<"$WIN_TITLE_RAW" || fail window_mismatch "tytuł okna nie zawiera markera $MARKER" 2
WIN_TITLE=$MARKER
((WIN_W >= 200 && WIN_H >= 80)) || fail window_mismatch "okno kontrolne ma zbyt mały rozmiar: ${WIN_W}x${WIN_H}" 2
CHK_WINDOW=1
say "okno kontrolne ${WID} ${WIN_GEOM_BEFORE} (marker ${MARKER})"

take_shot() {
  local path=$1
  timeout 15 scrot -o "$path" >/dev/null 2>&1 || return 1
  [[ -s $path ]] || return 1
  chmod 0600 "$path"
}

analyze_shot() {
  local shot=$1 out=$2 spec=$3
  timeout 60 "$PY" "$HELPER" analyze --image "$shot" --window "$spec" \
    --bg "$BG_COLOR" --fg "$FG_COLOR" >"$out" 2>"$ARTIFACT_DIR/analysis.err" || return 1
  jq -e '.ok == true' "$out" >/dev/null 2>&1
}

apply_analysis() {
  local out=$1
  SCREEN_COLORS=$(jq -r '.screen_colors' "$out")
  WINDOW_COLORS=$(jq -r '.window_colors' "$out")
  BG_PIXELS=$(jq -r '.background_pixels' "$out")
  FG_PIXELS=$(jq -r '.foreground_pixels' "$out")
  BG_FRACTION=$(jq -r '.background_fraction' "$out")
}

SHOT1="$ARTIFACT_DIR/screen-initial.png"
take_shot "$SHOT1" || fail screenshot_failed "scrot nie zrobił zrzutu początkowego" 2
ANALYSIS1="$ARTIFACT_DIR/analysis-initial.json"
analyze_shot "$SHOT1" "$ANALYSIS1" "${WIN_X},${WIN_Y},${WIN_W},${WIN_H}" ||
  fail image_analysis_failed "analiza Pillow nie powiodła się: $(tail -n 3 "$ARTIFACT_DIR/analysis.err" | tr '\n' ' ')" 2
apply_analysis "$ANALYSIS1"

say "kolorów na ekranie: ${SCREEN_COLORS} (diagnostyka; próg ${MIN_COLORS} NIE decyduje o PASS)"
if ((SCREEN_COLORS < MIN_COLORS)); then
  say "UWAGA — kolorów mniej niż próg diagnostyczny ${MIN_COLORS}; to nie jest błąd"
fi
awk -v f="$BG_FRACTION" 'BEGIN {exit !(f >= 0.25)}' ||
  fail render_check_failed "tło okna zajmuje tylko ${BG_FRACTION} powierzchni (oczekiwano >= 0.25)" 2
((FG_PIXELS >= 50)) ||
  fail render_check_failed "brak pikseli tekstu w oknie (${FG_PIXELS}); możliwy brak fontów" 2
((WINDOW_COLORS >= 2)) ||
  fail render_check_failed "okno jest jednolite (${WINDOW_COLORS} kolorów); brak treści" 2
CHK_IMAGE=1
SHA_BEFORE=$(jq -r '.crop_sha256' "$ANALYSIS1")

# --- Interakcja: przesuń i skaluj okno, obraz musi się zmienić -------------------------------
NEW_X=$((WIN_X + 60))
NEW_Y=$((WIN_Y + 40))
NEW_W=$((WIN_W - 80))
NEW_H=$((WIN_H - 40))
((NEW_W >= 200 && NEW_H >= 80)) || fail interaction_failed "wyliczony rozmiar okna jest nieprawidłowy" 2
say "interakcja: wmctrl -e 0,${NEW_X},${NEW_Y},${NEW_W},${NEW_H}"
timeout 10 wmctrl -i -r "$WID" -e "0,${NEW_X},${NEW_Y},${NEW_W},${NEW_H}" >/dev/null 2>&1 ||
  fail interaction_failed "wmctrl nie przyjął polecenia przesunięcia/zmiany rozmiaru" 2

interacted=0
while :; do
  if read_window_geometry; then
    moved=0 resized=0
    ((CUR_X != INIT_X || CUR_Y != INIT_Y)) && moved=1
    ((CUR_W != INIT_W || CUR_H != INIT_H)) && resized=1
    if ((moved == 1 && resized == 1)); then
      interacted=1
      break
    fi
  fi
  (($(date +%s) < DEADLINE)) || fail interaction_failed "WM nie zmienił pozycji i rozmiaru okna w limicie czasu" 2
  sleep 0.2
done
WIN_GEOM_AFTER=$CURRENT_GEOM
WIN_X=$CUR_X WIN_Y=$CUR_Y WIN_W=$CUR_W WIN_H=$CUR_H
((interacted == 1)) || fail interaction_failed "geometria okna nie zmieniła się po interakcji" 2

SHOT2="$ARTIFACT_DIR/screen-interaction.png"
take_shot "$SHOT2" || fail screenshot_failed "scrot nie zrobił zrzutu po interakcji" 2
ANALYSIS2="$ARTIFACT_DIR/analysis-interaction.json"
analyze_shot "$SHOT2" "$ANALYSIS2" "${WIN_X},${WIN_Y},${WIN_W},${WIN_H}" ||
  fail image_analysis_failed "analiza Pillow po interakcji nie powiodła się: $(tail -n 3 "$ARTIFACT_DIR/analysis.err" | tr '\n' ' ')" 2
apply_analysis "$ANALYSIS2"
awk -v f="$BG_FRACTION" 'BEGIN {exit !(f >= 0.25)}' ||
  fail render_check_failed "tło okna po interakcji zajmuje tylko ${BG_FRACTION} powierzchni" 2
((FG_PIXELS >= 50)) ||
  fail render_check_failed "brak pikseli tekstu po interakcji (${FG_PIXELS})" 2
SHA_AFTER=$(jq -r '.crop_sha256' "$ANALYSIS2")
[[ $SHA_BEFORE != "$SHA_AFTER" ]] ||
  fail interaction_failed "obraz okna nie zmienił się po interakcji (ten sam skrót regionu)" 2
CHK_INTERACTION=1

STATUS=pass
REASON=ok
MESSAGE=""
EXIT_CODE=0
say "PASS — pulpit renderuje się (${GEOMETRY}), okno ${WIN_GEOM_AFTER}, kolorów ekranu ${SCREEN_COLORS} (diagnostyka)"
write_result
exit 0
