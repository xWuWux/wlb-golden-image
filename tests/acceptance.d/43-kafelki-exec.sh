# shellcheck shell=bash
# #314 część A: statyczna bramka kafelek → Exec (menu XFCE). HEADLESS i deterministyczna, więc
# BRAMKUJE etap 5 (ko przy błędzie) na każdym obrazie z pulpitem, na którym są kafelki wlb-*.desktop.
#
# Dla każdego /usr/share/applications/wlb-*.desktop:
#   1. parsujemy linie Exec= i odcinamy field-codes (%f %F %u %U %i %c %k),
#   2. bierzemy pierwszy token polecenia,
#   3. wymagamy ścieżki absolutnej ALBO rozwiązania na PATH SESJI — nie roota. Root ma
#      /usr/local/bin, sesja XFCE/jrdp go NIE ma (#199/#202); `command -v` roota dałby fałszywy
#      zielony dla gołego "Exec=wlb-fsleyes". PATH sesji odtwarzamy w tests/lib/kafelki-exec.sh
#      (jrdp/xstartup nie ustawia PATH — dziedziczy PATH spawnera TLJH).
#   4. cel musi istnieć i być wykonywalny; wrapper WLB (/usr/local/bin, /opt/wlb) musi wskazywać
#      istniejący cel (np. fsleyes/fsl przez FSLDIR).
#   5. TEST NEGATYWNY (obowiązkowy): kopia kafelka z zepsutym Exec musi dać FAIL — inaczej zielony
#      wynik byłby fałszywy (bramka, która nic nie wykrywa).
#
# Adaptacyjnie: tylko obrazy z pulpitem i kafelkami wlb-*.desktop (radiologia, histologia).
if [ -x /opt/wlb/desktop/wlb-desktop-xstartup ]; then
  w43_tiles=(/usr/share/applications/wlb-*.desktop)
  if [ ! -e "${w43_tiles[0]}" ]; then
    skip "Kafelki wlb-*.desktop: brak na tym obrazie (#314)"
  else
    echo "== Kafelki pulpitu: Exec → istniejący, wykonywalny cel (#314) =="
    # Kanoniczny PATH sesji — jawnie, żeby bramka nigdy nie wzięła PATH roota (który ma /usr/local/bin).
    W43_SESSION_PATH=/opt/tljh/user/bin:/bin:/usr/bin
    export W43_SESSION_PATH
    # shellcheck disable=SC2016  # $W43_SESSION_PATH celowo rozwija wewnętrzny bash
    expect_ok "PATH sesji nie zawiera /usr/local/bin (bramka nie używa PATH roota, #199/#202)" \
      bash -c 'case ":$W43_SESSION_PATH:" in *:/usr/local/bin:*) exit 1 ;; *) exit 0 ;; esac'
    # shellcheck disable=SC2016  # jw.
    expect_ok "PATH sesji zawiera /usr/bin (rozwiązywanie stockowych Exec)" \
      bash -c 'case ":$W43_SESSION_PATH:" in *:/usr/bin:*) exit 0 ;; *) exit 1 ;; esac'

    for w43_f in "${w43_tiles[@]}"; do
      expect_ok "Kafelek $(basename "$w43_f"): Exec istnieje i jest wykonywalny na PATH sesji (#314)" \
        w43_tile_ok "$w43_f"
    done

    # TEST NEGATYWNY: ta sama bramka na kopii kafelka z celowo zepsutym Exec musi zwrócić błąd.
    W43_TMP=$(mktemp -d) || ko "Kafelki Exec: nie można utworzyć katalogu tymczasowego (#314)"
    W43_BAD=$W43_TMP/wlb-zly.desktop
    printf '[Desktop Entry]\nType=Application\nName=Zły\nExec=wlb-nie-ma-takiego-314 %%F\n' >"$W43_BAD"
    expect_fail "Bramka wykrywa względny/nieistniejący Exec (test negatywny, #314)" \
      w43_tile_ok "$W43_BAD"
    printf '[Desktop Entry]\nType=Application\nName=Zły\nExec=/usr/local/bin/wlb-nie-ma-takiego-314\n' >"$W43_BAD"
    expect_fail "Bramka wykrywa absolutny nieistniejący Exec (test negatywny, #314)" \
      w43_tile_ok "$W43_BAD"
    rm -rf "$W43_TMP"
  fi
fi
