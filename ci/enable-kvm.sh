#!/usr/bin/env bash
# Udostępnia /dev/kvm użytkownikowi runnera GitHub Actions (stage 5 i 6).
#
# `udevadm trigger` działa asynchronicznie — sprawdzenie zaraz po nim bywało wcześniejsze niż
# nadanie uprawnień (przebieg #7 padł na `test -w /dev/kvm`). Czekamy na udev, a w razie potrzeby
# nadajemy uprawnienia wprost. Brak samego urządzenia to cecha runnera (bez zagnieżdżonej
# wirtualizacji), a nie błąd kodu — adnotacja "INFRA:" (ci/ci_failures.py: kategoria infra).
set -euo pipefail

if [[ ! -e /dev/kvm ]]; then
  echo "::error title=INFRA: brak KVM::Runner nie udostępnia /dev/kvm (brak zagnieżdżonej wirtualizacji)"
  exit 1
fi

echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"' |
  sudo tee /etc/udev/rules.d/99-kvm4all.rules >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=kvm
sudo udevadm settle --timeout=30 || true

for _ in $(seq 1 10); do
  [[ -w /dev/kvm ]] && break
  sleep 1
done
if [[ ! -w /dev/kvm ]]; then
  echo "udev nie nadał uprawnień w 10 s — nadaję je wprost"
  sudo chmod 0666 /dev/kvm
fi
[[ -w /dev/kvm ]] || {
  echo "::error title=INFRA: brak dostępu do KVM::/dev/kvm istnieje, ale nie jest zapisywalne mimo chmod"
  exit 1
}
ls -l /dev/kvm
