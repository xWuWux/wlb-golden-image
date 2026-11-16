#!/usr/bin/env bash
# /opt/wlb/e2e/mouse-target.sh — in-session mouse target dla testów E2E (#277).
#
# Uruchamia dialog zenity --question na deterministycznej pozycji i rozmiarze,
# publikuje deskryptor /run/wlb/e2e/target.json zgodny ze schematem wlb.e2e-target/v1,
# a po kliknięciu przycisku OK zapisuje kod wyniku do /run/wlb/e2e/mouse.txt (rc=0).
#
# Parametry środowiskowe (przydatne m.in. w testach jednostkowych):
#   WLB_E2E_MARKER_DIR        ścieżka do katalogu markerów (domyślnie: /run/wlb/e2e)
#   WLB_E2E_SESSION_FILE      ścieżka do trwałego identyfikatora sesji
#   WLB_E2E_SCREEN_GEOMETRY   wymuszona rozdzielczość ekranu WxH (np. 1024x768)
set -euo pipefail

MARKER_DIR="${WLB_E2E_MARKER_DIR:-/run/wlb/e2e}"
TARGET_FILE="$MARKER_DIR/target.json"
MOUSE_FILE="$MARKER_DIR/mouse.txt"

mkdir -p "$MARKER_DIR" 2>/dev/null || true

# Session ID: trwały identyfikator sesji X (przetrwa czyszczenie /run/wlb/e2e/* przez test)
SESSION_FILE="${WLB_E2E_SESSION_FILE:-/tmp/.wlb-e2e-session-id-${USER:-badacz}-${DISPLAY:-0}}"
if [ -f "$SESSION_FILE" ] && [ -s "$SESSION_FILE" ]; then
  SESSION_ID=$(head -n 1 "$SESSION_FILE")
else
  SESSION_ID=$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "wlb-e2e-$$")
  printf "%s\n" "$SESSION_ID" > "$SESSION_FILE" 2>/dev/null || true
fi

# Rozmiar ekranu (framebuffer VNC / X screen)
SCREEN_W=""
SCREEN_H=""
if [ -n "${WLB_E2E_SCREEN_GEOMETRY:-}" ]; then
  SCREEN_W="${WLB_E2E_SCREEN_GEOMETRY%x*}"
  SCREEN_H="${WLB_E2E_SCREEN_GEOMETRY#*x}"
fi
if [ -z "$SCREEN_W" ] || [ -z "$SCREEN_H" ]; then
  if command -v xdpyinfo >/dev/null 2>&1; then
    DIMS=$(xdpyinfo 2>/dev/null | awk '/dimensions:/ {print $2}')
    if [ -n "$DIMS" ]; then
      SCREEN_W="${DIMS%x*}"
      SCREEN_H="${DIMS#*x}"
    fi
  fi
fi
if [ -z "$SCREEN_W" ] || [ -z "$SCREEN_H" ]; then
  if command -v xwininfo >/dev/null 2>&1; then
    SCREEN_W=$(xwininfo -root 2>/dev/null | awk '/Width:/ {print $2}')
    SCREEN_H=$(xwininfo -root 2>/dev/null | awk '/Height:/ {print $2}')
  fi
fi
SCREEN_W="${SCREEN_W:-1024}"
SCREEN_H="${SCREEN_H:-768}"

# Rozmiar i pozycja okna zenity
WIN_W=360
WIN_H=180
WIN_X=$(( (SCREEN_W - WIN_W) / 2 ))
WIN_Y=$(( (SCREEN_H - WIN_H) / 2 ))

WINDOW_TITLE="E2E Mouse Target"

# Uruchomienie zenity w tle
rc=0
zenity --question \
  --title="$WINDOW_TITLE" \
  --text="Kliknij 'OK', aby potwierdzić interakcję myszą (test E2E)." \
  --ok-label="OK" \
  --cancel-label="Anuluj" \
  --width="$WIN_W" \
  --height="$WIN_H" \
  --no-wrap &
ZENITY_PID=$!

# Czekaj na pojawienie się okna i ustaw pozycję przez wmctrl
WID=""
for _ in $(seq 1 40); do
  if command -v wmctrl >/dev/null 2>&1; then
    WID=$(wmctrl -l 2>/dev/null | awk -v t="$WINDOW_TITLE" '$0 ~ t {print $1; exit}')
    [ -n "$WID" ] && break
  fi
  sleep 0.1
done

if [ -n "$WID" ] && command -v wmctrl >/dev/null 2>&1; then
  wmctrl -i -r "$WID" -e "0,$WIN_X,$WIN_Y,$WIN_W,$WIN_H" 2>/dev/null || true
fi

# Odczytaj rzeczywiste współrzędne okna po zarządzaniu przez WM
if [ -n "$WID" ] && command -v xwininfo >/dev/null 2>&1; then
  INFO=$(xwininfo -id "$WID" 2>/dev/null || true)
  if [ -n "$INFO" ]; then
    ACT_X=$(awk -F: '/Absolute upper-left X/ {gsub(/ /, "", $2); print $2}' <<< "$INFO")
    ACT_Y=$(awk -F: '/Absolute upper-left Y/ {gsub(/ /, "", $2); print $2}' <<< "$INFO")
    ACT_W=$(awk -F: '/^[[:space:]]*Width:/ {gsub(/ /, "", $2); print $2}' <<< "$INFO")
    ACT_H=$(awk -F: '/^[[:space:]]*Height:/ {gsub(/ /, "", $2); print $2}' <<< "$INFO")
    [ -n "$ACT_X" ] && WIN_X="$ACT_X"
    [ -n "$ACT_Y" ] && WIN_Y="$ACT_Y"
    [ -n "$ACT_W" ] && WIN_W="$ACT_W"
    [ -n "$ACT_H" ] && WIN_H="$ACT_H"
  fi
fi

# Obliczenie współrzędnych przycisku OK na ekranie (w pikselach bufora)
BTN_W=80
BTN_H=34
BTN_X=$(( WIN_X + WIN_W - BTN_W - 16 ))
BTN_Y=$(( WIN_Y + WIN_H - BTN_H - 14 ))

# Wygenerowanie i publikacja /run/wlb/e2e/target.json
write_target_json() {
  cat > "${TARGET_FILE}.tmp" <<EOF
{
  "schema": "wlb.e2e-target/v1",
  "session_id": "$SESSION_ID",
  "screen": {
    "w": $SCREEN_W,
    "h": $SCREEN_H
  },
  "button": {
    "x": $BTN_X,
    "y": $BTN_Y,
    "w": $BTN_W,
    "h": $BTN_H
  },
  "keyboard": {
    "title": "E2E Keyboard Target"
  }
}
EOF
  mv "${TARGET_FILE}.tmp" "$TARGET_FILE"
}

write_target_json

# Utrzymuj target.json przy życiu w tle, gdyby test wyczyścił /run/wlb/e2e/*
(
  while kill -0 "$ZENITY_PID" 2>/dev/null; do
    if [ ! -f "$TARGET_FILE" ]; then
      write_target_json 2>/dev/null || true
    fi
    sleep 0.2
  done
) &
MONITOR_PID=$!

# Czekaj na zakończenie zenity (kliknięcie lub timeout)
wait "$ZENITY_PID" || rc=$?

# Zapisz wynik kliknięcia do mouse.txt
printf "rc=%d\n" "$rc" > "$MOUSE_FILE"

# Zatrzymaj pętlę monitorującą
kill "$MONITOR_PID" 2>/dev/null || true
wait "$MONITOR_PID" 2>/dev/null || true

# Upewnij się, że target.json nadal istnieje po kliknięciu
if [ ! -f "$TARGET_FILE" ]; then
  write_target_json 2>/dev/null || true
fi

exit "$rc"
