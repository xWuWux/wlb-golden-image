#!/usr/bin/env bash
# Zatrzymuje VM testową i usuwa jej dyski (obraz w output/ zostaje nietknięty).
# KEEP_WORKSPACE=1 zostawia dysk roboczy (test migracji).
set -euo pipefail
T="$(cd "$(dirname "$0")/.." && pwd)/build/test"

if [[ -f $T/qemu.pid ]] && kill -0 "$(cat "$T/qemu.pid")" 2>/dev/null; then
  pid=$(cat "$T/qemu.pid")
  # najpierw łagodnie (system plików dysku roboczego ma być spójny), potem kill
  ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 \
    -i "$T/id_ed25519" -p "${SSH_PORT:-2222}" wlbadmin@127.0.0.1 'sudo systemctl poweroff' 2>/dev/null || true
  for _ in $(seq 1 60); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill "$pid" 2>/dev/null || true
  echo "VM testowa zatrzymana"
fi
rm -f "$T"/{qemu.pid,system.qcow2,seed.iso}
[[ ${KEEP_WORKSPACE:-0} == 1 ]] || rm -f "$T/workspace.qcow2"
