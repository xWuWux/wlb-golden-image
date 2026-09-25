# shellcheck shell=bash
# Wspólne funkcje skryptów testowych uruchamianych na hoście (VM testowa z tests/run-local.sh).

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
T="$ROOT/build/test"
SSH=(ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
  -i "$T/id_ed25519" -p "${SSH_PORT:-2222}" wlbadmin@127.0.0.1)

# remote_run SKRYPT [ARG...] — wykonuje skrypt w VM jako root, z funkcjami z remote-common.sh
remote_run() {
  local script=$1
  shift
  cat "$ROOT/tests/lib/remote-common.sh" "$script" | "${SSH[@]}" "sudo bash -s -- $(printf '%q ' "$@")"
}

require_vm() {
  if ! { [[ -f $T/qemu.pid ]] && kill -0 "$(cat "$T/qemu.pid")" 2>/dev/null; }; then
    echo "VM testowa nie działa — make test-up"
    exit 1
  fi
}
