#!/usr/bin/env bash
# Czyszczenie przed zamrożeniem obrazu: usuwa tożsamość maszyny budującej,
# sekrety huba i ślady budowania, żeby każda VM z obrazu była unikalna.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

# Starsze jądra, moduły, nagłówki i narzędzia zostają po dist-upgrade (apt-autoremove chroni też
# „poprzednie" jądro). Po restarcie maszyny budującej (rola base) działa już jądro docelowe, więc stare
# można jawnie usunąć — ~110 MB i jeden wpis w GRUB. Zostawiamy wersję, która wystartuje (najnowsze
# /boot/vmlinuz-*); meta-pakiety (linux-image-virtual, linux-tools-common itd.) nie pasują do wzorca
# wersjonowanego i zostają. linux-tools-* można czyścić nawet bez restartu (narzędzia przestrzeni usera).
latest=$(find /boot -maxdepth 1 -name 'vmlinuz-*' -printf '%f\n' | sed 's/^vmlinuz-//' | sort -V | tail -1)
latest_ver=${latest%-*} # 6.8.0-142-generic -> 6.8.0-142
old_kernel=()
for pat in 'linux-image-[0-9]*' 'linux-modules-[0-9]*' 'linux-modules-extra-[0-9]*' \
  'linux-headers-[0-9]*' 'linux-tools-[0-9]*'; do
  mapfile -t found < <(
    dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' "$pat" 2>/dev/null |
      awk '$1 == "ii" {print $2}' | grep -vE -- "-${latest_ver//./\\.}(-|$)" || true
  )
  old_kernel+=("${found[@]}")
done
if [[ -n $latest_ver && ${#old_kernel[@]} -gt 0 ]]; then
  echo "Usuwam starsze jądra/moduły/narzędzia (zostaje ${latest_ver}): ${old_kernel[*]}"
  apt-get -y purge "${old_kernel[@]}"
  update-grub # usuń wpisy starego jądra z menu GRUB
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
