# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-memory sprawdza aplikacje GUI „pod pamięć" (rola memory_apps, #105);
# na innych flavorach pomija. Lekkość bazy (brak pulpitu/GUI na wlb-general) pilnuje 40-pulpit.sh.
if grep -qx "WLB_IMAGE_NAME=wlb-memory" /etc/wlb/image-release 2>/dev/null; then
  echo "== Aplikacje GUI flavora wlb-memory (LibreOffice Calc, #105) =="
  expect_ok "LibreOffice obecny (binarka)" test -x /usr/bin/libreoffice
  # Stockowy kafelek LibreOffice Calc wystarcza: Exec=libreoffice rozwiązuje się przez /usr/bin, które
  # JEST w PATH sesji XFCE (inaczej niż /usr/local/bin z wrapperami neuro — #199).
  expect_ok "Kafelek Calc w menu XFCE" test -f /usr/share/applications/libreoffice-calc.desktop
  # Natywny render pod XFCE: plugin VCL GTK3 musi być zainstalowany (bez niego brzydki fallback „gen").
  expect_ok "Integracja GTK3 LibreOffice (render pod XFCE)" test -f /usr/lib/libreoffice/program/libvclplug_gtk3lo.so

  # Silnik Calc działa END-TO-END: konwersja CSV -> ODS headless (bez X). Mocniejsze niż --version —
  # ładuje rdzeń, filtry arkusza i zapis ODF, a nie tylko sprawdza, że binarka istnieje. Render pod VNC
  # pokrywa osobno desktop render-smoke (#138); start GUI LibreOffice nie ma czystego „otwórz i wyjdź",
  # więc tu zostaje przy funkcjonalnym smoke silnika.
  expect_ok "Calc zapisuje dwie komórki w ODS jako badacz (#105)" as "$R1" bash -se <<'CALC_SMOKE'
d=$(mktemp -d)
trap 'rm -rf -- "$d"' EXIT
printf 'WLB-header\nWLB-result\n' >"$d/t.csv"
HOME="$d" timeout --kill-after=10s 150s /usr/bin/libreoffice --headless \
  -env:UserInstallation="file://$d/profile" --convert-to ods --outdir "$d" "$d/t.csv"
python3 - "$d/t.ods" <<'CHECK_ODS'
import sys
from xml.etree import ElementTree
from zipfile import ZipFile

with ZipFile(sys.argv[1]) as document:
    if document.read("mimetype") != b"application/vnd.oasis.opendocument.spreadsheet":
        sys.exit("niepoprawny typ dokumentu")
    root = ElementTree.fromstring(document.read("content.xml"))
ns = {"t": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
      "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}
cells = root.findall(".//t:table/t:table-row/t:table-cell/text:p", ns)
if [cell.text for cell in cells] != ["WLB-header", "WLB-result"]:
    sys.exit("utracone lub zmienione dane arkusza")
CHECK_ODS
CALC_SMOKE
fi
