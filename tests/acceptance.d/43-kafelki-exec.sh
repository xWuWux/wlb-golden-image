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
#   4. cel musi istnieć i być wykonywalny; wrapper WLB (/usr/local/bin, /opt/wlb/bin) musi wskazywać
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
    # PATH sesji wyprowadzamy z REALNEGO środowiska PROCESU serwera badacza (/proc/<MainPID>/environ):
    # to dokładnie to, co dziedziczy jrdp → Xtigervnc → dbus-launch → xfce4-session → Exec kafelka.
    # NIE przez `in_unit`/sudo: sudo dokłada secure_path z /usr/local/bin, więc mierzyliśmy złą
    # warstwę i fałszywie „wykrywaliśmy" /usr/local/bin, którego sesja pulpitu nie ma (#199/#315).
    # Fallback: Environment= jednostki, potem stała z ostrzeżeniem (nigdy udawane „odtworzenie").
    W43_PATH_SOURCE=""
    W43_UNIT="jupyter-$R1.service"
    w43_main_pid=$(systemctl show "$W43_UNIT" -p MainPID --value 2>/dev/null || true)
    if [[ $w43_main_pid =~ ^[0-9]+$ && $w43_main_pid -gt 0 && -r /proc/$w43_main_pid/environ ]]; then
      W43_SESSION_PATH=$(tr '\0' '\n' <"/proc/$w43_main_pid/environ" 2>/dev/null |
        sed -n 's/^PATH=//p' | head -1)
      [[ -n $W43_SESSION_PATH ]] && W43_PATH_SOURCE=unit_process_environ
    fi
    if [[ -z $W43_PATH_SOURCE ]]; then
      W43_UNIT_ENV=$(systemctl show "$W43_UNIT" -p Environment --value 2>/dev/null || true)
      W43_SESSION_PATH=$(printf '%s\n' "$W43_UNIT_ENV" | tr ' ' '\n' | sed -n 's/^PATH=//p' | head -1)
      [[ -n $W43_SESSION_PATH ]] && W43_PATH_SOURCE=unit_env
    fi
    if [[ -z $W43_PATH_SOURCE ]]; then
      W43_SESSION_PATH=/opt/tljh/user/bin:/bin:/usr/bin
      W43_PATH_SOURCE=fallback
      echo "UWAGA: nie udało się wyprowadzić PATH sesji $R1 — używam fallbacku (#314)"
    fi
    export W43_SESSION_PATH
    expect_ok "PATH sesji wyprowadzony z realnego środowiska procesu serwera/jednostki (#314)" \
      test "$W43_PATH_SOURCE" != fallback
    # shellcheck disable=SC2016  # $W43_SESSION_PATH celowo rozwija wewnętrzny bash
    expect_ok "Realny PATH sesji zawiera /usr/bin (#314)" \
      bash -c 'case ":$W43_SESSION_PATH:" in *:/usr/bin:*) exit 0 ;; *) exit 1 ;; esac'
    # Premisa #199 (brak /usr/local/bin) bywa flavor-specific: gdy realny PATH sesji go zawiera,
    # nie udajemy FAIL — bramka i tak rozwiązuje Exec względem REALNEGO PATH, a fixture #199
    # (polecenie tylko w /usr/local/bin) traci sens na tym obrazie. Dokumentujemy to jawnie.
    # shellcheck disable=SC2016  # jw.
    if bash -c 'case ":$W43_SESSION_PATH:" in *:/usr/local/bin:*) exit 0 ;; *) exit 1 ;; esac'; then
      w43_has_localbin=1
      echo "UWAGA: realny PATH sesji $R1 zawiera /usr/local/bin — premisa #199 flavor-specific;" \
        "bramka używa realnego PATH, fixture #199 pominięty (#314)"
    else
      w43_has_localbin=0
      expect_ok "Realny PATH sesji nie zawiera /usr/local/bin (fakt z warstwy jrdp, #199/#202)" true
    fi

    for w43_f in "${w43_tiles[@]}"; do
      expect_ok "Kafelek pulpitu: Exec istnieje i jest wykonywalny na PATH sesji (#314)" \
        w43_tile_ok "$w43_f"
    done

    # TEST NEGATYWNY: ta sama bramka na kopii kafelka z celowo zepsutym Exec musi zwrócić błąd.
    W43_TMP=$(mktemp -d) || ko "Kafelki Exec: nie można utworzyć katalogu tymczasowego (#314)"
    W43_BAD=$W43_TMP/wlb-zly.desktop
    # Fixture sedna #199 (tylko gdy premisa zachodzi): polecenie ISTNIEJE w /usr/local/bin
    # (root je widzi), ale NIE ma go na PATH sesji — goła nazwa MUSI dać FAIL; ta sama ścieżka
    # absolutna MUSI przejść.
    if [ "$w43_has_localbin" -eq 0 ]; then
      W43_LOCAL=/usr/local/bin/wlb-314-tylko-lokalny
      # Skrypt-wrappery WLB mają linię `exec`; bez niej bramka słusznie uzna cel za nieistniejący.
      printf '#!/bin/sh\nexec /bin/true "$@"\n' >"$W43_LOCAL"
      chmod 755 "$W43_LOCAL"
      printf '[Desktop Entry]\nType=Application\nName=Test\nExec=wlb-314-tylko-lokalny %%F\n' >"$W43_BAD"
      expect_fail "Bramka odrzuca polecenie istniejące tylko w /usr/local/bin (sedno #199, #314)" \
        w43_tile_ok "$W43_BAD"
      printf '[Desktop Entry]\nType=Application\nName=Test\nExec=/usr/local/bin/wlb-314-tylko-lokalny\n' >"$W43_BAD"
      expect_ok "Bramka akceptuje ten sam cel przez ścieżkę absolutną (fixture, #314)" \
        w43_tile_ok "$W43_BAD"
      rm -f "$W43_LOCAL"
    else
      skip "Fixture #199: PATH sesji zawiera /usr/local/bin na tym flavorze — premisa flavor-specific (#314)"
    fi
    printf '[Desktop Entry]\nType=Application\nName=Zły\nExec=wlb-nie-ma-takiego-314 %%F\n' >"$W43_BAD"
    expect_fail "Bramka wykrywa względny/nieistniejący Exec (test negatywny, #314)" \
      w43_tile_ok "$W43_BAD"
    printf '[Desktop Entry]\nType=Application\nName=Zły\nExec=/usr/local/bin/wlb-nie-ma-takiego-314\n' >"$W43_BAD"
    expect_fail "Bramka wykrywa absolutny nieistniejący Exec (test negatywny, #314)" \
      w43_tile_ok "$W43_BAD"
    rm -rf "$W43_TMP"
  fi
fi
