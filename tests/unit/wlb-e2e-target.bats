#!/usr/bin/env bats
# wlb-e2e-target.bats — testy jednostkowe targetu in-session E2E (#277-A)
#
# Weryfikuje kontrakt #277-A -> #277-B:
#   * deskryptor /run/wlb/e2e/target.json (schema: wlb.e2e-target/v1, session_id, screen, button)
#   * walidacja target.json przez reguły z desktop-e2e-novnc.py
#   * marker myszy /run/wlb/e2e/mouse.txt (rc=0)
#   * marker klawiatury /run/wlb/e2e/keyboard.txt (nonce)
#   * konfiguracja tmpfiles i uprawnienia 0777
#   * kafelki .desktop z absolutnymi ścieżkami Exec (#199)

load helpers.bash

setup() {
  setup_sandbox
  TARGET_DIR="$REPO_ROOT/ansible/roles/desktop/files"
  export MOUSE_SCRIPT="$TARGET_DIR/mouse-target.sh"
  export KEYBOARD_SCRIPT="$TARGET_DIR/keyboard-target.sh"
  export RUNNER_SCRIPT="$TARGET_DIR/target-runner.sh"
  export TMPFILES_CONF="$TARGET_DIR/wlb-e2e-tmpfiles.conf"
  export MOUSE_DESKTOP="$TARGET_DIR/wlb-e2e-mouse.desktop"
  export AUTOSTART_DESKTOP="$TARGET_DIR/wlb-e2e-target.desktop"

  export WLB_E2E_MARKER_DIR="$SANDBOX/run/wlb/e2e"
  export WLB_E2E_SESSION_FILE="$SANDBOX/tmp/.wlb-e2e-session-id"
  export WLB_E2E_SCREEN_GEOMETRY="1024x768"
  mkdir -p "$WLB_E2E_MARKER_DIR" "$SANDBOX/tmp"
}

@test "mouse-target.sh: generuje poprawny /run/wlb/e2e/target.json z wymaganymi polami (#277)" {
  stub zenity 0
  stub wmctrl 0
  stub xwininfo 0 "Absolute upper-left X: 332
Absolute upper-left Y: 294
Width: 360
Height: 180"

  run "$MOUSE_SCRIPT"
  [ "$status" -eq 0 ]
  [ -f "$WLB_E2E_MARKER_DIR/target.json" ]

  # Sprawdzenie pól w JSON przez jq
  run jq -e '.schema == "wlb.e2e-target/v1"' "$WLB_E2E_MARKER_DIR/target.json"
  [ "$status" -eq 0 ]
  run jq -e '.session_id | type == "string" and length > 0' "$WLB_E2E_MARKER_DIR/target.json"
  [ "$status" -eq 0 ]
  run jq -e '.screen.w == 1024 and .screen.h == 768' "$WLB_E2E_MARKER_DIR/target.json"
  [ "$status" -eq 0 ]
  run jq -e '.button.x > 0 and .button.y > 0 and .button.w > 0 and .button.h > 0' "$WLB_E2E_MARKER_DIR/target.json"
  [ "$status" -eq 0 ]
  run jq -e '.keyboard.title == "E2E Keyboard Target"' "$WLB_E2E_MARKER_DIR/target.json"
  [ "$status" -eq 0 ]
}

@test "target.json: przechodzi pełną walidację parsera z desktop-e2e-novnc.py (#277)" {
  stub zenity 0
  stub wmctrl 0
  stub xwininfo 0 "Absolute upper-left X: 332
Absolute upper-left Y: 294
Width: 360
Height: 180"

  run "$MOUSE_SCRIPT"
  [ "$status" -eq 0 ]

  run python3 -c '
import json, sys

TARGET_SCHEMA = "wlb.e2e-target/v1"

def validate(data):
    if not isinstance(data, dict):
        sys.exit("nie dict")
    if data.get("schema") != TARGET_SCHEMA:
        sys.exit("zly schema")
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        sys.exit("brak session_id")
    screen = data.get("screen")
    if not isinstance(screen, dict) or screen.get("w", 0) <= 0 or screen.get("h", 0) <= 0:
        sys.exit("zly screen")
    button = data.get("button")
    if not isinstance(button, dict) or button.get("w", 0) <= 0 or button.get("h", 0) <= 0:
        sys.exit("zly button")
    return True

with open(sys.argv[1], encoding="utf-8") as f:
    d = json.load(f)
validate(d)
print("VALID_OK")
' "$WLB_E2E_MARKER_DIR/target.json"

  [ "$status" -eq 0 ]
  [[ "$output" =~ "VALID_OK" ]]
}

@test "session_id: jest trwały i nie zmienia się po wyczyszczeniu markerów (#277)" {
  stub zenity 0
  stub wmctrl 0
  stub xwininfo 0

  run "$MOUSE_SCRIPT"
  [ "$status" -eq 0 ]
  first_sid=$(jq -r '.session_id' "$WLB_E2E_MARKER_DIR/target.json")

  # Symulacja clean() z testu E2E: usunięcie zawartości katalogu markerów
  rm -rf "${WLB_E2E_MARKER_DIR:?}"/*

  run "$MOUSE_SCRIPT"
  [ "$status" -eq 0 ]
  second_sid=$(jq -r '.session_id' "$WLB_E2E_MARKER_DIR/target.json")

  [ -n "$first_sid" ]
  [ "$first_sid" = "$second_sid" ]
}

@test "mouse-target.sh: zapisuje mouse.txt rc=0 przy kliknięciu OK w zenity (#277)" {
  stub zenity 0
  stub wmctrl 0
  stub xwininfo 0

  run "$MOUSE_SCRIPT"
  [ "$status" -eq 0 ]
  [ -f "$WLB_E2E_MARKER_DIR/mouse.txt" ]
  [ "$(cat "$WLB_E2E_MARKER_DIR/mouse.txt")" = "rc=0" ]
}

@test "mouse-target.sh: zapisuje rc!=0 przy anulowaniu zenity (#277)" {
  stub zenity 1
  stub wmctrl 0
  stub xwininfo 0

  run "$MOUSE_SCRIPT"
  [ "$status" -eq 1 ]
  [ -f "$WLB_E2E_MARKER_DIR/mouse.txt" ]
  [ "$(cat "$WLB_E2E_MARKER_DIR/mouse.txt")" = "rc=1" ]
}

@test "keyboard-target.sh: zapisuje każdą odczytaną linię nonce do keyboard.txt (#277)" {
  nonce1="e4a5c6d7-1111-2222-3333-444455556666"
  nonce2="a1b2c3d4-5555-6666-7777-888899990000"

  run bash -c "printf '%s\n%s\n' '$nonce1' '$nonce2' | '$KEYBOARD_SCRIPT'"
  [ "$status" -eq 0 ]
  [ -f "$WLB_E2E_MARKER_DIR/keyboard.txt" ]
  # Ostatni zapisany nonce to nonce2
  [ "$(cat "$WLB_E2E_MARKER_DIR/keyboard.txt")" = "$nonce2" ]
}

@test "wlb-e2e-tmpfiles.conf: deklaruje katalog /run/wlb/e2e z uprawnieniami 0777 (#277)" {
  [ -f "$TMPFILES_CONF" ]
  run grep -E '^d /run/wlb/e2e 0777 root root -' "$TMPFILES_CONF"
  [ "$status" -eq 0 ]
}

@test "kafelki .desktop: posiadają poprawny format i absolutne ścieżki Exec (#199, #277)" {
  [ -f "$MOUSE_DESKTOP" ]
  [ -f "$AUTOSTART_DESKTOP" ]

  run grep -E '^Exec=/opt/wlb/e2e/mouse-target\.sh' "$MOUSE_DESKTOP"
  [ "$status" -eq 0 ]

  run grep -E '^Exec=/opt/wlb/e2e/target-runner\.sh' "$AUTOSTART_DESKTOP"
  [ "$status" -eq 0 ]

  run grep -E '^Icon=input-mouse' "$MOUSE_DESKTOP"
  [ "$status" -eq 0 ]
}

@test "mouse-target.sh: przelicza geometrię target.json po zmianie ekranu (resize/reconnect, #277 review)" {
  # jupyter-remote-desktop-proxy ustawia rfb.resizeSession=true — po resize ekran X zmienia
  # rozmiar i target.json MUSI dostać świeże screen/button, nie tylko „plik istnieje".
  # Regres (brak funkcji geometrii / pętla tylko '! -f', bez strażnika sourcowania) obala ten test.
  # Wykonujemy skrypt w trybie --emit-target (nie sourcujemy): to omija konflikt kcov+set-u przy
  # sourcowaniu instrumentowanego skryptu, a jednocześnie przechodzi przez REALNE funkcje geometrii.
  run env WLB_E2E_SCREEN_GEOMETRY=1024x768 "$MOUSE_SCRIPT" --emit-target
  [ "$status" -eq 0 ]
  w1=$(jq -r ".screen.w" "$WLB_E2E_MARKER_DIR/target.json")
  bx1=$(jq -r ".button.x" "$WLB_E2E_MARKER_DIR/target.json")

  run env WLB_E2E_SCREEN_GEOMETRY=1920x1080 "$MOUSE_SCRIPT" --emit-target
  [ "$status" -eq 0 ]
  w2=$(jq -r ".screen.w" "$WLB_E2E_MARKER_DIR/target.json")
  bx2=$(jq -r ".button.x" "$WLB_E2E_MARKER_DIR/target.json")

  # Zmiana ekranu 1024->1920 MUSI dać nowe screen.w i nową pozycję przycisku (nie tylko „plik istnieje")
  [ "$w1" = "1024" ]
  [ "$w2" = "1920" ]
  [ "$bx1" != "$bx2" ]
}
