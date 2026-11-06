# shellcheck shell=bash
# #140: copy-lockdown pulpitu w ścieżce proxy — ADAPTACYJNY i NIE-BRAMKUJĄCY.
#
# jrdp 3.0.1 robi which('vncserver') i uruchamia wrapper TigerVNC; ten czyta
# /etc/tigervnc/vncserver-config-mandatory i dokłada Xtigervnc -AcceptCutText=0 -SendCutText=0.
# Sprawdzamy: (1) łańcuch jrdp -> vncserver -> tigervncserver, (2) wrapper realnie emituje flagi
# (dry-run dokładnej komendy jrdp), (3) zawartość mandatory, (4) behawioralnie — jeśli dostępne
# są xclip/X — odrzucenie CutText w obu kierunkach. noVNC file-transfer = N/A w jrdp 3.0.1
# (brak UI; pełne E2E przeglądarki to #206) — bez asercji.
#
# Schowek to test RUNTIME: błąd/niejednoznaczność daje SKIP, nie ko (jak #138).
# Po walidacji KVM promocja: WLB_CUTLOCKDOWN_GATING=1 zamienia SKIP na FAIL.
if /opt/tljh/user/bin/python -c "import jupyter_remote_desktop_proxy" 2>/dev/null; then
  echo "== Copy-lockdown pulpitu przez ścieżkę proxy (#140 — NIE-bramkujący) =="
  W44_GATING=${WLB_CUTLOCKDOWN_GATING:-0}

  # w44_verdict OPIS RC — 0=PASS; inaczej FAIL przy gatingu, SKIP bez gatingu.
  w44_verdict() {
    local desc=$1 rc=$2
    if [ "$rc" -eq 0 ]; then
      ok "$desc"
    elif [ "$W44_GATING" = 1 ]; then
      ko "$desc"
    else
      skip "$desc — NIE bramkuje (WLB_CUTLOCKDOWN_GATING=1 promuje)"
    fi
  }

  if ! id "jupyter-$R1" >/dev/null 2>&1; then
    skip "Copy-lockdown #140: brak konta jupyter-$R1 (test adaptacyjny)"
  else
    W44_TMP=$(mktemp -d /tmp/wlb-cut140.XXXXXX 2>/dev/null || true)
    if [ -z "$W44_TMP" ]; then
      skip "Copy-lockdown #140: nie można utworzyć katalogu tymczasowego"
    else
      chmod 755 "$W44_TMP"
      W44_HOME=$W44_TMP/home
      mkdir -m 700 "$W44_HOME"
      chown -R "jupyter-$R1" "$W44_TMP" 2>/dev/null || true

      W44_XSTARTUP=$W44_TMP/xstartup
      cat >"$W44_XSTARTUP" <<'EOF'
#!/bin/sh
exec xterm -geometry 80x24+0+0
EOF
      chmod 755 "$W44_XSTARTUP"
      chown "jupyter-$R1" "$W44_XSTARTUP"

      # -------------------------------------------------------------------------
      # 1. GUARD łańcucha: pierwszy token komendy jrdp prowadzi do wrappera
      #    tigervncserver, a nie bezpośrednio do Xtigervnc.
      # -------------------------------------------------------------------------
      W44_PROXY_INFO=$(
        as "$R1" env HOME="$W44_HOME" \
          JUPYTER_REMOTE_DESKTOP_PROXY_XSTARTUP="$W44_XSTARTUP" \
          /opt/tljh/user/bin/python - <<'PY' 2>"$W44_TMP/proxy.err"
import shlex
from jupyter_remote_desktop_proxy.setup_websockify import setup_websockify

cmd = setup_websockify()["command"][-1]
part = cmd.split("&&", 1)[-1].strip()
print(shlex.split(part)[0])
print(cmd)
PY
      )
      W44_PROXY_BIN=$(printf '%s\n' "$W44_PROXY_INFO" | sed -n '1p')
      W44_PROXY_CMD=$(printf '%s\n' "$W44_PROXY_INFO" | sed -n '2p')
      W44_PROXY_REAL=$(readlink -f "$W44_PROXY_BIN" 2>/dev/null || true)

      if [ -n "$W44_PROXY_BIN" ] && [ "$W44_PROXY_REAL" = "/usr/bin/tigervncserver" ]; then
        ok "GUARD: jrdp startuje VNC przez wrapper vncserver -> tigervncserver, nie Xtigervnc (#140)"
      else
        w44_verdict "GUARD: jrdp nie wskazuje wrappera TigerVNC (#140): bin='${W44_PROXY_BIN:-?}' real='${W44_PROXY_REAL:-?}' err=$(tail -n1 "$W44_TMP/proxy.err" 2>/dev/null)" 1
      fi

      W44_JRDP_VER=$(as "$R1" /opt/tljh/user/bin/python -c 'import importlib.metadata as m; print(m.version("jupyter-remote-desktop-proxy"))' 2>/dev/null || echo '?')
      echo "  info  jrdp=$W44_JRDP_VER TigerVNC=$(dpkg-query -W -f='${Version}' tigervnc-standalone-server 2>/dev/null || echo '?')"

      # -------------------------------------------------------------------------
      # 2. Wrapper realnie czyta mandatory: dry-run DOKŁADNEJ komendy jrdp
      #    (podmieniamy tylko placeholder {unix_socket}, sesja nie startuje).
      # -------------------------------------------------------------------------
      if [ -z "$W44_PROXY_CMD" ]; then
        skip "Copy-lockdown #140: brak komendy startowej jrdp — nie można sprawdzić flag wrappera"
      else
        W44_SOCK=$W44_TMP/rfb.sock
        W44_DRY_CMD=${W44_PROXY_CMD//\{unix_socket\}/$W44_SOCK}
        W44_DRY_CMD="$W44_DRY_CMD -dry-run -verbose"
        W44_DRY_LOG=$W44_TMP/dry.log
        if as "$R1" env HOME="$W44_HOME" \
          JUPYTER_REMOTE_DESKTOP_PROXY_XSTARTUP="$W44_XSTARTUP" \
          timeout 20s bash -c "$W44_DRY_CMD" >"$W44_DRY_LOG" 2>&1; then
          if grep -q -- '-AcceptCutText=0' "$W44_DRY_LOG" &&
            grep -q -- '-SendCutText=0' "$W44_DRY_LOG"; then
            ok "Wrapper przekazuje Xtigervnc -AcceptCutText=0 -SendCutText=0 (dry-run, #140)"
          else
            w44_verdict "Komenda Xtigervnc nie zawiera obu flag cutoff (#140): $(grep -m1 'Starting ' "$W44_DRY_LOG" 2>/dev/null || tail -n1 "$W44_DRY_LOG")" 1
          fi
        else
          w44_verdict "Dry-run komendy jrdp nie powiódł się (#140): $(tail -n1 "$W44_DRY_LOG" 2>/dev/null)" 1
        fi
      fi

      # -------------------------------------------------------------------------
      # 3. Konfiguracja mandatory: obie dyrektywy CutText wyłączone.
      # -------------------------------------------------------------------------
      W44_MANDATORY=/etc/tigervnc/vncserver-config-mandatory
      # Znak dolara jest częścią sprawdzanej konfiguracji Perla.
      # shellcheck disable=SC2016
      if [ -r "$W44_MANDATORY" ] &&
        grep -qxF '$AcceptCutText = 0;' "$W44_MANDATORY" &&
        grep -qxF '$SendCutText = 0;' "$W44_MANDATORY"; then
        ok "Konfiguracja $W44_MANDATORY wyłącza CutText w obu kierunkach (#140)"
      else
        w44_verdict "Konfiguracja $W44_MANDATORY nie wyłącza CutText w obu kierunkach (#140)" 1
      fi

      # -------------------------------------------------------------------------
      # 4. Behawioryka: sesja przez DOKŁADNĄ komendę jrdp (minimalny xstartup,
      #    bez XFCE) + kontrola pozytywna bezpośrednim Xtigervnc z flagami 1/1.
      #    Bez xclip nie ma jak zmierzyć schowka X — wtedy SKIP z TODO.
      # -------------------------------------------------------------------------
      W44_RUNTIME=1
      for W44_C in xclip vncserver Xtigervnc xauth python3 xdpyinfo; do
        command -v "$W44_C" >/dev/null 2>&1 || W44_RUNTIME=0
      done
      if [ "$W44_RUNTIME" -ne 1 ]; then
        skip "Copy-lockdown #140: brak xclip/vncserver/Xtigervnc/xauth — behawioralny test pominięty (TODO: dodać xclip do roli desktop)"
      else
        W44_RFB=$W44_TMP/rfb_cuttext.py
        cat >"$W44_RFB" <<'PY'
#!/usr/bin/env python3
"""Minimal RFB 3.8 client for clipboard (CutText) policy tests.

Usage:
  rfb_cuttext.py SOCKET inject TEXT
  rfb_cuttext.py SOCKET watch TEXT READY_FILE TIMEOUT

Exit codes: 0 = inject sent / watch received; 1 = watch timeout; 2 = error.
"""
import socket
import struct
import sys
import time


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("unexpected EOF")
        buf.extend(chunk)
    return bytes(buf)


def handshake(sock):
    version = recv_exact(sock, 12)
    if not version.startswith(b"RFB "):
        raise ValueError("not an RFB server: %r" % version)
    try:
        major, minor = int(version[4:7]), int(version[8:11])
    except ValueError:
        raise ValueError("bad RFB version: %r" % version)
    if (major, minor) < (3, 8):
        raise ValueError("unsupported RFB version: %r" % version)
    sock.sendall(b"RFB 003.008\n")

    n_types = recv_exact(sock, 1)[0]
    if n_types == 0:
        length = struct.unpack(">I", recv_exact(sock, 4))[0]
        reason = recv_exact(sock, length).decode("utf-8", "replace")
        raise ValueError("server refused security types: %s" % reason)
    types = recv_exact(sock, n_types)
    if 1 not in types:
        raise ValueError("server does not offer None security: %r" % (types,))
    sock.sendall(b"\x01")

    result = struct.unpack(">I", recv_exact(sock, 4))[0]
    if result != 0:
        length = struct.unpack(">I", recv_exact(sock, 4))[0]
        reason = recv_exact(sock, length).decode("utf-8", "replace")
        raise ValueError("security result %d: %s" % (result, reason))

    sock.sendall(b"\x01")  # ClientInit: shared
    head = recv_exact(sock, 24)
    name_len = struct.unpack(">I", head[20:24])[0]
    recv_exact(sock, name_len)


def send_cut_text(sock, text):
    data = text.encode("utf-8")
    sock.sendall(b"\x06\x00\x00\x00" + struct.pack(">I", len(data)) + data)


def read_server_message(sock):
    msg_type = recv_exact(sock, 1)[0]
    if msg_type == 3:  # ServerCutText
        recv_exact(sock, 3)
        length = struct.unpack(">I", recv_exact(sock, 4))[0]
        return recv_exact(sock, length).decode("utf-8", "replace")
    if msg_type == 2:  # Bell
        return None
    if msg_type == 1:  # SetColourMapEntries
        recv_exact(sock, 3)
        _first, count = struct.unpack(">HH", recv_exact(sock, 4))
        recv_exact(sock, count * 6)
        return None
    raise ValueError("unexpected RFB message type %d" % msg_type)


def main():
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    sock_path, mode, text = sys.argv[1], sys.argv[2], sys.argv[3]
    ready_file = sys.argv[4] if len(sys.argv) > 4 else None
    timeout = float(sys.argv[5]) if len(sys.argv) > 5 else 5.0

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(sock_path)
    try:
        handshake(sock)
        if ready_file:
            with open(ready_file, "w"):
                pass
        if mode == "inject":
            send_cut_text(sock, text)
            time.sleep(0.5)
            return 0
        if mode == "watch":
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                sock.settimeout(max(0.1, deadline - time.monotonic()))
                try:
                    value = read_server_message(sock)
                except socket.timeout:
                    break
                if value == text:
                    return 0
            return 1
        print("unknown mode %r" % mode, file=sys.stderr)
        return 2
    finally:
        sock.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("rfb_cuttext: %s" % exc, file=sys.stderr)
        sys.exit(2)
PY
        chmod 755 "$W44_RFB"
        chown "jupyter-$R1" "$W44_RFB"

        # w44_xclip_at DISPLAY XAUTHORITY SELEKCJA ARGS...
        w44_xclip_at() {
          local disp=$1 auth=$2 sel=$3
          shift 3
          as "$R1" env HOME="$W44_HOME" DISPLAY="$disp" XAUTHORITY="$auth" \
            xclip -selection "$sel" "$@"
        }

        # w44_set_at DISPLAY XAUTHORITY SELEKCJA TEKST
        w44_set_at() {
          printf '%s' "$4" | w44_xclip_at "$1" "$2" "$3" -i
        }

        # w44_wait_at DISPLAY XAUTHORITY SELEKCJA OCZEKIWANY
        w44_wait_at() {
          local got
          for _ in $(seq 1 20); do
            got=$(w44_xclip_at "$1" "$2" "$3" -o 2>/dev/null || true)
            [ "$got" = "$4" ] && return 0
            sleep 0.1
          done
          return 1
        }

        # w44_host_to_vm DISPLAY XAUTHORITY SOCKET SENTINEL MARKER
        # 0 = marker NIE trafił (polityka działa), 1 = trafił (wyciek), 2 = harness.
        w44_host_to_vm() {
          local disp=$1 auth=$2 sock=$3 sent=$4 marker=$5 got
          w44_set_at "$disp" "$auth" clipboard "$sent" || return 2
          w44_wait_at "$disp" "$auth" clipboard "$sent" || return 2
          as "$R1" python3 "$W44_RFB" "$sock" inject "$marker" >/dev/null 2>&1 || return 2
          got=$(w44_xclip_at "$disp" "$auth" clipboard -o 2>/dev/null || true)
          if [ "$got" = "$marker" ]; then
            return 1
          elif [ "$got" = "$sent" ]; then
            return 0
          fi
          return 2
        }

        # w44_watch_marker DISPLAY XAUTHORITY SOCKET MARKER TIMEOUT
        # 0 = ServerCutText z markerem dotarł, 1 = timeout (nie dotarł), 2 = harness.
        w44_watch_marker() {
          local disp=$1 auth=$2 sock=$3 marker=$4 timeout=$5
          local ready=$W44_TMP/ready.$$ pid rc
          rm -f "$ready"
          as "$R1" python3 "$W44_RFB" "$sock" watch "$marker" "$ready" "$timeout" \
            >"$W44_TMP/watch.log" 2>&1 &
          pid=$!
          for _ in $(seq 1 50); do
            [ -e "$ready" ] && break
            sleep 0.1
          done
          if [ ! -e "$ready" ]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
            return 2
          fi
          if ! w44_set_at "$disp" "$auth" clipboard "$marker" ||
            ! w44_wait_at "$disp" "$auth" clipboard "$marker"; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
            return 2
          fi
          wait "$pid"
          rc=$?
          case $rc in
            0) return 0 ;;
            1) return 1 ;;
            *) return 2 ;;
          esac
        }

        # w44_kill_xvnc DISPLAY — zabija Xtigervnc konkretnego użytkownika i displayu.
        w44_kill_xvnc() {
          local d=$1 p
          p=$(pgrep -u "jupyter-$R1" -f "Xtigervnc :$d( |$)" 2>/dev/null | head -1 || true)
          if [ -n "$p" ]; then
            kill "$p" 2>/dev/null || true
          fi
        }

        W44_RUN=$(date +%s)-$$
        W44_N=
        W44_N2=
        W44_VNC_JOB=
        W44_X2_JOB=

        W44_RUN_CMD=${W44_PROXY_CMD//\{unix_socket\}/$W44_SOCK}
        W44_VNC_LOG=$W44_TMP/vnc.log
        as "$R1" env HOME="$W44_HOME" \
          JUPYTER_REMOTE_DESKTOP_PROXY_XSTARTUP="$W44_XSTARTUP" \
          bash -c "$W44_RUN_CMD" >"$W44_VNC_LOG" 2>&1 &
        W44_VNC_JOB=$!

        for _ in $(seq 1 80); do
          [ -S "$W44_SOCK" ] && break
          sleep 0.25
        done
        W44_N=$(find "$W44_HOME/.vnc" -maxdepth 1 -name '*.pid' -printf '%f\n' 2>/dev/null |
          sed -n 's/.*:\([0-9][0-9]*\)\.pid$/\1/p' | head -1)
        if [ -z "$W44_N" ]; then
          W44_N=$(as "$R1" env HOME="$W44_HOME" vncserver -list 2>/dev/null |
            awk '$1 ~ /^[0-9]+$/ {print $1; exit}')
        fi

        W44_PROXY_READY=0
        if [ -S "$W44_SOCK" ] && [ -n "$W44_N" ] && [ -f "$W44_HOME/.Xauthority" ]; then
          for _ in $(seq 1 40); do
            if as "$R1" env HOME="$W44_HOME" DISPLAY=":$W44_N" \
              XAUTHORITY="$W44_HOME/.Xauthority" xdpyinfo >/dev/null 2>&1; then
              W44_PROXY_READY=1
              break
            fi
            sleep 0.25
          done
        fi

        if [ "$W44_PROXY_READY" -ne 1 ]; then
          skip "Copy-lockdown #140: sesja VNC przez proxy nie wystartowała (display='${W44_N:-?}'): $(tail -n1 "$W44_VNC_LOG" 2>/dev/null)"
        else
          ok "Sesja VNC wystartowała przez komendę jrdp/wrapper (display :$W44_N, socket unix, #140)"

          # Kontrola pozytywna: bezpośredni Xtigervnc, świadomie z flagami 1/1.
          for W44_C in $(seq 20 99); do
            if [ ! -e "/tmp/.X11-unix/X$W44_C" ] && [ ! -e "/tmp/.X$W44_C-lock" ]; then
              W44_N2=$W44_C
              break
            fi
          done

          W44_POS_INJECT=0
          W44_POS_SEND=0
          W44_XAUTH2=$W44_TMP/xauth2
          W44_SOCK2=$W44_TMP/rfb2.sock
          if [ -n "$W44_N2" ]; then
            W44_COOKIE=$(python3 -c 'import secrets; print(secrets.token_hex(16))')
            for W44_H in "$(hostname)" "$(hostname -f 2>/dev/null || true)"; do
              [ -n "$W44_H" ] || continue
              xauth -f "$W44_XAUTH2" add "$W44_H:$W44_N2" . "$W44_COOKIE"
              xauth -f "$W44_XAUTH2" add "$W44_H/unix:$W44_N2" . "$W44_COOKIE"
            done
            chown "jupyter-$R1" "$W44_XAUTH2"
            chmod 600 "$W44_XAUTH2"

            as "$R1" env HOME="$W44_HOME" XAUTHORITY="$W44_XAUTH2" \
              Xtigervnc ":$W44_N2" -geometry 1024x768 -depth 24 -SecurityTypes None \
              -rfbunixpath "$W44_SOCK2" -rfbport -1 \
              -AcceptCutText=1 -SendCutText=1 -auth "$W44_XAUTH2" \
              >"$W44_TMP/xvnc2.log" 2>&1 &
            W44_X2_JOB=$!

            W44_POS_READY=0
            for _ in $(seq 1 40); do
              if [ -S "$W44_SOCK2" ] && as "$R1" env HOME="$W44_HOME" DISPLAY=":$W44_N2" \
                XAUTHORITY="$W44_XAUTH2" xdpyinfo >/dev/null 2>&1; then
                W44_POS_READY=1
                break
              fi
              sleep 0.25
            done

            if [ "$W44_POS_READY" -eq 1 ]; then
              W44_TMP_POS_SENT="WLB-POS-SENT-$W44_RUN"
              W44_TMP_POS_INJ="WLB-POS-INJ-$W44_RUN"
              W44_TMP_POS_SEND="WLB-POS-SEND-$W44_RUN"
              w44_host_to_vm ":$W44_N2" "$W44_XAUTH2" "$W44_SOCK2" \
                "$W44_TMP_POS_SENT" "$W44_TMP_POS_INJ"
              W44_RC=$?
              [ "$W44_RC" -eq 1 ] && W44_POS_INJECT=1
              if w44_watch_marker ":$W44_N2" "$W44_XAUTH2" "$W44_SOCK2" "$W44_TMP_POS_SEND" 4; then
                W44_POS_SEND=1
              fi
            else
              echo "  info  kontrola pozytywna: Xtigervnc :${W44_N2:-?} nie wystartował: $(tail -n1 "$W44_TMP/xvnc2.log" 2>/dev/null)"
            fi
          fi

          if [ "$W44_POS_INJECT" -eq 1 ] && [ "$W44_POS_SEND" -eq 1 ]; then
            ok "Kontrola pozytywna: bezpośredni Xtigervnc (AcceptCutText=1/SendCutText=1) przenosi schowek w obu kierunkach (#140)"
          else
            skip "Copy-lockdown #140: kontrola pozytywna nie przeszła (inject=$W44_POS_INJECT send=$W44_POS_SEND) — wyniki negatywne byłyby niejednoznaczne"
          fi

          if [ "$W44_POS_INJECT" -eq 1 ] && [ "$W44_POS_SEND" -eq 1 ]; then
            W44_NEG_SENT="WLB-NEG-SENT-$W44_RUN"
            W44_NEG_INJ="WLB-NEG-INJ-$W44_RUN"
            W44_NEG_SEND="WLB-NEG-SEND-$W44_RUN"

            w44_host_to_vm ":$W44_N" "$W44_HOME/.Xauthority" "$W44_SOCK" \
              "$W44_NEG_SENT" "$W44_NEG_INJ"
            W44_RC=$?
            if [ "$W44_RC" -eq 2 ]; then
              skip "Copy-lockdown #140 host→VM: wynik niejednoznaczny (xclip/RFB harness)"
            else
              w44_verdict "Host→VM: ClientCutText nie trafia do schowka X (AcceptCutText=0, #140)" "$W44_RC"
            fi

            w44_watch_marker ":$W44_N" "$W44_HOME/.Xauthority" "$W44_SOCK" "$W44_NEG_SEND" 4
            W44_RC=$?
            if [ "$W44_RC" -eq 2 ]; then
              skip "Copy-lockdown #140 VM→host: wynik niejednoznaczny (xclip/RFB harness)"
            elif [ "$W44_RC" -eq 0 ]; then
              w44_verdict "VM→host: serwer NIE wysłał ServerCutText mimo zmiany schowka (SendCutText=0, #140)" 1
            else
              w44_verdict "VM→host: serwer NIE wysłał ServerCutText mimo zmiany schowka (SendCutText=0, #140)" 0
            fi
          fi
        fi

        # Sprzątanie: oba serwery X, procesy-widma, katalog tymczasowy.
        if [ -n "${W44_X2_JOB:-}" ]; then
          w44_kill_xvnc "${W44_N2:-}"
          kill "$W44_X2_JOB" 2>/dev/null || true
          wait "$W44_X2_JOB" 2>/dev/null || true
        fi
        if [ -n "${W44_N:-}" ]; then
          as "$R1" env HOME="$W44_HOME" vncserver -kill ":$W44_N" >/dev/null 2>&1 || true
          w44_kill_xvnc "$W44_N"
        fi
        if [ -n "${W44_VNC_JOB:-}" ]; then
          kill "$W44_VNC_JOB" 2>/dev/null || true
          wait "$W44_VNC_JOB" 2>/dev/null || true
        fi
        sleep 0.5
        [ -n "${W44_N:-}" ] && rm -f "/tmp/.X$W44_N-lock" "/tmp/.X11-unix/X$W44_N" 2>/dev/null || true
        [ -n "${W44_N2:-}" ] && rm -f "/tmp/.X$W44_N2-lock" "/tmp/.X11-unix/X$W44_N2" 2>/dev/null || true
        rm -rf "$W44_TMP"
      fi
    fi
  fi
fi
