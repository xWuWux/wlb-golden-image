#!/usr/bin/env bash
# Stage 6b: tymczasowe wdrożenie obrazu w projekcie testowym OpenStack i kryteria akceptacji
# na prawdziwej chmurze (Neutron, Cinder, cloud-init z metadanych). Wszystko, co zostało utworzone,
# jest usuwane na końcu — także po błędzie.
#
# Wymaga: python-openstackclient, OS_CLOUD (clouds.yaml) oraz zmiennych:
#   OS_TEST_FLAVOR    np. wlb.general
#   OS_TEST_NETWORK   sieć projektu testowego (NIE produkcyjnego)
#   OS_TEST_SSH_HOST  opcjonalnie: adres, pod którym runner widzi VM (domyślnie pierwszy adres IP serwera)
# Runner musi mieć łączność z siecią testową (zwykle runner self-hosted w sieci GUMed).
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require openstack ssh python3
: "${OS_CLOUD:?OS_CLOUD wymagane}" "${OS_TEST_FLAVOR:?}" "${OS_TEST_NETWORK:?}"
case "$OS_TEST_NETWORK $OS_CLOUD" in
  *prod*) {
    echo "Odmowa: stage 6b nie działa na zasobach produkcyjnych ($OS_CLOUD / $OS_TEST_NETWORK)"
    exit 1
  } ;;
esac

IMAGE=${1:-$(find output -name '*.qcow2' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)}
[[ -f $IMAGE ]] || {
  echo "Brak obrazu"
  exit 1
}
RUN_ID=wlb-ci-${GITHUB_RUN_ID:-local}-$(date +%s)
WORK=build/ephemeral
mkdir -p "$WORK"
ssh-keygen -q -t ed25519 -N '' -C "$RUN_ID" -f "$WORK/id_ed25519" <<<y >/dev/null

# shellcheck disable=SC2329  # wywoływana przez trap
cleanup() {
  echo "Sprzątanie $RUN_ID"
  openstack server delete --wait "$RUN_ID" 2>/dev/null || true
  openstack volume delete "$RUN_ID-workspace" 2>/dev/null || true
  openstack image delete "$RUN_ID" 2>/dev/null || true
}
trap cleanup EXIT

step "Wysyłanie obrazu $(basename "$IMAGE")"
openstack image create "$RUN_ID" --disk-format qcow2 --container-format bare --private \
  --property hw_disk_bus=virtio --property hw_qemu_guest_agent=yes --file "$IMAGE" -f value -c id
endstep

step "Tworzenie VM $RUN_ID"
sed "s|__SSH_PUBKEY__|$(cat "$WORK/id_ed25519.pub")|" tests/cloud-init/user-data.yaml >"$WORK/user-data"
volume=$(openstack volume create "$RUN_ID-workspace" --size 20 -f value -c id)
for _ in $(seq 1 30); do
  [[ $(openstack volume show "$volume" -f value -c status) == available ]] && break
  sleep 5
done
# dysk roboczy jako drugi dysk (vdb) — tak jak w produkcji
openstack server create "$RUN_ID" --image "$RUN_ID" --flavor "$OS_TEST_FLAVOR" --network "$OS_TEST_NETWORK" \
  --user-data "$WORK/user-data" --wait -f value -c id \
  --block-device "uuid=$volume,source_type=volume,destination_type=volume,boot_index=-1,delete_on_termination=false"
HOST=${OS_TEST_SSH_HOST:-$(openstack server show "$RUN_ID" -f json -c addresses |
  python3 -c 'import json,sys; a=json.load(sys.stdin)["addresses"]; print(next(iter(a.values()))[0])')}
endstep

SSH=(ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -i "$WORK/id_ed25519" "wlbadmin@$HOST")
step "Czekam na cloud-init i wlb-firstboot ($HOST)"
for _ in $(seq 1 90); do
  if "${SSH[@]}" true 2>/dev/null; then break; fi
  sleep 10
done
"${SSH[@]}" 'cloud-init status --wait >/dev/null; sudo cat /var/lib/wlb/firstboot.done'
endstep

step "Kryteria akceptacji na OpenStack"
set +e
cat tests/lib/remote-common.sh tests/acceptance-remote.sh | "${SSH[@]}" 'sudo bash -s' | tee "$WORK/acceptance.log"
rc=${PIPESTATUS[1]}
set -e
endstep
{
  echo "### Wdrożenie tymczasowe (OpenStack: $OS_CLOUD)"
  echo '```'
  grep -E '^(==|  (PASS|FAIL|SKIP)|Wynik)' "$WORK/acceptance.log"
  echo '```'
} | summary >/dev/null
exit "$rc"
