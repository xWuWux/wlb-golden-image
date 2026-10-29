#!/usr/bin/env bash
# SBOM obrazu w formacie SPDX (#12a).
#   ci/sbom.sh KATALOG_ARTEFAKTÓW PLIK_WYJŚCIOWY.spdx.json
# Składniki: locki Pythona/R i dpkg-status z artefaktów budowania obrazu.
# Dlaczego SPDX, nie CycloneDX: osv-scanner 2.6.0 w CycloneDX gubi pakiety deb Ubuntu
# („unable to determine purl type"), w SPDX wypisuje wszystkie (zob. #12). Pakiet źródłowy
# „linux" pomijamy (ci/osv-scanner-image.toml) — pełne matchowanie CVE jądra wywołuje OOM (#2).
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"

ARTIFACTS=${1:?podaj katalog artefaktów obrazu}
OUT=${2:?podaj plik wyjściowy SBOM}
require osv-scanner python3

# Distro w PURL pakietów deb bierze się z /etc/os-release PROCESU skanującego (#129/#3).
# Gdy SBOM zawiera pakiety deb, tożsamość musi pochodzić z TEJ SAMEJ VM co dpkg-status
# i równać się środowisku skanera -- ostrzeżenie nie czyni artefaktu wiarygodnym.
if [[ -s $ARTIFACTS/dpkg-status ]]; then
  python3 ci/image_identity.py "$ARTIFACTS" ||
    die "walidacja tożsamości OS dla SBOM nieudana (#129) -- publikacja zablokowana"
else
  grep -q 'VERSION_CODENAME=noble' /etc/os-release 2>/dev/null ||
    echo "::warning title=SBOM::host skanujący nie jest noble — distro w PURL pakietów deb może być błędne"
fi

mkdir -p "$(dirname "$OUT")" build/sca
inputs=()
[[ -s $ARTIFACTS/renv.lock ]] && inputs+=(-L "$ARTIFACTS/renv.lock")
if [[ -s $ARTIFACTS/environment.lock.yml ]]; then
  python3 ci/sca_requirements.py "$ARTIFACTS/environment.lock.yml" build/sca/image-requirements.txt
  inputs+=(-L build/sca/image-requirements.txt)
fi
[[ -s $ARTIFACTS/dpkg-status ]] && inputs+=(-L "dpkg-status:$ARTIFACTS/dpkg-status")
((${#inputs[@]} > 0)) || die "brak wejść do SBOM (renv.lock/environment.lock.yml/dpkg-status) w ${ARTIFACTS}"

# exit 1 = znalezione podatności (nie błąd) — SBOM i tak zostaje zapisany; interesuje nas plik, nie kod.
osv-scanner scan source --no-resolve --config ci/osv-scanner-image.toml \
  --format spdx-2-3 --output-file "$OUT" "${inputs[@]}" || true
[[ -s $OUT ]] || die "osv-scanner nie wygenerował SBOM (${OUT})"
echo "SBOM (SPDX): ${OUT} ($(wc -c <"$OUT") B)"
