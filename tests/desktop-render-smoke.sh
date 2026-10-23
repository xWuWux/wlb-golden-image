#!/usr/bin/env bash
# desktop-render-smoke.sh — render-smoke pulpitu (#138, etap 1 testów wizualnych; pulpit #106).
#
# Co robi: wstaje headless serwer X (TigerVNC) z sesją XFCE, robi zrzut ekranu (scrot) i sprawdza,
# że ekran NIE jest praktycznie pusty — pusty/czarny ma ~1-2 kolory, wyrenderowany pulpit wiele.
# To test RUNTIME (nie obecności pakietów), więc cięższy i wrażliwy na czas renderu — dlatego na
# razie samodzielny (empiryczna walidacja w #106), a NIE wpięty w bramkującą akceptację (stage 5).
#
# Wymaga pakietów roli desktop (TigerVNC, XFCE, dbus-x11, scrot) oraz Pillow z env badaczy.
# Uruchamiać JAKO badacz (nie root — XFCE pod rootem jest niewspierany), na VM wlb-memory:
#   sudo -iu <badacz> /opt/.../tests/desktop-render-smoke.sh
#
# Kody wyjścia: 0 = render OK; 1 = błąd środowiska/startu; 2 = ekran praktycznie pusty.
# Parametry (env): WLB_SMOKE_DISPLAY(:99)  WLB_SMOKE_GEOMETRY(1280x800)
#   WLB_SMOKE_SETTLE(8, sekundy na render)  WLB_SMOKE_MIN_COLORS(64)  WLB_SMOKE_KEEP_SHOT(0)
set -euo pipefail

DISPLAY_NUM="${WLB_SMOKE_DISPLAY:-:99}"
GEOMETRY="${WLB_SMOKE_GEOMETRY:-1280x800}"
SETTLE="${WLB_SMOKE_SETTLE:-8}"
MIN_COLORS="${WLB_SMOKE_MIN_COLORS:-64}"
PY=/opt/tljh/user/bin/python

say() { printf 'render-smoke: %s\n' "$*"; }
die() {
  say "FAIL — $*"
  exit "${2:-1}"
}

# --- Wymagania środowiska -------------------------------------------------------------------
[ "$(id -u)" -ne 0 ] || die "uruchom jako badacz, nie root (sesja XFCE pod rootem jest niewspierana)"
VNCSERVER="$(command -v tigervncserver || command -v vncserver || true)"
[ -n "$VNCSERVER" ] || die "brak tigervncserver/vncserver (rola desktop)"
command -v startxfce4 >/dev/null || die "brak startxfce4 (rola desktop)"
command -v dbus-launch >/dev/null || die "brak dbus-launch (pakiet dbus-x11, rola desktop)"
command -v scrot >/dev/null || die "brak scrot (rola desktop)"
[ -x "$PY" ] || die "brak Pythona env badaczy z Pillow: $PY"

SHOT="$(mktemp --suffix=.png)"
XLOG="$(mktemp)"
XSTART="$(mktemp)"

# shellcheck disable=SC2329  # wywoływana przez trap
cleanup() {
  "$VNCSERVER" -kill "$DISPLAY_NUM" >/dev/null 2>&1 || true
  if [ "${WLB_SMOKE_KEEP_SHOT:-0}" != 1 ]; then
    rm -f "$SHOT"
  fi
  rm -f "$XLOG" "$XSTART"
}
trap cleanup EXIT

# --- 1. Serwer X (prawdziwy TigerVNC) + sesja XFCE ------------------------------------------
# Wrapper tigervncserver sam ustawia Xauthority (dlatego scrot niżej się połączy) i uruchamia
# xstartup. -SecurityTypes None: serwer tylko na localhost, bez hasła — służy wyłącznie do zrzutu.
cat >"$XSTART" <<'EOF'
#!/bin/sh
exec dbus-launch --exit-with-session startxfce4
EOF
chmod +x "$XSTART"

"$VNCSERVER" "$DISPLAY_NUM" -geometry "$GEOMETRY" -depth 24 \
  -SecurityTypes None -localhost yes -xstartup "$XSTART" >"$XLOG" 2>&1 ||
  die "serwer VNC nie wstał: $(tr '\n' ' ' <"$XLOG")"

say "XFCE startuje na ${DISPLAY_NUM}, czekam ${SETTLE}s na render…"
sleep "$SETTLE"

# --- 2. Zrzut ekranu -----------------------------------------------------------------------
DISPLAY="$DISPLAY_NUM" scrot -o "$SHOT" ||
  die "scrot nie zrobił zrzutu (log: $(tr '\n' ' ' <"$XLOG"))"
[ -s "$SHOT" ] || die "zrzut pusty/zerowy: $SHOT"

# --- 3. Analiza: liczba kolorów (pusty ekran ~1-2, wyrenderowany pulpit — wiele) ------------
colors="$(
  WLB_SHOT="$SHOT" "$PY" - <<'PY'
import os
from PIL import Image

im = Image.open(os.environ["WLB_SHOT"]).convert("RGB")
c = im.getcolors(maxcolors=1_000_000)  # None, gdy kolorów > maxcolors (bardzo „bogaty” obraz)
print(1_000_001 if c is None else len(c))
PY
)" || die "analiza Pillow nie powiodła się"

say "kolorów na zrzucie: ${colors} (próg ${MIN_COLORS})"
if [ "$colors" -ge "$MIN_COLORS" ]; then
  say "PASS — pulpit renderuje się (${GEOMETRY})"
  exit 0
fi
die "ekran praktycznie pusty (${colors} < ${MIN_COLORS} kolorów) — pulpit nie wyrenderował się" 2
