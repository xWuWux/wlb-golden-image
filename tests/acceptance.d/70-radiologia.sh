# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-radiologia sprawdza stos neuroobrazowania; na innych pomija.
if grep -qx "WLB_IMAGE_NAME=wlb-radiologia" /etc/wlb/image-release 2>/dev/null; then
  echo "== Stos neuroobrazowania (FSL, FSLeyes, 3DSlicer, #135) =="
  expect_ok "FSL zainstalowany (fslversion)" test -f /usr/local/fsl/etc/fslversion
  expect_ok "Środowisko FSL (profile.d/fsl.sh)" test -f /etc/profile.d/fsl.sh
  expect_ok "Narzędzie FSL obecne (fslmaths)" test -x /usr/local/fsl/share/fsl/bin/fslmaths
  expect_ok "FSLeyes obecny (w FSL)" test -x /usr/local/fsl/share/fsl/bin/fsleyes
  expect_ok "3DSlicer na PATH (Slicer)" test -x /usr/local/bin/Slicer

  # GUI runtime (#4): sama obecność binarki nie wystarcza — 3DSlicer wywracał się przy starcie na
  # brakującej bibliotece xcb (libxcb-icccm.so.4), a "test -x" tego nie łapał. Faktyczny start GUI
  # pod wirtualnym X (Xtigervnc z roli desktop) + marker wersji z rdzenia aplikacji i Pythona Slicera.
  echo "== Uruchamialność GUI stosu neuro (#4) =="
  # FSLeyes: --version działa headless (bez DISPLAY), potwierdza że pakiet się ładuje. UWAGA: fsleyes
  # --version zamyka deskryptor stdout i zwraca rc!=0, gdy stdout jest zwykłym PLIKIEM (tak loguje
  # harness) — dlatego czytamy przez podstawienie polecenia (potok) i sprawdzamy marker wersji, nie rc.
  # shellcheck disable=SC2016  # wyrażenia celowo rozwijane w wewnętrznym bash -c, nie tu
  expect_ok "FSLeyes uruchamia się (--version, #4)" \
    bash -c '. /etc/profile.d/fsl.sh >/dev/null 2>&1; out=$(fsleyes --version 2>&1); echo "$out" | grep -q "FSLeyes version"'
  # 3DSlicer: wymaga serwera X — startujemy jednorazowy Xtigervnc i sprawdzamy marker wersji.
  if command -v Xtigervnc >/dev/null 2>&1; then
    # shellcheck disable=SC2016  # wyrażenia celowo rozwijane w wewnętrznym bash -c, nie tu
    expect_ok "3DSlicer startuje pod wirtualnym X — biblioteki xcb + Qt (#4)" \
      bash -c '
        disp=:99
        Xtigervnc "$disp" -geometry 1024x768 -depth 24 -SecurityTypes None >/tmp/wlb-slicer-xvnc.log 2>&1 &
        xp=$!
        trap "kill $xp 2>/dev/null" EXIT
        for _ in $(seq 1 20); do [ -S /tmp/.X11-unix/X99 ] && break; sleep 0.5; done
        out=$(DISPLAY="$disp" Slicer --no-splash --no-main-window \
          --python-code "print(\"SLICER_OK=\"+slicer.app.applicationVersion); slicer.util.exit(0)" 2>&1)
        echo "$out" | grep -q "SLICER_OK="
      '
  else
    # Na flavorze radiologia pulpit (rola desktop) zawsze daje Xtigervnc — jego brak to regresja.
    expect_ok "Regresja: brak serwera X (Xtigervnc) na flavorze radiologia (#4)" false
  fi
fi
