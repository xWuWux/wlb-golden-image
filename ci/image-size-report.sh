#!/usr/bin/env bash
# shellcheck shell=bash
# Raport rozmiaru obrazu qcow2 (#135): flavor z FSL + 3DSlicer ma dziesiątki GB, więc rozmiar
# ma być widoczny przy każdym buildzie, a nie sprawdzany ręcznie (qemu-img info).
#   ci/image-size-report.sh OBRAZ.qcow2 [ETYKIETA]
# Wypisuje rozmiar wirtualny (dysk gościa) i faktyczny (plik) oraz dopisuje wiersz do
# podsumowania joba. Opcjonalny próg: WLB_IMAGE_SIZE_MAX_GIB — przekroczenie rozmiaru
# FAKTYCZNEGO pliku kończy się kodem 1 (domyślnie bez progu, tylko raport).
set -euo pipefail
# shellcheck source=ci/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

image=${1:-}
label=${2:-${image##*/}}
[[ -n $image ]] || die "użycie: image-size-report.sh OBRAZ.qcow2 [ETYKIETA]"
[[ -f $image ]] || die "brak obrazu: $image"

info=$(qemu-img info --output=json "$image")
read -r virtual actual < <(python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d["virtual-size"], d.get("actual-size", 0))
' <<<"$info")

gib() { python3 -c 'import sys; print(f"{int(sys.argv[1]) / 2**30:.2f}")' "$1"; }
v=$(gib "$virtual")
a=$(gib "$actual")

echo "Rozmiar obrazu $label: wirtualny ${v} GiB, plik ${a} GiB"
summary <<EOT
### Rozmiar obrazu: $label
| Wirtualny (dysk gościa) | Faktyczny (plik qcow2) |
|---|---|
| ${v} GiB | ${a} GiB |
EOT

if [[ -n ${WLB_IMAGE_SIZE_MAX_GIB:-} ]]; then
  max_bytes=$((WLB_IMAGE_SIZE_MAX_GIB * 1024 * 1024 * 1024))
  if ((actual > max_bytes)); then
    echo "BŁĄD: rozmiar pliku ${a} GiB przekracza próg ${WLB_IMAGE_SIZE_MAX_GIB} GiB" >&2
    exit 1
  fi
fi
