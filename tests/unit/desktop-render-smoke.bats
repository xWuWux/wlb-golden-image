#!/usr/bin/env bats
# Testy jednostkowe render-smoke pulpitu (#205): gotowość, okno kontrolne, interakcja,
# testy negatywne, result.json, retencja artefaktów i cleanup wyłącznie własnej sesji.
# Prawdziwy X/XFCE/TigerVNC jest poza zakresem jednostek — atrapy odwzorowują kontrakt poleceń.

load helpers

SCRIPT="$REPO_ROOT/tests/desktop-render-smoke.sh"

setup() {
  setup_sandbox
  ART="$BATS_TEST_TMPDIR/artifacts"
  export SMOKE_STATE="$BATS_TEST_TMPDIR/state"
  export CALLS
  mkdir -p "$ART" "$SMOKE_STATE" "$BATS_TEST_TMPDIR/x11-lock" "$BATS_TEST_TMPDIR/x11-socket"
  export TMPDIR="$BATS_TEST_TMPDIR"
  export WLB_SMOKE_ARTIFACT_DIR="$ART"
  export WLB_SMOKE_DISPLAY=":99"
  export WLB_SMOKE_GEOMETRY="1280x800"
  export WLB_SMOKE_TIMEOUT="5"
  export WLB_SMOKE_MIN_COLORS="64"
  export WLB_SMOKE_PYTHON="$STUBS/python"
  export WLB_SMOKE_X11_LOCK_DIR="$BATS_TEST_TMPDIR/x11-lock"
  export WLB_SMOKE_X11_SOCKET_DIR="$BATS_TEST_TMPDIR/x11-socket"
  unset SMOKE_SCREEN_COLORS SMOKE_WINDOW_COLORS SMOKE_FG_PIXELS SMOKE_BG_FRACTION SMOKE_SHA_CONSTANT
  install_smoke_stubs
}

teardown() {
  if [[ -n ${FOREIGN_PID:-} ]]; then
    kill -TERM -- "-$FOREIGN_PID" 2>/dev/null || true
  fi
  if [[ -f $SMOKE_STATE/vnc.pid ]]; then
    kill -TERM "$(cat "$SMOKE_STATE/vnc.pid")" 2>/dev/null || true
  fi
  if [[ -f $SMOKE_STATE/xmessage.pid ]]; then
    kill -TERM "$(cat "$SMOKE_STATE/xmessage.pid")" 2>/dev/null || true
  fi
}

# Wszystkie polecenia X/Pythona jako jeden dispatcher; symlinki nazw zachowują kontrakt poleceń.
install_smoke_stubs() {
  cat >"$STUBS/smoke-tool" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
name=${0##*/}
printf '%s %s\n' "$name" "$*" >>"$CALLS"
state=${SMOKE_STATE:?}
read_state() { [[ -f "$state/$1" ]] && cat "$state/$1"; }
write_state() { printf '%s' "$2" >"$state/$1"; }

case $name in
  xdpyinfo)
    [[ -f $state/no_x ]] && exit 1
    echo "dimensions: 640x480 pixels"
    ;;
  xprop)
    if [[ -f $state/no_wm ]]; then exit 1; fi
    case "$*" in
      *-root*) echo '_NET_SUPPORTING_WM_CHECK(WINDOW): window id # 0x600001' ;;
      *0x600001*) echo '_NET_WM_NAME(UTF8_STRING) = "xfwm4"' ;;
      *0x1*)
        title=$(read_state window_title)
        printf 'WM_NAME(STRING) = "%s"\n_NET_WM_NAME(UTF8_STRING) = "%s"\n' "$title" "$title"
        ;;
      *) exit 1 ;;
    esac
    ;;
  xwininfo)
    if [[ $* == *-root* ]]; then
      title=$(read_state window_title)
      [[ -n $title ]] || exit 0
      w=$(read_state window_w)
      h=$(read_state window_h)
      printf '0x1 "%s": ("xmessage" "Xmessage")  %sx%s+0+0  +0+0\n' "$title" "${w:-560}" "${h:-200}"
    else
      [[ -n $(read_state window_title) ]] || exit 1
      printf 'xwininfo: Window id: 0x1 "xmessage"\n'
      printf '  Absolute upper-left X:  %s\n' "$(read_state window_x)"
      printf '  Absolute upper-left Y:  %s\n' "$(read_state window_y)"
      printf '  Width: %s\n' "$(read_state window_w)"
      printf '  Height: %s\n' "$(read_state window_h)"
      printf '  Map State: IsViewable\n'
    fi
    ;;
  wmctrl)
    if [[ $* == *-l* ]]; then
      title=$(read_state window_title)
      [[ -n $title ]] && printf '0x00000001  0 host %s\n' "$title"
      exit 0
    fi
    spec=""
    prev=""
    for arg in "$@"; do
      [[ $prev == -e ]] && spec=$arg
      prev=$arg
    done
    [[ -f $state/no_interaction ]] && exit 0
    IFS=, read -r _ x y w h <<<"$spec"
    write_state window_x "$x"
    write_state window_y "$y"
    write_state window_w "$w"
    write_state window_h "$h"
    ;;
  xmessage)
    title=""
    geometry=""
    while (($#)); do
      case $1 in
        -title) title=$2; shift 2 ;;
        -geometry) geometry=$2; shift 2 ;;
        *) shift ;;
      esac
    done
    [[ -f $state/window_start_fail ]] && exit 1
    IFS='x+' read -r w h x y <<<"$geometry"
    write_state window_title "$title"
    write_state window_x "$x"
    write_state window_y "$y"
    write_state window_w "$w"
    write_state window_h "$h"
    echo $$ >"$state/xmessage.pid"
    exec sleep 300
    ;;
  scrot)
    out="${!#}"
    [[ -f $state/shot_fail ]] && exit 1
    [[ -f $state/shot_fail_after && $out == *interaction* ]] && exit 1
    printf 'PNG-STUB\n' >"$out"
    ;;
  python)
    if [[ ${1:-} == -c ]]; then
      [[ -f $state/no_pillow ]] && exit 1
      exit 0
    fi
    [[ -f $state/analysis_error ]] && {
      echo 'stub analysis error' >&2
      echo '{"ok":false,"error":"stub"}'
      exit 2
    }
    window=""
    image=""
    while (($#)); do
      case $1 in
        --window) window=$2; shift 2 ;;
        --image) image=$2; shift 2 ;;
        *) shift ;;
      esac
    done
    IFS=, read -r x y w h <<<"$window"
    screen=${SMOKE_SCREEN_COLORS:-5000}
    win_colors=${SMOKE_WINDOW_COLORS:-12}
    fg=${SMOKE_FG_PIXELS:-800}
    frac=${SMOKE_BG_FRACTION:-0.8}
    if [[ ${SMOKE_SHA_CONSTANT:-0} == 1 ]]; then
      sha=constant
    else
      sha=$(printf '%s' "$window" | sha256sum | cut -c1-32)
    fi
    printf '{"ok":true,"image":"%s","width":640,"height":480,' "$image"
    printf '"window":{"x":%s,"y":%s,"width":%s,"height":%s},' "$x" "$y" "$w" "$h"
    printf '"screen_colors":%s,"window_colors":%s,"background_pixels":1000,' "$screen" "$win_colors"
    printf '"foreground_pixels":%s,"background_fraction":%s,"crop_sha256":"%s"}\n' "$fg" "$frac" "$sha"
    ;;
  pgrep)
    name=""
    prev=""
    for arg in "$@"; do
      [[ $prev == -x ]] && name=$arg
      prev=$arg
    done
    [[ -f $state/dead_session ]] && exit 1
    [[ -n $name && -f $state/no_$name ]] && exit 1
    exit 0
    ;;
  vncserver | tigervncserver)
    sock=""
    display=""
    while (($#)); do
      case $1 in
        -rfbunixpath) sock=$2; shift 2 ;;
        :*) display=$1; shift ;;
        *) shift ;;
      esac
    done
    if [[ -f $state/vnc_busy && $display == :99 ]]; then
      echo "A X11 server is already running for display ${display}" >&2
      exit 1
    fi
    if [[ ! -f $state/vnc_nosocket ]]; then
      /usr/bin/python3 - "$sock" <<'PY'
import socket
import sys

sock = socket.socket(socket.AF_UNIX)
sock.bind(sys.argv[1])
sock.close()
PY
    fi
    echo $$ >"$state/vnc.pid"
    : >"$state/vnc-started"
    if [[ -f $state/vnc_partial ]]; then
      echo "partial start: X nie wstał" >&2
      exit 1
    fi
    exec sleep 300
    ;;
  xauth | startxfce4 | dbus-launch)
    :
    ;;
  *)
    echo "nieznana atrapa: $name" >&2
    exit 1
    ;;
esac
STUB
  chmod +x "$STUBS/smoke-tool"
  for name in tigervncserver vncserver python xdpyinfo xprop xwininfo wmctrl xmessage scrot pgrep \
    xauth startxfce4 dbus-launch; do
    ln -sf smoke-tool "$STUBS/$name"
  done
}

result() { jq -r "$1" "$ART/result.json"; }

wait_for_file() {
  local file=$1
  for _ in $(seq 1 100); do
    [[ -e $file ]] && return 0
    sleep 0.05
  done
  return 1
}

wait_for_pid_gone() {
  local pid=$1 state
  for _ in $(seq 1 100); do
    kill -0 "$pid" 2>/dev/null || return 0
    # Proces zabity przez cleanup bywa jeszcze ZOMBIE: jest martwy, czeka tylko na reap, który pod
    # obciążeniem potrafi się opóźnić. kill -0 widzi zombie jako „żywy", więc to samo w sobie sprawdzał
    # flaky. Zombie (stan Z) albo brak stanu traktujemy jak zniknięty — sesja została zatrzymana.
    state=$(ps -o state= -p "$pid" 2>/dev/null | tr -d ' ')
    [[ -z $state || $state == Z* ]] && return 0
    sleep 0.05
  done
  return 1
}

@test "PASS: gotowość, okno, tekst, interakcja i result.json" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(result .status)" = pass ]
  [ "$(result .reason)" = ok ]
  [ "$(result .schema)" = "wlb.desktop-render-smoke/v1" ]
  [ "$(result .checks.x)" = true ]
  [ "$(result .checks.vnc_socket)" = true ]
  [ "$(result .checks.wm)" = true ]
  [ "$(result .checks.session)" = true ]
  [ "$(result .checks.panel)" = true ]
  [ "$(result .checks.dbus)" = true ]
  [ "$(result .checks.window)" = true ]
  [ "$(result .checks.image)" = true ]
  [ "$(result .checks.interaction)" = true ]
  [ -s "$ART/screen-initial.png" ]
  [ -s "$ART/screen-interaction.png" ]
  [ "$(result .window.geometry_before)" != "$(result .window.geometry_after)" ]
  [[ $(result .window.title) =~ ^WLB-SMOKE- ]]
  [[ $(result .window.title) != *WM_NAME* ]]
  called "rfbunixpath"
  called "rfbport -1"
  called "SecurityTypes None"
  called "xstartup"
  refute grep -q -- 'vncserver -kill' "$CALLS"
  [ -s "$SMOKE_STATE/vnc.pid" ]
  wait_for_pid_gone "$(cat "$SMOKE_STATE/vnc.pid")"
}

@test "PASS: liczba kolorów jest tylko diagnostyką (MIN_COLORS nie decyduje)" {
  run env SMOKE_SCREEN_COLORS=2 WLB_SMOKE_MIN_COLORS=999999 bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(result .status)" = pass ]
  [ "$(result .colors.screen)" -eq 2 ]
  [ "$(result .min_colors)" -eq 999999 ]
}

@test "FAIL: jednolite tło okna (brak tekstu) to błąd renderu, nie PASS kolorów" {
  run env SMOKE_FG_PIXELS=0 SMOKE_WINDOW_COLORS=1 bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .status)" = fail ]
  [ "$(result .reason)" = render_check_failed ]
  [ "$(result .checks.image)" = false ]
  [ -s "$ART/screen-initial.png" ]
  [ -s "$ART/result.json" ]
}

@test "FAIL: gradient bez tła okna jest odrzucany" {
  run env SMOKE_BG_FRACTION=0 SMOKE_FG_PIXELS=0 bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .reason)" = render_check_failed ]
  [ "$(result .colors.background_fraction)" = 0 ]
}

@test "FAIL: brak fontów (zero pikseli tekstu) jest odrzucany" {
  run env SMOKE_FG_PIXELS=0 bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .reason)" = render_check_failed ]
  [[ $(result .message) == *"font"* ]]
}

@test "FAIL: okno błędu bez markera nie jest kontrolowanym oknem" {
  : >"$SMOKE_STATE/window_start_fail"
  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .reason)" = window_start_failed ]
  [ "$(result .checks.window)" = false ]
}

@test "FAIL: brak WM jest wykrywany w deadline, bez decydowania o PASS" {
  : >"$SMOKE_STATE/no_wm"
  run env WLB_SMOKE_TIMEOUT=2 bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = readiness_timeout ]
  [ "$(result .checks.wm)" = false ]
  [ "$(result .checks.x)" = true ]
  [[ $(result .message) == *WM* ]]
}

@test "FAIL: martwa sesja (brak xfce4-session) jest wykrywana" {
  : >"$SMOKE_STATE/no_xfce4-session"
  run env WLB_SMOKE_TIMEOUT=2 bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = readiness_timeout ]
  [ "$(result .checks.session)" = false ]
}

@test "FAIL: całkowicie martwa sesja (pgrep bez procesów) nie wisi" {
  : >"$SMOKE_STATE/dead_session"
  run env WLB_SMOKE_TIMEOUT=2 bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = readiness_timeout ]
  [ "$(result .checks.session)" = false ]
  [ "$(result .checks.panel)" = false ]
  [ "$(result .checks.dbus)" = false ]
}

@test "FAIL: brak panelu XFCE jest wykrywany" {
  : >"$SMOKE_STATE/no_xfce4-panel"
  run env WLB_SMOKE_TIMEOUT=2 bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = readiness_timeout ]
  [ "$(result .checks.panel)" = false ]
}

@test "FAIL: brak D-Bus sesji jest wykrywany" {
  : >"$SMOKE_STATE/no_dbus-daemon"
  run env WLB_SMOKE_TIMEOUT=2 bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = readiness_timeout ]
  [ "$(result .checks.dbus)" = false ]
}

@test "FAIL: zajęty display nie uruchamia VNC i nie dotyka cudzej sesji" {
  : >"$BATS_TEST_TMPDIR/x11-lock/.X99-lock"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = display_busy ]
  refute called "tigervncserver :99"
}

@test "FAIL: wrapper zgłasza zajęty display — wymuszony display kończy się display_busy" {
  : >"$SMOKE_STATE/vnc_busy"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = display_busy ]
  called "tigervncserver :99"
}

@test "PASS: auto-display pomija display zajęty przez wrapper i wybiera :100" {
  : >"$SMOKE_STATE/vnc_busy"
  run env WLB_SMOKE_DISPLAY= bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(result .display)" = ":100" ]
  called "tigervncserver :100"
}

@test "FAIL: częściowy start VNC kończy się bez zawieszenia" {
  : >"$SMOKE_STATE/vnc_partial"
  : >"$SMOKE_STATE/no_x"
  run env WLB_SMOKE_TIMEOUT=2 bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = vnc_start_failed ]
  [ -s "$ART/vnc.log" ]
}

@test "FAIL: analiza obrazu bez Pillow ma czytelny powód" {
  : >"$SMOKE_STATE/no_pillow"
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = missing_pillow ]
}

@test "FAIL: błąd analizy Pillow trafia do result.json" {
  : >"$SMOKE_STATE/analysis_error"
  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .reason)" = image_analysis_failed ]
  [ -s "$ART/analysis.err" ]
}

@test "FAIL: brak reakcji na wmctrl jest wykrywany" {
  : >"$SMOKE_STATE/no_interaction"
  run env WLB_SMOKE_TIMEOUT=2 bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .reason)" = interaction_failed ]
  [ "$(result .checks.interaction)" = false ]
}

@test "FAIL: interakcja bez zmiany obrazu jest odrzucana" {
  run env SMOKE_SHA_CONSTANT=1 bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .reason)" = interaction_failed ]
  [ "$(result .checks.interaction)" = false ]
}

@test "FAIL: scrot po interakcji zachowuje wynik i artefakty" {
  : >"$SMOKE_STATE/shot_fail_after"
  run bash "$SCRIPT"
  [ "$status" -eq 2 ]
  [ "$(result .reason)" = screenshot_failed ]
  [ -s "$ART/screen-initial.png" ]
  [ -s "$ART/result.json" ]
}

@test "FAIL: niepoprawny display daje result.json, nie start VNC" {
  run env WLB_SMOKE_DISPLAY=':zle' bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = invalid_display ]
  refute called "tigervncserver"
}

@test "FAIL: niepoprawna geometria i timeout są walidowane przed startem" {
  run env WLB_SMOKE_GEOMETRY='900x' bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = invalid_geometry ]
  rm -f "$ART/result.json"
  run env WLB_SMOKE_TIMEOUT=0 bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = invalid_timeout ]
}

@test "FAIL: niepoprawny MIN_COLORS jest walidowany, ale nie wywraca JSON" {
  run env WLB_SMOKE_MIN_COLORS=abc bash "$SCRIPT"
  [ "$status" -eq 1 ]
  [ "$(result .reason)" = invalid_min_colors ]
  [ "$(result .min_colors)" = null ]
}

@test "PASS: auto-display pomija zajęty :99 i wybiera :100" {
  : >"$BATS_TEST_TMPDIR/x11-lock/.X99-lock"
  run env WLB_SMOKE_DISPLAY= bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(result .display)" = ":100" ]
  called "tigervncserver :100"
}

@test "SIGTERM: wynik fail, własna sesja zatrzymana, obca sesja nietknięta" {
  setsid sleep 300 &
  FOREIGN_PID=$!
  export FOREIGN_PID
  bash "$SCRIPT" >"$BATS_TEST_TMPDIR/signal.out" 2>&1 &
  local runner=$!
  wait_for_file "$SMOKE_STATE/vnc-started"
  kill -TERM "$runner"
  wait "$runner" || true
  [ "$(result .status)" = fail ]
  [ "$(result .reason)" = signal_term ]
  [ "$(result .exit_code)" -eq 143 ]
  wait_for_pid_gone "$(cat "$SMOKE_STATE/vnc.pid")"
  kill -0 "$FOREIGN_PID"
}

@test "PASS: dwa równoległe przebiegi nie zabijają swoich sesji" {
  local art1="$BATS_TEST_TMPDIR/art1" art2="$BATS_TEST_TMPDIR/art2"
  local state1="$BATS_TEST_TMPDIR/state1" state2="$BATS_TEST_TMPDIR/state2"
  mkdir -p "$art1" "$art2" "$state1" "$state2"
  env WLB_SMOKE_DISPLAY=:99 WLB_SMOKE_ARTIFACT_DIR="$art1" SMOKE_STATE="$state1" bash "$SCRIPT" \
    >"$BATS_TEST_TMPDIR/out1" 2>&1 &
  local p1=$!
  env WLB_SMOKE_DISPLAY=:100 WLB_SMOKE_ARTIFACT_DIR="$art2" SMOKE_STATE="$state2" bash "$SCRIPT" \
    >"$BATS_TEST_TMPDIR/out2" 2>&1 &
  local p2=$!
  wait "$p1"
  wait "$p2"
  jq -e '.status == "pass"' "$art1/result.json" >/dev/null
  jq -e '.status == "pass"' "$art2/result.json" >/dev/null
  wait_for_pid_gone "$(cat "$state1/vnc.pid")"
  wait_for_pid_gone "$(cat "$state2/vnc.pid")"
}
