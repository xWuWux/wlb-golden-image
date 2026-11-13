# shellcheck shell=bash
# Adaptacyjna: standard biurowy pulpitu (#269, #270) — LibreOffice Writer i czytnik PDF (evince)
# na KAŻDYM flavorze z pulpitem (decyzja PO: Opcja A, bez wyjątku dla radiologii).
# wlb-general jest headless, więc nie dotyczy.
if grep -qxE 'WLB_IMAGE_NAME=wlb-(memory|radiologia|histologia)' /etc/wlb/image-release 2>/dev/null; then
  echo "== Standard biurowy pulpitu: LibreOffice Writer (#269) i czytnik PDF (#270) =="
  expect_ok "LibreOffice obecny (binarka)" test -x /usr/bin/libreoffice
  # Kafelek stockowy z libreoffice-common — bez własnego .desktop (jak Calc w 45-memory/47-histologia).
  expect_ok "Kafelek LibreOffice Writer w menu XFCE" test -f /usr/share/applications/libreoffice-writer.desktop
  # Natywny render pod XFCE: plugin VCL GTK3 musi być obecny (bez niego brzydki fallback „gen”).
  expect_ok "Integracja GTK3 LibreOffice (render pod XFCE)" test -f /usr/lib/libreoffice/program/libvclplug_gtk3lo.so

  # Smoke silnika dokumentów: .txt -> .odt (filtr Text) ORAZ .odt -> .docx (MS Word 2007 XML).
  # Mocniejsze niż --version — ładuje rdzeń, filtr dokumentu i zapis ODF/OOXML, a nie tylko binarkę.
  # Wzorzec jak Calc CSV->ODS w 45-memory.sh.
  # shellcheck disable=SC2016  # $d i $$ celowo rozwijane w wewnętrznym bash -c, nie tu
  expect_ok "Writer konwertuje .txt->.odt i .odt->.docx (silnik dokumentów, #269)" bash -c '
    d=$(mktemp -d) || exit 1
    trap "rm -rf \"$d\"" EXIT
    printf "WLB test\n" > "$d/t.txt"
    HOME="$d" timeout --kill-after=10s 150s libreoffice --headless \
      -env:UserInstallation=file://"$d/profile" --convert-to odt --outdir "$d" "$d/t.txt" >/dev/null 2>&1 || exit 1
    test -s "$d/t.odt" || exit 1
    HOME="$d" timeout --kill-after=10s 150s libreoffice --headless \
      -env:UserInstallation=file://"$d/profile" --convert-to "docx:MS Word 2007 XML" --outdir "$d" "$d/t.odt" >/dev/null 2>&1 || exit 1
    test -s "$d/t.docx"
  '

  # Czytnik PDF (evince, #270): binarka, stockowy kafelek XFCE oraz headless smoke renderowania
  expect_ok "Czytnik PDF evince obecny (binarka, #270)" test -x /usr/bin/evince
  expect_ok "Kafelek czytnika PDF w menu XFCE (org.gnome.Evince.desktop, #270)" \
    test -f /usr/share/applications/org.gnome.Evince.desktop

  if command -v evince-thumbnailer >/dev/null; then
    # shellcheck disable=SC2016  # $d celowo rozwijane w wewnętrznym bash -c, nie tu
    expect_ok "evince-thumbnailer renderuje PDF bez X (smoke silnika PDF, #270)" bash -c '
      d=$(mktemp -d) || exit 1
      trap "rm -rf \"$d\"" EXIT
      python3 -c "
import sys
pdf = (
    b\"%PDF-1.4\n\"
    b\"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n\"
    b\"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n\"
    b\"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R/Resources<<>>>>endobj\n\"
    b\"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n\"
    b\"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n\"
)
with open(sys.argv[1], \"wb\") as f:
    f.write(pdf)
" "$d/sample.pdf" || exit 1
      timeout --kill-after=5s 30s evince-thumbnailer -s 128 "$d/sample.pdf" "$d/out.png" >/dev/null 2>&1 || exit 1
      test -s "$d/out.png"
    '
  fi
fi
