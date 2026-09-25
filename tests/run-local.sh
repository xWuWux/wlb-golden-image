#!/usr/bin/env bash
# Uruchamia zbudowany golden image lokalnie w QEMU/KVM jako Laboratorium testowe.
# Obraz nie jest modyfikowany: system startuje z nakładki qcow2, dysk roboczy jest osobny.
#
#   tests/run-local.sh [obraz.qcow2]     # domyślnie najnowszy z output/
#   KEEP_WORKSPACE=1 tests/run-local.sh  # ponownie użyj dysku roboczego (test migracji)
#   SSH:  ssh -p 2222 -i build/test/id_ed25519 wlbadmin@127.0.0.1
#   Hub:  http://localhost:8080  (z Windows także, WSL przekazuje localhost)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
T="$ROOT/build/test"
IMAGE=${1:-$(find "$ROOT/output" -name '*.qcow2' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)}
SSH_PORT=${SSH_PORT:-2222}
HUB_PORT=${HUB_PORT:-8080}

[[ -n $IMAGE && -f $IMAGE ]] || {
  echo "Brak obrazu — najpierw make build"
  exit 1
}
[[ -w /dev/kvm ]] || {
  echo "Brak dostępu do /dev/kvm (grupa kvm, restart WSL)"
  exit 1
}
if [[ -f $T/qemu.pid ]] && kill -0 "$(cat "$T/qemu.pid")" 2>/dev/null; then
  echo "VM testowa już działa (make test-down, aby zatrzymać)"
  exit 0
fi

mkdir -p "$T"
[[ -f $T/id_ed25519 ]] || ssh-keygen -q -t ed25519 -N '' -C wlb-test -f "$T/id_ed25519"
rm -f "$T"/{system.qcow2,seed.iso,serial.log}
if [[ ${KEEP_WORKSPACE:-0} != 1 || ! -f $T/workspace.qcow2 ]]; then
  rm -f "$T/workspace.qcow2"
  qemu-img create -q -f qcow2 "$T/workspace.qcow2" 20G
fi

qemu-img create -q -f qcow2 -F qcow2 -b "$(realpath "$IMAGE")" "$T/system.qcow2" 40G
sed "s|__SSH_PUBKEY__|$(cat "$T/id_ed25519.pub")|" "$ROOT/tests/cloud-init/user-data.yaml" >"$T/user-data"
cloud-localds "$T/seed.iso" "$T/user-data" "$ROOT/tests/cloud-init/meta-data.yaml"

echo "Start VM z $(basename "$IMAGE")"
# kolejność dysków: vda = system, vdb = /workspace, vdc = seed cloud-init
qemu-system-x86_64 -name wlb-lab-test01 -machine q35,accel=kvm -cpu host \
  -smp "${VM_CPUS:-4}" -m "${VM_MEMORY:-8192}" \
  -drive file="$T/system.qcow2",if=virtio,format=qcow2 \
  -drive file="$T/workspace.qcow2",if=virtio,format=qcow2 \
  -drive file="$T/seed.iso",if=virtio,format=raw,readonly=on \
  -nic "user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22,hostfwd=tcp:127.0.0.1:${HUB_PORT}-:80" \
  -display none -serial file:"$T/serial.log" \
  -daemonize -pidfile "$T/qemu.pid"

SSH=(ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5
  -i "$T/id_ed25519" -p "$SSH_PORT" wlbadmin@127.0.0.1)
echo -n "Czekam na SSH"
for _ in $(seq 1 60); do
  "${SSH[@]}" true 2>/dev/null && break
  echo -n .
  sleep 5
done
echo
echo "Czekam na cloud-init i wlb-firstboot..."
if ! "${SSH[@]}" "cloud-init status --wait >/dev/null; sudo cat /var/lib/wlb/firstboot.done"; then
  # diagnostyka od razu na ekranie (w CI trafia do logu joba, nawet gdy artefakty się nie zapiszą)
  echo "wlb-firstboot nie zakończył się. Ostatnie wpisy z VM:"
  "${SSH[@]}" "sudo journalctl -t wlb-firstboot --no-pager | tail -20; sudo tail -30 /var/log/cloud-init-output.log" || true
  echo "Pełny log konsoli: $T/serial.log"
  exit 1
fi

cat <<EOF

VM testowa działa.
  SSH:  ssh -p $SSH_PORT -i build/test/id_ed25519 wlbadmin@127.0.0.1
  Hub:  http://localhost:$HUB_PORT
  Hasło admina huba (admin-klienta): ${SSH[*]} sudo cat /root/wlb-hub-admin-initial-password
Testy: make test    Zatrzymanie: make test-down
EOF
