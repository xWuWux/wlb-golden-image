#!/usr/bin/env bash
# Skan CVE pakietów obrazu przez OVAL Canonical (USN) + oscap, z sygnałem świeżości jądra (#3, wariant C).
# Domyka ślepą plamkę po override "linux" w osv-scanner (#2/#3): osv-scanner OOM-ował na źródle jądra
# (2–14 GB), a oscap eval pełnego noble USN OVAL zużywa ~0,7 GB / ~6 s.
#
# Eval biegnie na RUNNERZE przeciwko dpkg-status OBRAZU przez OSCAP_PROBE_ROOT (probe dpkginfo czyta
# <root>/var/lib/dpkg/status), nie pakietom runnera. UWAGA: oscap i tak NIE flaguje jądra (USN kluczują
# poprawki na wersjonowanych pakietach binarnych linux-image-<seria>-NNN), dlatego sygnał świeżości
# jądra liczy ci/oval_summary.py z samych danych OVAL (porównanie wersji).
#
# Użycie: ci/image_oval.sh <dpkg-status> <out-dir>
set -euo pipefail

DPKG=${1:?podaj dpkg-status obrazu}
OUT=${2:?podaj katalog wyjściowy}
OVAL_URL=${WLB_OVAL_URL:-https://security-metadata.canonical.com/oval/com.ubuntu.noble.usn.oval.xml.bz2}

mkdir -p "$OUT"
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/var/lib/dpkg"
cp "$DPKG" "$root/var/lib/dpkg/status"

curl -fsSL --retry 5 --retry-all-errors -o "$OUT/oval.xml.bz2" "$OVAL_URL"
python3 -c 'import bz2, shutil, sys; shutil.copyfileobj(bz2.open(sys.argv[1]), open(sys.argv[2], "wb"))' \
  "$OUT/oval.xml.bz2" "$OUT/oval.xml"

# eval może zwrócić kod !=0, gdy znajdzie podatności — nie przerywamy (to raport)
OSCAP_PROBE_ROOT="$root" oscap oval eval \
  --results "$OUT/oval-results.xml" --report "$OUT/oval-report.html" "$OUT/oval.xml" \
  >"$OUT/oval-eval.log" 2>&1 || true

python3 ci/oval_summary.py "$DPKG" "$OUT/oval.xml" "$OUT/oval-results.xml" | tee "$OUT/oval-summary.md"
# artefakty do zachowania: oval-report.html + oval-summary.md; reszta (duża) idzie precz
rm -f "$OUT/oval.xml.bz2" "$OUT/oval.xml" "$OUT/oval-results.xml"
