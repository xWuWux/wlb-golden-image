# shellcheck shell=bash
# Adaptacyjna: standard biurowy pulpitu (#269) — LibreOffice Writer na KAŻDYM flavorze z pulpitem
# (decyzja PO: Opcja A, bez wyjątku dla radiologii). wlb-general jest headless, więc nie dotyczy.
if grep -qxE 'WLB_IMAGE_NAME=wlb-(memory|radiologia|histologia)' /etc/wlb/image-release 2>/dev/null; then
  echo "== Standard biurowy pulpitu: LibreOffice Writer (#269) =="
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
fi
