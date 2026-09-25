# shellcheck shell=bash disable=SC2034  # zmienne używane w plikach .bats
# Wspólne funkcje testów bats: piaskownica WLB_ROOT i atrapy poleceń systemowych.
# Każde wywołanie atrapy jest dopisywane do $CALLS, żeby test mógł sprawdzić, co skrypt zrobił.

REPO_ROOT="$(cd "$(dirname "${BATS_TEST_FILENAME}")/../.." && pwd)"
FIRSTBOOT="$REPO_ROOT/ansible/roles/lab_config/files/wlb-firstboot"
MOVER="$REPO_ROOT/ansible/roles/storage/files/wlb-sluza-out-mover"

setup_sandbox() {
  SANDBOX="$BATS_TEST_TMPDIR/root"
  STUBS="$BATS_TEST_TMPDIR/stubs"
  CALLS="$BATS_TEST_TMPDIR/calls.log"
  mkdir -p "$SANDBOX/etc/wlb" "$STUBS"
  : >"$CALLS"
  export WLB_ROOT="$SANDBOX" CALLS PATH="$STUBS:$PATH"
}

# stub NAZWA [KOD_WYJŚCIA] [STDOUT] — atrapa polecenia zapisująca swoje argumenty
stub() {
  local name=$1 code=${2:-0}
  # wyjście w osobnym pliku — dowolna treść (wiele linii, cudzysłowy) bez cytowania w skrypcie
  if [[ -n ${3:-} ]]; then printf '%s\n' "$3" >"$STUBS/$name.out"; else rm -f "$STUBS/$name.out"; fi
  cat >"$STUBS/$name" <<EOF
#!/usr/bin/env bash
echo "$name \$*" >>"\$CALLS"
[[ -f "$STUBS/$name.out" ]] && cat "$STUBS/$name.out"
exit $code
EOF
  chmod +x "$STUBS/$name"
}

calls() { cat "$CALLS"; }

# called [opcje grep] WZORZEC — czy atrapa została wywołana z takimi argumentami
called() { grep -q "$@" -- "$CALLS"; }

# refute POLECENIE... — asercja negatywna. W bats samo "! polecenie" w środku testu
# nie powoduje niepowodzenia (SC2314), funkcja zwracająca 1 — tak.
refute() {
  if "$@"; then
    echo "oczekiwano niepowodzenia: $*" >&2
    return 1
  fi
}
