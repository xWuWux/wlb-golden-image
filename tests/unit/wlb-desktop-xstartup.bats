#!/usr/bin/env bats
# Testy jednostkowe wlb-desktop-xstartup (#278): xstartup sesji pulpitu MUSI wyeksportować
# XAUTHORITY (i DISPLAY) do potomków, inaczej natywne apki GUI (LibreOffice Calc/Writer) padają
# "no authorization protocol specified". Atrapa interpretera TLJH (WLB_TLJH_PYTHON) zwraca ścieżkę
# domyślnego xstartup jrdp; „downstream" (łańcuch jrdp albo fallback dbus-launch/startxfce4) zrzuca
# środowisko do pliku, więc test weryfikuje, CO realnie dziedziczy sesja.

load helpers

XSTARTUP="$REPO_ROOT/ansible/roles/desktop/files/wlb-desktop-xstartup"

setup() {
  setup_sandbox
  export HOME="$SANDBOX/home"
  mkdir -p "$HOME"
  ENVDUMP="$BATS_TEST_TMPDIR/envdump"
  : >"$ENVDUMP"

  # Downstream (domyślny xstartup jrdp) — zrzuca odziedziczone środowisko i kończy (bez exec dalej).
  JRDP_XSTARTUP="$BATS_TEST_TMPDIR/jrdp-xstartup"
  cat >"$JRDP_XSTARTUP" <<EOF
#!/bin/sh
echo "JRDP XAUTHORITY=\${XAUTHORITY-UNSET}" >>"$ENVDUMP"
echo "JRDP DISPLAY=\${DISPLAY-UNSET}" >>"$ENVDUMP"
EOF
  chmod +x "$JRDP_XSTARTUP"

  # Atrapa interpretera TLJH: wypisuje ścieżkę do domyślnego xstartup jrdp (sterowana PY_PRINTS).
  PY_PRINTS="$JRDP_XSTARTUP"
  cat >"$STUBS/tljh-python" <<EOF
#!/usr/bin/env bash
echo "tljh-python \$*" >>"\$CALLS"
cat >/dev/null   # pochłoń skrypt z here-doc na stdin
printf '%s\n' "$PY_PRINTS"
EOF
  chmod +x "$STUBS/tljh-python"
  export WLB_TLJH_PYTHON="$STUBS/tljh-python"

  # Fallback, gdy jrdp niedostępny — też zrzuca środowisko.
  cat >"$STUBS/dbus-launch" <<EOF
#!/usr/bin/env bash
echo "dbus-launch \$*" >>"\$CALLS"
echo "FALLBACK XAUTHORITY=\${XAUTHORITY-UNSET}" >>"$ENVDUMP"
echo "FALLBACK DISPLAY=\${DISPLAY-UNSET}" >>"$ENVDUMP"
EOF
  chmod +x "$STUBS/dbus-launch"
}

@test "eksportuje żywy XAUTHORITY do potomka sesji (#278)" {
  run env DISPLAY=":7" XAUTHORITY="/run/live/Xauth-xyz" "$XSTARTUP"
  [ "$status" -eq 0 ]
  grep -qx "JRDP XAUTHORITY=/run/live/Xauth-xyz" "$ENVDUMP"
  grep -qx "JRDP DISPLAY=:7" "$ENVDUMP"
}

@test "puste XAUTHORITY -> fallback na \$HOME/.Xauthority, też eksportowany (#278)" {
  run env DISPLAY=":7" XAUTHORITY="" "$XSTARTUP"
  [ "$status" -eq 0 ]
  grep -qx "JRDP XAUTHORITY=$HOME/.Xauthority" "$ENVDUMP"
}

@test "nieustawiony XAUTHORITY -> fallback na \$HOME/.Xauthority (#278)" {
  run env DISPLAY=":7" "$XSTARTUP"
  [ "$status" -eq 0 ]
  grep -qx "JRDP XAUTHORITY=$HOME/.Xauthority" "$ENVDUMP"
}

@test "łańcuchuje do domyślnego xstartup jrdp gdy dostępny (#278)" {
  run env DISPLAY=":7" XAUTHORITY="/run/live/Xauth" "$XSTARTUP"
  [ "$status" -eq 0 ]
  called 'tljh-python'
  grep -q '^JRDP ' "$ENVDUMP"
  refute grep -q '^FALLBACK ' "$ENVDUMP"
}

@test "brak xstartup jrdp -> fallback dbus-launch startxfce4 z eksportem XAUTHORITY (#278)" {
  # interpreter zwraca pustą ścieżkę -> gałąź fallback
  cat >"$STUBS/tljh-python" <<EOF
#!/usr/bin/env bash
cat >/dev/null
printf '\n'
EOF
  chmod +x "$STUBS/tljh-python"

  run env DISPLAY=":7" XAUTHORITY="/run/live/Xauth" "$XSTARTUP"
  [ "$status" -eq 0 ]
  called 'dbus-launch .*startxfce4'
  grep -qx "FALLBACK XAUTHORITY=/run/live/Xauth" "$ENVDUMP"
  grep -qx "FALLBACK DISPLAY=:7" "$ENVDUMP"
}

@test "xstartup jrdp niewykonywalny/nieczytelny -> fallback (#278)" {
  PY_MISSING="$BATS_TEST_TMPDIR/nie-ma-takiego"
  cat >"$STUBS/tljh-python" <<EOF
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' "$PY_MISSING"
EOF
  chmod +x "$STUBS/tljh-python"

  run env DISPLAY=":7" XAUTHORITY="/run/live/Xauth" "$XSTARTUP"
  [ "$status" -eq 0 ]
  called 'dbus-launch .*startxfce4'
}
