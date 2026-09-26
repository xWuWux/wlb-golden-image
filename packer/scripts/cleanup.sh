#!/usr/bin/env bash
# Czyszczenie przed zamrożeniem obrazu: usuwa tożsamość maszyny budującej,
# sekrety huba i ślady budowania, żeby każda VM z obrazu była unikalna.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

# Nagłówki starszych wersji jądra zostają po dist-upgrade — niepotrzebne w VM (nie budujemy modułów),
# zajmują ~110 MB i zawyżają raport CVE. Zostawiamy wersję, która wystartuje (najnowsze
# /boot/vmlinuz-*), a nie bieżącą: w czasie budowania działa jeszcze jądro sprzed aktualizacji.
latest=$(find /boot -maxdepth 1 -name 'vmlinuz-*' -printf '%f\n' | sed 's/^vmlinuz-//' | sort -V | tail -1)
latest_ver=${latest%-*} # 6.8.0-142-generic -> 6.8.0-142
mapfile -t old_headers < <(
  dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' 'linux-headers-[0-9]*' 2>/dev/null |
    awk '$1 == "ii" {print $2}' | grep -vE -- "-${latest_ver//./\\.}(-|$)" || true
)
if [[ -n $latest_ver && ${#old_headers[@]} -gt 0 ]]; then
  echo "Usuwam nagłówki starszych jąder (zostaje ${latest_ver}): ${old_headers[*]}"
  apt-get -y purge "${old_headers[@]}"
fi

apt-get -y autoremove --purge
apt-get clean
rm -rf /var/lib/apt/lists/*

# JupyterHub wygeneruje nowy cookie secret i bazę przy pierwszym starcie VM
systemctl stop jupyterhub traefik || true
rm -f /opt/tljh/state/jupyterhub_cookie_secret /opt/tljh/state/jupyterhub.sqlite /workspace/.wlb-hub/*

# Klucze hosta SSH i machine-id odtwarza cloud-init przy pierwszym starcie
rm -f /etc/ssh/ssh_host_*
cloud-init clean --logs --machine-id --seed

rm -rf /tmp/* /var/tmp/* /root/.bash_history /root/.cache
find /var/log -type f \( -name '*.gz' -o -name '*.[0-9]' \) -delete
find /var/log -type f -exec truncate -s 0 {} +
journalctl --rotate
journalctl --vacuum-time=1s

fstrim -av || true
