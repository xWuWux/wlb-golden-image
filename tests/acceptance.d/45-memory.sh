# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-memory sprawdza aplikacje GUI „pod pamięć" (rola memory_apps, #105);
# na innych flavorach pomija. Lekkość bazy (brak pulpitu/GUI na wlb-general) pilnuje 40-pulpit.sh.
if grep -qx "WLB_IMAGE_NAME=wlb-memory" /etc/wlb/image-release 2>/dev/null; then
  echo "== Aplikacje GUI flavora wlb-memory (LibreOffice Calc #105, LabPlot #109, RStudio #108) =="
  expect_ok "LibreOffice obecny (binarka)" test -x /usr/bin/libreoffice
  # Stockowy kafelek LibreOffice Calc wystarcza: Exec=libreoffice rozwiązuje się przez /usr/bin, które
  # JEST w PATH sesji XFCE (inaczej niż /usr/local/bin z wrapperami neuro — #199).
  expect_ok "Kafelek Calc w menu XFCE" test -f /usr/share/applications/libreoffice-calc.desktop
  # Natywny render pod XFCE: plugin VCL GTK3 musi być zainstalowany (bez niego brzydki fallback „gen").
  expect_ok "Integracja GTK3 LibreOffice (render pod XFCE)" test -f /usr/lib/libreoffice/program/libvclplug_gtk3lo.so

  # LabPlot (#109): wykresy naukowe + curve-fitting GUI. W Ubuntu noble (LabPlot 2.x) binarka i
  # kafelek mają sufiks „2” (labplot2 / org.kde.labplot2.desktop); nazwa „labplot” bez sufiksu
  # pojawia się dopiero w nowszych wydaniach Ubuntu — nie zakładać jej na tym obrazie.
  expect_ok "LabPlot obecny (binarka)" bash -c "command -v labplot2"
  expect_ok "Kafelek LabPlot w menu XFCE" bash -c \
    "test -f /usr/share/applications/org.kde.labplot2.desktop || test -f /usr/share/applications/labplot2.desktop"

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

  # RStudio Server (#108): warstwa statystyki z GUI — R-IDE w przeglądarce przez jupyter-rsession-proxy
  # (rola rstudio w desktop.yml). Serwer zainstalowany, ale SAMODZIELNA usługa wyłączona: dostęp tylko
  # przez hub (konta TLJH nie mają haseł PAM, więc osobny port z logowaniem PAM nie zadziała — i nie
  # chcemy drugiej bramy uwierzytelniania). jamovi/JASP (Flatpak) i RKWard (ABI R vs CRAN) odrzucone.
  expect_ok "RStudio Server zainstalowany (rserver, #108)" test -x /usr/lib/rstudio-server/bin/rserver
  expect_fail "Samodzielna usługa rstudio-server WYŁĄCZONA — dostęp tylko przez hub (#108)" \
    systemctl is-enabled rstudio-server
  expect_ok "jupyter-rsession-proxy w środowisku TLJH — launcher RStudio w JupyterLab (#108)" \
    /opt/tljh/user/bin/python -c "import jupyter_rsession_proxy"
fi
