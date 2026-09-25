#!/usr/bin/env bash
# Zatrzymuje VM testową i usuwa jej dyski (obraz w output/ zostaje nietknięty).
set -euo pipefail
T="$(cd "$(dirname "$0")/.." && pwd)/build/test"
if [[ -f $T/qemu.pid ]] && kill -0 "$(cat "$T/qemu.pid")" 2>/dev/null; then
  kill "$(cat "$T/qemu.pid")"
  echo "VM testowa zatrzymana"
fi
rm -f "$T"/{qemu.pid,system.qcow2,workspace.qcow2,seed.iso}
