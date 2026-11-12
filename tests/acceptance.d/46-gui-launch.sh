# shellcheck shell=bash
# #278: GUI-launch natywnej apki (LibreOffice Calc) w sesji pulpitu — ADAPTACYJNY, NIE-BRAMKUJĄCY.
#
# Reprodukuje realną awarię z histologia-01: domyślny xstartup jupyter-remote-desktop-proxy NIE
# eksportuje XAUTHORITY do potomków sesji, więc natywne apki GUI (LibreOffice Calc/Writer) padają
# "Authorization required, but no authorization protocol specified / Failed to open display"
# (jamovi przez Flatpak działa, bo bwrap stawia własny X11 — stąd mylące „jedno działa, drugie nie").
# Fix: /opt/wlb/desktop/wlb-desktop-xstartup eksportuje ŻYWY cookie do potomków.
#
# Test startuje REALNĄ sesję przez wrapper jrdp/TigerVNC (jak #44/#140) z naszym xstartup. Downstream
# naszego xstartup podmieniamy sondą (przez WLB_TLJH_PYTHON — mechanizm z wlb-desktop-xstartup), która:
#   (1) zrzuca ODZIEDZICZONE XAUTHORITY/DISPLAY (dowód, że sesja je wyeksportowała),
#   (2) odpala `libreoffice --calc` w tym środowisku.
# Asercje: XAUTHORITY niepuste i autoryzuje display; okno LibreOffice realnie się mapuje; log soffice
# bez "Failed to open display". Luka pokryta dotąd tylko headless (45-memory/47-histologia:
# `libreoffice --headless --convert-to`), która w ogóle nie dotyka autoryzacji X.
#
# RUNTIME = wrażliwy na czas: błąd/niejednoznaczność -> SKIP, nie ko (#86, jak #138 §8).
# Promocja do bramkowania po walidacji KVM: WLB_GUILAUNCH_GATING=1 zamienia SKIP na FAIL.
if /opt/tljh/user/bin/python -c "import jupyter_remote_desktop_proxy" 2>/dev/null &&
  [ -x /usr/bin/libreoffice ] && [ -x /opt/wlb/desktop/wlb-desktop-xstartup ]; then
  echo "== GUI-launch natywnej apki w sesji pulpitu (#278 — NIE-bramkujący) =="
  W46_GATING=${WLB_GUILAUNCH_GATING:-0}

  w46_verdict() {
    local desc=$1 rc=$2
    if [ "$rc" -eq 0 ]; then
      ok "$desc"
    elif [ "$W46_GATING" = 1 ]; then
      ko "$desc"
    else
      skip "$desc — NIE bramkuje (WLB_GUILAUNCH_GATING=1 promuje)"
    fi
  }

  W46_OK=1
  for W46_C in vncserver Xtigervnc xauth xdpyinfo xwininfo python3; do
    command -v "$W46_C" >/dev/null 2>&1 || W46_OK=0
  done
  if ! id "jupyter-$R1" >/dev/null 2>&1; then
    skip "GUI-launch #278: brak konta jupyter-$R1 (test adaptacyjny)"
  elif [ "$W46_OK" -ne 1 ]; then
    skip "GUI-launch #278: brak vncserver/Xtigervnc/xauth/xdpyinfo/xwininfo — test pominięty"
  else
    W46_TMP=$(mktemp -d /tmp/wlb-gui283.XXXXXX 2>/dev/null || true)
    if [ -z "$W46_TMP" ]; then
      skip "GUI-launch #278: nie można utworzyć katalogu tymczasowego"
    else
      chmod 755 "$W46_TMP"
      W46_HOME=$W46_TMP/home
      mkdir -m 700 "$W46_HOME"

      W46_PROBE_ENV=$W46_TMP/probe.env
      W46_PROBE_READY=$W46_TMP/probe.ready
      W46_SOFFICE_LOG=$W46_TMP/soffice.log
      : >"$W46_PROBE_ENV"
      : >"$W46_SOFFICE_LOG"

      # Sonda = downstream naszego xstartup: zrzuca odziedziczone środowisko i odpala natywną apkę GUI.
      W46_PROBE=$W46_TMP/probe-xstartup
      cat >"$W46_PROBE" <<EOF
#!/bin/sh
echo "XAUTHORITY=\${XAUTHORITY-UNSET}" >"$W46_PROBE_ENV"
echo "DISPLAY=\${DISPLAY-UNSET}" >>"$W46_PROBE_ENV"
: >"$W46_PROBE_READY"
libreoffice --calc --norestore >"$W46_SOFFICE_LOG" 2>&1 &
exec sleep 180
EOF
      chmod 755 "$W46_PROBE"

      # Atrapa interpretera TLJH dla naszego xstartup: zwraca ścieżkę sondy (zamiast domyślnego
      # xstartup jrdp), więc badamy eksport NASZEGO skryptu uruchamiając realną apkę GUI.
      W46_PYSTUB=$W46_TMP/tljh-python
      cat >"$W46_PYSTUB" <<EOF
#!/bin/sh
cat >/dev/null
printf '%s\n' "$W46_PROBE"
EOF
      chmod 755 "$W46_PYSTUB"
      chown -R "jupyter-$R1" "$W46_TMP" 2>/dev/null || true

      W46_PROXY_CMD=$(
        as "$R1" env HOME="$W46_HOME" \
          /opt/tljh/user/bin/python - <<'PY' 2>/dev/null
from jupyter_remote_desktop_proxy.setup_websockify import setup_websockify

print(setup_websockify()["command"][-1])
PY
      )

      W46_SOCK=$W46_TMP/rfb.sock
      W46_N=
      W46_VNC_JOB=
      if [ -z "$W46_PROXY_CMD" ]; then
        skip "GUI-launch #278: nie udało się pobrać komendy startowej jrdp"
      else
        W46_RUN_CMD=${W46_PROXY_CMD//\{unix_socket\}/$W46_SOCK}
        W46_VNC_LOG=$W46_TMP/vnc.log
        # Uruchamiamy NASZ xstartup; jego downstream (sondę) wskazuje WLB_TLJH_PYTHON.
        as "$R1" env HOME="$W46_HOME" \
          JUPYTER_REMOTE_DESKTOP_PROXY_XSTARTUP=/opt/wlb/desktop/wlb-desktop-xstartup \
          WLB_TLJH_PYTHON="$W46_PYSTUB" \
          bash -c "$W46_RUN_CMD" >"$W46_VNC_LOG" 2>&1 &
        W46_VNC_JOB=$!

        for _ in $(seq 1 80); do
          [ -S "$W46_SOCK" ] && break
          sleep 0.25
        done
        W46_N=$(find "$W46_HOME/.vnc" -maxdepth 1 -name '*.pid' -printf '%f\n' 2>/dev/null |
          sed -n 's/.*:\([0-9][0-9]*\)\.pid$/\1/p' | head -1)
        if [ -z "$W46_N" ]; then
          W46_N=$(as "$R1" env HOME="$W46_HOME" vncserver -list 2>/dev/null |
            awk '$1 ~ /^[0-9]+$/ {print $1; exit}')
        fi

        if [ -z "$W46_N" ] || [ ! -S "$W46_SOCK" ]; then
          skip "GUI-launch #278: sesja VNC przez proxy nie wystartowała: $(tail -n1 "$W46_VNC_LOG" 2>/dev/null)"
        else
          # Poczekaj, aż sonda zrzuci środowisko (xstartup uruchomiony).
          for _ in $(seq 1 40); do
            [ -s "$W46_PROBE_READY" ] 2>/dev/null && break
            [ -s "$W46_PROBE_ENV" ] && break
            sleep 0.25
          done

          W46_XAUTH_VAL=$(sed -n 's/^XAUTHORITY=//p' "$W46_PROBE_ENV" 2>/dev/null | head -1)

          # --- Asercja 1 (rdzeń #278): sesja wyeksportowała niepuste XAUTHORITY do potomka ---
          if [ -n "$W46_XAUTH_VAL" ] && [ "$W46_XAUTH_VAL" != "UNSET" ] &&
            as "$R1" env HOME="$W46_HOME" DISPLAY=":$W46_N" XAUTHORITY="$W46_XAUTH_VAL" \
              xdpyinfo >/dev/null 2>&1; then
            ok "Sesja pulpitu eksportuje XAUTHORITY do potomka i autoryzuje display (#278)"
          else
            w46_verdict "Potomek sesji dostał puste/niedziałające XAUTHORITY='${W46_XAUTH_VAL:-?}' (#278)" 1
          fi

          # --- Asercja 2: natywna apka GUI realnie mapuje okno (nie tylko headless) ---
          W46_WIN=0
          for _ in $(seq 1 60); do
            if as "$R1" env HOME="$W46_HOME" DISPLAY=":$W46_N" \
              XAUTHORITY="${W46_XAUTH_VAL:-$W46_HOME/.Xauthority}" \
              xwininfo -root -tree 2>/dev/null | grep -qiE 'libreoffice|soffice|calc'; then
              W46_WIN=1
              break
            fi
            # wczesne wykrycie fatalnego błędu autoryzacji X z loga soffice
            if grep -qiE 'Failed to open display|no authorization protocol' "$W46_SOFFICE_LOG" 2>/dev/null; then
              break
            fi
            sleep 1
          done

          if [ "$W46_WIN" -eq 1 ]; then
            ok "LibreOffice Calc mapuje okno w sesji pulpitu (GUI-launch, #278)"
          elif grep -qiE 'Failed to open display|no authorization protocol' "$W46_SOFFICE_LOG" 2>/dev/null; then
            w46_verdict "LibreOffice nie otworzył display w sesji: $(grep -iE 'Failed to open display|no authorization' "$W46_SOFFICE_LOG" | head -1) (#278)" 1
          else
            skip "GUI-launch #278: okno LibreOffice nie zmapowało się w czasie (wynik niejednoznaczny, nie bramkuje)"
          fi
        fi
      fi

      # Sprzątanie: apka GUI, sesja VNC, procesy-widma, locki, katalog.
      as "$R1" pkill -u "jupyter-$R1" -f 'soffice' >/dev/null 2>&1 || true
      if [ -n "${W46_N:-}" ]; then
        as "$R1" env HOME="$W46_HOME" vncserver -kill ":$W46_N" >/dev/null 2>&1 || true
        W46_XP=$(pgrep -u "jupyter-$R1" -f "Xtigervnc :$W46_N( |$)" 2>/dev/null | head -1 || true)
        [ -n "$W46_XP" ] && kill "$W46_XP" 2>/dev/null || true
      fi
      if [ -n "${W46_VNC_JOB:-}" ]; then
        kill "$W46_VNC_JOB" 2>/dev/null || true
        wait "$W46_VNC_JOB" 2>/dev/null || true
      fi
      sleep 0.5
      [ -n "${W46_N:-}" ] && rm -f "/tmp/.X$W46_N-lock" "/tmp/.X11-unix/X$W46_N" 2>/dev/null || true
      rm -rf "$W46_TMP"
    fi
  fi
fi
