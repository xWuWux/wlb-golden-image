#!/usr/bin/env bash
# shellcheck shell=bash
# Raport rozmiaru obrazu qcow2 (#135): flavor z FSL + 3DSlicer ma dziesiątki GB, więc rozmiar
# ma być widoczny przy każdym buildzie, a nie sprawdzany ręcznie (qemu-img info).
#   ci/image-size-report.sh OBRAZ.qcow2 [ETYKIETA]
# Wypisuje rozmiar wirtualny (dysk gościa) i zaalokowany na hoście oraz dopisuje wiersz do
# podsumowania joba. Opcjonalny próg: WLB_IMAGE_SIZE_MAX_GIB — przekroczenie rozmiaru
# ALOKACJI na hoście kończy się kodem 1 (domyślnie bez progu, tylko raport).
set -euo pipefail
# shellcheck source=ci/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

(($# >= 1 && $# <= 2)) || die "użycie: image-size-report.sh OBRAZ.qcow2 [ETYKIETA]"
image=$1
label=${2:-${image##*/}}
[[ -f $image ]] || die "brak obrazu: $image"
[[ $label =~ ^[a-zA-Z0-9._+-]+$ ]] || die "etykieta wymaga liter ASCII, cyfr lub ._+-"
# Ścieżka ./ zapobiega interpretacji nazwy jako opcji lub protokołu QEMU.
[[ $image == /* ]] || image=./$image
result=$(qemu-img info -f qcow2 --output=json "$image" | python3 -c '
import json, re, sys
try:
    data = json.load(sys.stdin)
    virtual, actual = data["virtual-size"], data["actual-size"]
    if any(type(n) is not int or n < 0 for n in (virtual, actual)):
        raise ValueError("rozmiar musi być nieujemną liczbą całkowitą bajtów")
    limit = sys.argv[1]
    if limit and not re.fullmatch(r"[0-9]+", limit):
        raise ValueError("WLB_IMAGE_SIZE_MAX_GIB wymaga nieujemnej liczby całkowitej GiB")
    exceeded = bool(limit) and actual > int(limit) * 2**30
    print(f"{virtual / 2**30:.2f} {actual / 2**30:.2f} {actual} {int(exceeded)}")
except (ValueError, TypeError, KeyError, OverflowError) as exc:
    sys.exit(f"BŁĄD pomiaru qcow2: {exc}")
' "${WLB_IMAGE_SIZE_MAX_GIB:-}") || die "nie udało się sprawdzić obrazu lub progu"
read -r v a actual exceeded <<<"$result"

echo "Rozmiar obrazu $label: wirtualny ${v} GiB, alokacja ${a} GiB ($actual B)"
summary <<EOT
### Rozmiar obrazu: $label
| Wirtualny (dysk gościa) | Alokacja na hoście (qcow2) |
|---|---|
| ${v} GiB | ${a} GiB |
EOT
if [[ $exceeded == 1 ]]; then
  die "alokacja $actual B przekracza próg ${WLB_IMAGE_SIZE_MAX_GIB} GiB"
fi
