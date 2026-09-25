#!/usr/bin/env bash
# Uruchamia kryteria akceptacji MVP na działającej VM testowej (tests/run-local.sh).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T="$ROOT/build/test"
SSH=(ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
     -i "$T/id_ed25519" -p "${SSH_PORT:-2222}" wlbadmin@127.0.0.1)
[[ -f $T/qemu.pid ]] || { echo "VM testowa nie działa — make test-up"; exit 1; }
"${SSH[@]}" "sudo bash -s" < "$ROOT/tests/acceptance-remote.sh"
