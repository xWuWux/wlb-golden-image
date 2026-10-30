#!/usr/bin/env bash
# Izolowany test realnego wrappera Ubuntu 24.04, bez danych i bez sesji VM.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# Manifest obrazu Ubuntu przypięty po SHA256; pakiety instalujemy z repozytorium Ubuntu 24.04.
image='ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852'
command -v docker >/dev/null || {
  echo "Brak dockera" >&2
  exit 1
}
docker run --rm --interactive --network bridge \
  --mount "type=bind,src=$ROOT/ansible/roles/desktop/files/vncserver-config-mandatory,dst=/tmp/wlb-vnc-config,readonly" \
  "$image" bash -se <<'CONTAINER'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -qq -y --no-install-recommends tigervnc-standalone-server xterm >/dev/null
install -m 0644 /tmp/wlb-vnc-config /etc/tigervnc/vncserver-config-mandatory
useradd -m wlb-test
install -d -o wlb-test -g wlb-test -m 0700 /home/wlb-test/private
# Ten kontener nie ma danych, a Unix socket jest w katalogu 0700; celowo próbujemy
# nadpisać politykę argumentami 1, żeby sprawdzić priorytet config-mandatory.
runuser -u wlb-test -- vncserver -rfbunixpath /home/wlb-test/private/vnc.sock -rfbport -1 \
  -xstartup /usr/bin/xterm -SecurityTypes None -AcceptCutText=1 -SendCutText=1 -fg >/tmp/vnc.log 2>&1 &
wrapper=$!
trap 'kill "$wrapper" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  [[ -S /home/wlb-test/private/vnc.sock ]] && break
  kill -0 "$wrapper" 2>/dev/null || break
  sleep 1
done
if [[ ! -S /home/wlb-test/private/vnc.sock ]]; then
  cat /tmp/vnc.log >&2
  echo 'TigerVNC nie uruchomił prywatnego socketu' >&2
  exit 1
fi
# /proc to bezpośredni dowód parametrów uruchomionego procesu, nie tylko tekst konfiguracji.
found=0
for cmdline in /proc/[0-9]*/cmdline; do
  args=$(tr '\0' '\n' <"$cmdline" 2>/dev/null || true)
  if grep -qx '/usr/bin/Xtigervnc' <<<"$args" && grep -qx '/home/wlb-test/private/vnc.sock' <<<"$args"; then
    grep -qx -- '-AcceptCutText=0' <<<"$args"
    grep -qx -- '-SendCutText=0' <<<"$args"
    grep -qx -- '-rfbport' <<<"$args"
    found=1
    break
  fi
done
[[ $found == 1 ]] || { echo 'Nie znaleziono działającego Xtigervnc' >&2; exit 1; }
echo 'PASS: TigerVNC uruchomiony, polityka schowka 0 w obu kierunkach mimo próby nadpisania.'
CONTAINER
