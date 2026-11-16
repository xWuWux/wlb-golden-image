#!/usr/bin/env bash
# /opt/wlb/e2e/keyboard-target.sh — listener klawiatury dla testów E2E (#277).
# Uruchamiany w terminalu (xfce4-terminal / xterm) z fokusem X. Każda linia
# wejścia (nonce + Enter z Playwrighta) jest zapisywana do /run/wlb/e2e/keyboard.txt.
#
# Parametry środowiskowe:
#   WLB_E2E_MARKER_DIR    ścieżka do katalogu markerów (domyślnie: /run/wlb/e2e)
set -euo pipefail

MARKER_DIR="${WLB_E2E_MARKER_DIR:-/run/wlb/e2e}"
MARKER_FILE="$MARKER_DIR/keyboard.txt"

mkdir -p "$MARKER_DIR" 2>/dev/null || true

echo "=== WLB E2E Keyboard Target ==="
echo "Marker: $MARKER_FILE"
echo "Oczekiwanie na nonce z Playwrighta..."

while IFS= read -r line; do
  printf "%s\n" "$line" > "$MARKER_FILE"
  echo "[E2E] Zapisano nonce: $line"
done
