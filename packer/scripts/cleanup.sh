#!/usr/bin/env bash
# Czyszczenie przed zamrożeniem obrazu: usuwa tożsamość maszyny budującej,
# sekrety huba i ślady budowania, żeby każda VM z obrazu była unikalna.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get -y autoremove --purge
apt-get clean
rm -rf /var/lib/apt/lists/*

# JupyterHub wygeneruje nowy cookie secret i bazę przy pierwszym starcie VM
systemctl stop jupyterhub traefik || true
rm -f /opt/tljh/state/jupyterhub_cookie_secret /opt/tljh/state/jupyterhub.sqlite

# Klucze hosta SSH i machine-id odtwarza cloud-init przy pierwszym starcie
rm -f /etc/ssh/ssh_host_*
cloud-init clean --logs --machine-id --seed

rm -rf /tmp/* /var/tmp/* /root/.bash_history /root/.cache
find /var/log -type f \( -name '*.gz' -o -name '*.[0-9]' \) -delete
find /var/log -type f -exec truncate -s 0 {} +
journalctl --rotate
journalctl --vacuum-time=1s

fstrim -av || true
