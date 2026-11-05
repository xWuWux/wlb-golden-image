# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-memory sprawdza aplikacje GUI „pod pamięć" (rola memory_apps, #105);
# na innych flavorach pomija. Lekkość bazy (brak pulpitu/GUI na wlb-general) pilnuje 40-pulpit.sh.
if grep -qx "WLB_IMAGE_NAME=wlb-memory" /etc/wlb/image-release 2>/dev/null; then
  echo "== Aplikacje GUI flavora wlb-memory (LibreOffice Calc #105, RKWard #108) =="
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
  # shellcheck disable=SC2016  # $d i $$ celowo rozwijane w wewnętrznym bash -c, nie tu
  expect_ok "Calc konwertuje CSV->ODS (silnik arkusza, #105)" bash -c '
    d=$(mktemp -d) || exit 1
    trap "rm -rf \"$d\"" EXIT
    printf "a,b\n1,2\n" > "$d/t.csv"
    HOME="$d" timeout --kill-after=10s 150s libreoffice --headless \
      -env:UserInstallation=file://"$d/profile" --convert-to ods --outdir "$d" "$d/t.csv" >/dev/null 2>&1
    test -f "$d/t.ods"
  '

  # RKWard (#108): statystyka z GUI klik-klik (frontend R; R już w obrazie). Sprawdzamy binarkę i wpis
  # menu — nazwa .desktop zależy od wersji pakietu KDE, akceptujemy oba warianty. Działanie analiz R
  # pokrywa osobno test jąder/R; pełny GUI to render-smoke (#138).
  expect_ok "RKWard obecny (binarka, #108)" bash -c "command -v rkward"
  expect_ok "Kafelek RKWard w menu XFCE (#108)" bash -c \
    "test -f /usr/share/applications/org.kde.rkward.desktop || test -f /usr/share/applications/rkward.desktop"
fi
