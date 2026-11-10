# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-histologia sprawdza stos histologii (rola histo_apps + rstudio);
# na innych flavorach pomija. Lekkość bazy (brak pulpitu/GUI na wlb-general) pilnuje 40-pulpit.sh.
if grep -qx "WLB_IMAGE_NAME=wlb-histologia" /etc/wlb/image-release 2>/dev/null; then
  echo "== Stos histologii: Calc + RStudio + jamovi (#107/#108) =="

  # --- LibreOffice Calc (arkusz) — jak na wlb-memory (#107) ---
  expect_ok "LibreOffice obecny (binarka)" test -x /usr/bin/libreoffice
  # Stockowy kafelek Calc wystarcza: Exec=libreoffice rozwiązuje się przez /usr/bin (w PATH sesji XFCE).
  expect_ok "Kafelek Calc w menu XFCE" test -f /usr/share/applications/libreoffice-calc.desktop
  expect_ok "Integracja GTK3 LibreOffice (render pod XFCE)" test -f /usr/lib/libreoffice/program/libvclplug_gtk3lo.so
  # Silnik Calc END-TO-END: konwersja CSV -> ODS headless (bez X) — ładuje rdzeń, filtry arkusza i zapis ODF.
  # shellcheck disable=SC2016  # $d celowo rozwijane w wewnętrznym bash -c, nie tu
  expect_ok "Calc konwertuje CSV->ODS (silnik arkusza, #107)" bash -c '
    d=$(mktemp -d) || exit 1
    trap "rm -rf \"$d\"" EXIT
    printf "a,b\n1,2\n" > "$d/t.csv"
    HOME="$d" timeout --kill-after=10s 150s libreoffice --headless \
      -env:UserInstallation=file://"$d/profile" --convert-to ods --outdir "$d" "$d/t.csv" >/dev/null 2>&1
    test -f "$d/t.ods"
  '

  # --- RStudio Server (statystyka z GUI w przeglądarce) — jak na wlb-memory (#108) ---
  # Serwer zainstalowany, ale SAMODZIELNA usługa wyłączona: dostęp tylko przez hub (konta TLJH nie mają
  # haseł PAM, więc osobny port z logowaniem PAM nie zadziała — i nie chcemy drugiej bramy uwierzytelniania).
  expect_ok "RStudio Server zainstalowany (rserver, #108)" test -x /usr/lib/rstudio-server/bin/rserver
  expect_fail "Samodzielna usługa rstudio-server WYŁĄCZONA — dostęp tylko przez hub (#108)" \
    systemctl is-enabled rstudio-server
  expect_ok "jupyter-rsession-proxy w środowisku TLJH — launcher RStudio w JupyterLab (#108)" \
    /opt/tljh/user/bin/python -c "import jupyter_rsession_proxy"

  # --- jamovi (Flatpak, aplikacja pulpitowa) — #108 ---
  # jamovi dla Linuksa jest tylko jako Flatpak; wpięty jako aplikacja XFCE (sesja przez noVNC), nie przez
  # proxy. Instalacja app + runtime wchodzi w warstwie build (ma sieć); w runtime działa lokalnie, offline.
  echo "== jamovi (Flatpak, #108) =="
  expect_ok "jamovi zainstalowany w Flatpak (systemowo)" flatpak info --system org.jamovi.jamovi
  # Kafelek własny z ABSOLUTNYM Exec (#199): sesja XFCE nie gwarantuje XDG_DATA_DIRS eksportów Flatpaka.
  expect_ok "Kafelek jamovi w menu XFCE" test -f /usr/share/applications/wlb-jamovi.desktop
  expect_ok "Kafelek jamovi wskazuje flatpak run absolutnie (Exec, #199)" \
    grep -Fxq 'Exec=/usr/bin/flatpak run org.jamovi.jamovi' /usr/share/applications/wlb-jamovi.desktop
  # Sandbox widzi dane badacza: override filesystem=/workspace jest aktywny (bez tego file dialog jamovi
  # nie dosięga /workspace/jupyter-<login>). --show-permissions scala override'y z manifestem aplikacji.
  expect_ok "jamovi: dostęp sandboxa do /workspace (override, #108)" bash -c \
    "flatpak info --system --show-permissions org.jamovi.jamovi 2>/dev/null | grep -qE '(^|[=;,[:space:]])/workspace([;,[:space:]]|$)'"
  # GATINGOWY smoke sandboxa: uruchomienie bwrap przez nieuprzywilejowane userns. To realne ryzyko na
  # noble (#63/#65: kernel.apparmor_restrict_unprivileged_userns) — jeśli utwardzenie bazy zablokuje userns,
  # jamovi w ogóle nie wystartuje. --command=sh odpala powłokę w runtime sandboxa (bez GUI/X), czyli testuje
  # dokładnie ten mechanizm bez potrzeby serwera X. XDG_RUNTIME_DIR nadane, by flatpak run nie padł na jego braku.
  # shellcheck disable=SC2016  # $d i marker celowo rozwijane w wewnętrznym bash -c, nie tu
  expect_ok "jamovi: sandbox bwrap startuje (nieuprzywilejowane userns, #63/#108)" bash -c '
    d=$(mktemp -d) || exit 1
    trap "rm -rf \"$d\"" EXIT
    export XDG_RUNTIME_DIR="$d"
    out=$(timeout --kill-after=5s 60s flatpak run --command=sh org.jamovi.jamovi -c "echo JAMOVI_SANDBOX_OK" 2>&1) || {
      printf "%s\n" "$out"
      exit 1
    }
    printf "%s" "$out" | grep -q JAMOVI_SANDBOX_OK
  '
  # desktop-file-validate (jeśli dostępny) — poprawność składni kafelka.
  if command -v desktop-file-validate >/dev/null 2>&1; then
    expect_ok "Kafelek jamovi przechodzi desktop-file-validate" \
      desktop-file-validate /usr/share/applications/wlb-jamovi.desktop
  fi
fi
