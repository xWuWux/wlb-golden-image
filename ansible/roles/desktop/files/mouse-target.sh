#!/usr/bin/env bash
# /opt/wlb/e2e/mouse-target.sh — in-session mouse target dla testów E2E (#277).
#
# Uruchamia dialog zenity --question na deterministycznej pozycji i rozmiarze,
# publikuje deskryptor /run/wlb/e2e/target.json zgodny ze schematem wlb.e2e-target/v1,
# a po kliknięciu przycisku OK zapisuje kod wyniku do /run/wlb/e2e/mouse.txt (rc=0).
#
# jupyter-remote-desktop-proxy ustawia rfb.resizeSession=true, więc framebuffer X zmienia
# rozmiar razem z oknem przeglądarki. Dlatego geometria (ekran + okno) jest liczona funkcjami
# wołanymi TAKŻE w pętli monitorującej — po resize/reconnect target.json dostaje świeże
# screen/button, a nie tylko „plik istnieje" (#277, review #325/#277-B).
#
# Parametry środowiskowe (przydatne m.in. w testach jednostkowych):
#   WLB_E2E_MARKER_DIR        ścieżka do katalogu markerów (domyślnie: /run/wlb/e2e)
#   WLB_E2E_SESSION_FILE      ścieżka do trwałego identyfikatora sesji
#   WLB_E2E_SCREEN_GEOMETRY   wymuszona rozdzielczość ekranu WxH (np. 1024x768)
set -euo pipefail

MARKER_DIR="${WLB_E2E_MARKER_DIR:-/run/wlb/e2e}"
TARGET_FILE="$MARKER_DIR/target.json"
MOUSE_FILE="$MARKER_DIR/mouse.txt"

# Stałe rozmiary okna i przycisku
WIN_W=360
WIN_H=180
BTN_W=80
BTN_H=34
WINDOW_TITLE="E2E Mouse Target"

# Wypełniane w trakcie działania (deklaracje dla set -u)
WID=""
SESSION_ID=""
SCREEN_W=""
SCREEN_H=""
WIN_X=0
WIN_Y=0
BTN_X=0
BTN_Y=0

# session_init — trwały identyfikator sesji X (przetrwa czyszczenie /run/wlb/e2e/* przez test)
session_init() {
	local session_file
	session_file="${WLB_E2E_SESSION_FILE:-/tmp/.wlb-e2e-session-id-${USER:-badacz}-${DISPLAY:-0}}"
	if [ -f "$session_file" ] && [ -s "$session_file" ]; then
		SESSION_ID=$(head -n 1 "$session_file")
	else
		SESSION_ID=$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "wlb-e2e-$$")
		printf "%s\n" "$SESSION_ID" >"$session_file" 2>/dev/null || true
	fi
}

# read_screen — ustawia SCREEN_W/SCREEN_H (framebuffer VNC/X). Wołane też w pętli: po
# rfb.resizeSession ekran X zmienia rozmiar i deskryptor musi to odzwierciedlić.
read_screen() {
	SCREEN_W=""
	SCREEN_H=""
	if [ -n "${WLB_E2E_SCREEN_GEOMETRY:-}" ]; then
		SCREEN_W="${WLB_E2E_SCREEN_GEOMETRY%x*}"
		SCREEN_H="${WLB_E2E_SCREEN_GEOMETRY#*x}"
	fi
	if [ -z "$SCREEN_W" ] || [ -z "$SCREEN_H" ]; then
		if command -v xdpyinfo >/dev/null 2>&1; then
			local dims
			dims=$(xdpyinfo 2>/dev/null | awk '/dimensions:/ {print $2}')
			if [ -n "$dims" ]; then
				SCREEN_W="${dims%x*}"
				SCREEN_H="${dims#*x}"
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
}

# read_window — ustawia WIN_X/Y/W/H z rzeczywistego okna po WM (po resize WM może je przesunąć/
# przyciąć); fallback: wyśrodkowanie względem BIEŻĄCEGO ekranu. Wymaga WID.
read_window() {
	WIN_X=$(((SCREEN_W - WIN_W) / 2))
	WIN_Y=$(((SCREEN_H - WIN_H) / 2))
	[ -n "$WID" ] || return 0
	command -v xwininfo >/dev/null 2>&1 || return 0
	local info ax ay aw ah
	info=$(xwininfo -id "$WID" 2>/dev/null) || return 0
	[ -n "$info" ] || return 0
	ax=$(awk -F: '/Absolute upper-left X/ {gsub(/ /, "", $2); print $2}' <<<"$info")
	ay=$(awk -F: '/Absolute upper-left Y/ {gsub(/ /, "", $2); print $2}' <<<"$info")
	aw=$(awk -F: '/^[[:space:]]*Width:/ {gsub(/ /, "", $2); print $2}' <<<"$info")
	ah=$(awk -F: '/^[[:space:]]*Height:/ {gsub(/ /, "", $2); print $2}' <<<"$info")
	if [ -n "$ax" ]; then WIN_X="$ax"; fi
	if [ -n "$ay" ]; then WIN_Y="$ay"; fi
	if [ -n "$aw" ]; then WIN_W="$aw"; fi
	if [ -n "$ah" ]; then WIN_H="$ah"; fi
}

# compute_button — pozycja przycisku OK w pikselach bufora z geometrii okna
compute_button() {
	BTN_X=$((WIN_X + WIN_W - BTN_W - 16))
	BTN_Y=$((WIN_Y + WIN_H - BTN_H - 14))
}

# geom_sig — podpis bieżącej geometrii; zmiana = trzeba przepisać target.json
geom_sig() {
	printf '%s:%s:%s:%s:%s:%s' "$SCREEN_W" "$SCREEN_H" "$WIN_X" "$WIN_Y" "$WIN_W" "$WIN_H"
}

# write_target_json — publikuje deskryptor atomowo (tmp + mv)
write_target_json() {
	cat >"${TARGET_FILE}.tmp" <<EOF
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

main() {
	mkdir -p "$MARKER_DIR" 2>/dev/null || true
	session_init
	read_screen
	WIN_X=$(((SCREEN_W - WIN_W) / 2))
	WIN_Y=$(((SCREEN_H - WIN_H) / 2))

	# Uruchomienie zenity w tle
	local rc=0
	zenity --question \
		--title="$WINDOW_TITLE" \
		--text="Kliknij 'OK', aby potwierdzić interakcję myszą (test E2E)." \
		--ok-label="OK" \
		--cancel-label="Anuluj" \
		--width="$WIN_W" \
		--height="$WIN_H" \
		--no-wrap &
	local zenity_pid=$!

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

	read_window
	compute_button
	write_target_json

	# Pętla w tle: utrzymuje target.json aktualny — odtwarza po wyczyszczeniu /run/wlb/e2e/*
	# ORAZ przepisuje po ZMIANIE GEOMETRII ekranu/okna (resize/reconnect, rfb.resizeSession).
	(
		prev=$(geom_sig)
		while kill -0 "$zenity_pid" 2>/dev/null; do
			read_screen
			read_window || true
			compute_button
			cur=$(geom_sig)
			if [ "$cur" != "$prev" ] || [ ! -f "$TARGET_FILE" ]; then
				write_target_json 2>/dev/null || true
				prev="$cur"
			fi
			sleep 0.2
		done
	) &
	local monitor_pid=$!

	# Czekaj na zakończenie zenity (kliknięcie lub timeout)
	wait "$zenity_pid" || rc=$?

	# Zapisz wynik kliknięcia do mouse.txt
	printf "rc=%d\n" "$rc" >"$MOUSE_FILE"

	# Zatrzymaj pętlę monitorującą
	kill "$monitor_pid" 2>/dev/null || true
	wait "$monitor_pid" 2>/dev/null || true

	# Upewnij się, że target.json nadal istnieje po kliknięciu
	if [ ! -f "$TARGET_FILE" ]; then
		write_target_json 2>/dev/null || true
	fi

	# Propaguj wynik kliknięcia jako kod wyjścia skryptu (OK=0, Anuluj/timeout!=0)
	return "$rc"
}

# emit_target_once — tryb testowy/diagnostyczny: policz geometrię i zapisz target.json RAZ,
# bez zenity i bez pętli. Wołany jako PODPROCES (nie sourcowany), więc działa pod kcov —
# sourcowanie instrumentowanego skryptu pod set -u wywraca BASH_SOURCE w trapie kcov.
emit_target_once() {
	mkdir -p "$MARKER_DIR" 2>/dev/null || true
	session_init
	read_screen
	read_window
	compute_button
	write_target_json
}

# Uruchomienie bezpośrednie (nie sourcowanie): --emit-target do testów, inaczej pełny main.
# WLB_E2E_SOURCE_ONLY=1 blokuje oba i — dzięki short-circuit — NIE dotyka BASH_SOURCE;
# forma ${BASH_SOURCE+...} jest bezpieczna pod set -u nawet dla nieustawionej tablicy.
if [ "${WLB_E2E_SOURCE_ONLY:-0}" != 1 ] && [ "${BASH_SOURCE+${BASH_SOURCE[0]}}" = "${0:-}" ]; then
	case "${1:-}" in
	--emit-target) emit_target_once ;;
	*) main "$@" ;;
	esac
fi
