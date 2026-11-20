#!/usr/bin/env bash
# /opt/wlb/e2e/target-runner.sh — autostart targetu E2E w sesji XFCE (#277).
# Uruchamia w sesji:
#   1) mouse-target.sh (okno zenity + target.json)
#   2) xfce4-terminal / xterm z listenerem keyboard-target.sh (fokus klawiatury)
#
# Parametry środowiskowe:
#   WLB_E2E_MARKER_DIR    ścieżka do katalogu markerów (domyślnie: /run/wlb/e2e)
set -euo pipefail

MARKER_DIR="${WLB_E2E_MARKER_DIR:-/run/wlb/e2e}"
mkdir -p "$MARKER_DIR" 2>/dev/null || true

# Krótkie opóźnienie, aby XFCE i xfwm4 zdążyły zainicjalizować ekran
sleep 1

# Uruchom mouse-target.sh w tle (zarządza oknem zenity oraz target.json)
/opt/wlb/e2e/mouse-target.sh &

# Uruchom terminal klawiatury (preferowany xfce4-terminal, fallback na xterm)
if command -v xfce4-terminal >/dev/null 2>&1; then
  if ! pgrep -f "E2E Keyboard Target" >/dev/null 2>&1; then
    xfce4-terminal \
      --title="E2E Keyboard Target" \
      --geometry=70x12+20+20 \
      --command="/opt/wlb/e2e/keyboard-target.sh" &
  fi
elif command -v xterm >/dev/null 2>&1; then
  if ! pgrep -f "E2E Keyboard Target" >/dev/null 2>&1; then
    xterm -title "E2E Keyboard Target" \
      -geometry 70x12+20+20 \
      -e /opt/wlb/e2e/keyboard-target.sh &
  fi
fi

# Nadaj fokus terminalowi klawiatury po chwili
sleep 0.5
if command -v wmctrl >/dev/null 2>&1; then
  wmctrl -a "E2E Keyboard Target" 2>/dev/null || true
fi
