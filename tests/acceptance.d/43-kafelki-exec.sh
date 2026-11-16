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
    # PATH sesji wyprowadzamy z REALNEGO źródła: środowiska procesu serwera badacza w jego
    # jednostce systemd (jrdp/xstartup nie ustawia PATH — dziedziczy go z serwera; menu XFCE widzi
    # to samo). Stała jest wyłącznie fallbackiem z ostrzeżeniem, gdy jednostka nie istnieje —
    # nie może udawać „odtworzenia" PATH (to założenie zabiło #199).
    W43_PATH_SOURCE=""
    # shellcheck disable=SC2016  # "$PATH" celowo rozwija wewnętrzny sh w jednostce sesji
    if W43_UNIT_PATH=$(in_unit "$R1" sh -c 'printf %s "$PATH"' 2>/dev/null) && [[ -n $W43_UNIT_PATH ]]; then
      W43_SESSION_PATH=$W43_UNIT_PATH
      W43_PATH_SOURCE=unit_process
    elif W43_UNIT_ENV=$(systemctl show "jupyter-$R1.service" -p Environment --value 2>/dev/null) &&
      W43_SESSION_PATH=$(printf '%s\n' "$W43_UNIT_ENV" | tr ' ' '\n' | sed -n 's/^PATH=//p' | head -1) &&
      [[ -n $W43_SESSION_PATH ]]; then
      W43_PATH_SOURCE=unit_env
    else
      W43_SESSION_PATH=/opt/tljh/user/bin:/bin:/usr/bin
      W43_PATH_SOURCE=fallback
      echo "UWAGA: nie udało się wyprowadzić PATH sesji $R1 z jednostki — używam fallbacku (#314)"
    fi
    export W43_SESSION_PATH
    expect_ok "PATH sesji wyprowadzony z realnego źródła (proces/jednostka sesji, nie stała, #314)" \
      test "$W43_PATH_SOURCE" != fallback
    # Asercje o REALNYM PATH sesji (nie o stałej): /usr/bin musi być, /usr/local/bin nie ma —
    # to właśnie fakt z #199/#202, który bramka ma egzekwować.
    # shellcheck disable=SC2016  # $W43_SESSION_PATH celowo rozwija wewnętrzny bash
    expect_ok "Realny PATH sesji zawiera /usr/bin (#314)" \
      bash -c 'case ":$W43_SESSION_PATH:" in *:/usr/bin:*) exit 0 ;; *) exit 1 ;; esac'
    # shellcheck disable=SC2016  # jw.
    expect_ok "Realny PATH sesji nie zawiera /usr/local/bin (fakt z jednostki, #199/#202)" \
      bash -c 'case ":$W43_SESSION_PATH:" in *:/usr/local/bin:*) exit 1 ;; *) exit 0 ;; esac'

    for w43_f in "${w43_tiles[@]}"; do
      expect_ok "Kafelek pulpitu: Exec istnieje i jest wykonywalny na PATH sesji (#314)" \
        w43_tile_ok "$w43_f"
    done

    # TEST NEGATYWNY: ta sama bramka na kopii kafelka z celowo zepsutym Exec musi zwrócić błąd.
    W43_TMP=$(mktemp -d) || ko "Kafelki Exec: nie można utworzyć katalogu tymczasowego (#314)"
    W43_BAD=$W43_TMP/wlb-zly.desktop
    # Fixture sedna #199: polecenie ISTNIEJE w /usr/local/bin (root je widzi), ale NIE ma go na
    # PATH sesji — kafelek z gołą nazwą MUSI dać FAIL; ta sama ścieżka absolutna MUSI przejść.
    W43_LOCAL=/usr/local/bin/wlb-314-tylko-lokalny
    printf '#!/bin/sh\nexit 0\n' >"$W43_LOCAL"
    chmod 755 "$W43_LOCAL"
    printf '[Desktop Entry]\nType=Application\nName=Test\nExec=wlb-314-tylko-lokalny %%F\n' >"$W43_BAD"
    expect_fail "Bramka odrzuca polecenie istniejące tylko w /usr/local/bin (sedno #199, #314)" \
      w43_tile_ok "$W43_BAD"
    printf '[Desktop Entry]\nType=Application\nName=Test\nExec=/usr/local/bin/wlb-314-tylko-lokalny\n' >"$W43_BAD"
    expect_ok "Bramka akceptuje ten sam cel przez ścieżkę absolutną (fixture, #314)" \
      w43_tile_ok "$W43_BAD"
    rm -f "$W43_LOCAL"
    printf '[Desktop Entry]\nType=Application\nName=Zły\nExec=wlb-nie-ma-takiego-314 %%F\n' >"$W43_BAD"
    expect_fail "Bramka wykrywa względny/nieistniejący Exec (test negatywny, #314)" \
      w43_tile_ok "$W43_BAD"
    printf '[Desktop Entry]\nType=Application\nName=Zły\nExec=/usr/local/bin/wlb-nie-ma-takiego-314\n' >"$W43_BAD"
    expect_fail "Bramka wykrywa absolutny nieistniejący Exec (test negatywny, #314)" \
      w43_tile_ok "$W43_BAD"
    rm -rf "$W43_TMP"
  fi
fi
