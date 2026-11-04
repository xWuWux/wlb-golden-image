# shellcheck shell=bash
# #204: wyłącznie na VM testowej. Profile syntetyczne w jednostce tymczasowej.
w204_test_desktop() {
  local CONTRACT=/etc/wlb/desktop-contract
  if ! test -s "$CONTRACT"; then
    ko "Brak kontraktu pulpitu (#204)"
    return 1
  fi

  # w204_q HOME KANAŁ ŚCIEŻKA — wartość efektywna przez xfconf-query na izolowanym dbus,
  # tablice znormalizowane do "v1 v2 ..." (nagłówek "Value is an array..." odrzucany).
  w204_q() {
    LC_ALL=C HOME=$1 XDG_CONFIG_HOME=$1/.config dbus-run-session -- xfconf-query -c "$2" -p "$3" 2>/dev/null |
      awk 'NF && !/^Value is an array/ {printf "%s%s", sep, $0; sep=" "}'
  }

  # w204_scope_ok HOME — rc=0 gdy KAŻDY wpis xfconf z kontraktu zgadza się w tym profilu.
  # shellcheck disable=SC2329 # przekazywana do expect_ok/expect_fail
  w204_scope_ok() {
    local h=$1 _kind chan path typ val exp got rc=0 n=0
    while IFS='|' read -r _kind chan path typ val; do
      n=$((n + 1))
      exp=$val
      # tylko tablice mają wartości rozdzielone przecinkiem (xfconf-query drukuje je wierszami)
      case $typ in array_*) exp=$(printf '%s' "$val" | tr ',' ' ') ;; esac
      if ! got=$(w204_q "$h" "$chan" "$path"); then
        echo "  brak odczytu $chan $path" >&2
        rc=1
        continue
      fi
      if [ "$got" != "$exp" ]; then
        echo "  $chan $path => [$got] oczekiwano [$exp]" >&2
        rc=1
      fi
    done < <(grep '^xfconf|' "$CONTRACT")
    # pusty kontrakt xfconf nie może przechodzić jako „zgodny"
    [ "$n" -gt 0 ] || rc=1
    return "$rc"
  }

  expect_ok "Kontrakt ma znacznik wersji contract|version (#204)" \
    grep -qE '^contract\|version\|[0-9]+$' "$CONTRACT"

  W204_TMP=$(mktemp -d) || return 1
  export HOME=$W204_TMP/pusty XDG_RUNTIME_DIR=$W204_TMP/runtime
  mkdir -m 700 "$XDG_RUNTIME_DIR" || return 1
  W204_EMPTY=$W204_TMP/pusty
  W204_FRESH=$W204_TMP/skel
  mkdir -p "$W204_EMPTY" "$W204_FRESH"
  cp -R /etc/skel/. "$W204_FRESH"

  # Scope 1: pusty HOME = wartości efektywne konta bez żadnych plików użytkownika
  # (tak powstają konta badacza: useradd -M bez /etc/skel). To jest "świeży profil" platformy.
  expect_ok "Kontrakt xfconf: scope systemowy = wartości efektywne świeżego konta (#204)" \
    w204_scope_ok "$W204_EMPTY"
  expect_fail "Odczyt brakującej właściwości kończy się błędem (#204)" \
    w204_q "$W204_EMPTY" xsettings /WLB/MissingProperty204
  # Scope 2: profil tworzony z /etc/skel (konta z useradd -m) — to samo drzewo źródłowe.
  expect_ok "Kontrakt xfconf: profil ze /etc/skel = wartości kontraktu (#204)" \
    w204_scope_ok "$W204_FRESH"
  # Locale: kontrakt kontra faktyczna wartość domyślna systemu + dostępność locale.
  W204_LOCALE=$(awk -F'|' '$1=="locale" && $2=="LANG" {print $3}' "$CONTRACT")
  expect_ok "Locale domyślna (LANG) zgodna z kontraktem: $W204_LOCALE (#204)" \
    grep -qxF "LANG=$W204_LOCALE" /etc/default/locale
  # shellcheck disable=SC2016  # LANG celowo rozwijane w bash -c na VM
  expect_ok "Locale $W204_LOCALE działa (locale charmap = UTF-8) (#204)" \
    bash -c "test \"\$( LANG='$W204_LOCALE' locale charmap )\" = UTF-8"

  # Fonty: fc-match aliasów z kontraktu musi dawać przypisaną rodzinę.
  W204_SANS=$(awk -F'|' '$1=="font" && $2=="sans" {print $3}' "$CONTRACT")
  W204_MONO=$(awk -F'|' '$1=="font" && $2=="mono" {print $3}' "$CONTRACT")
  expect_ok "fc-match Sans = $W204_SANS wg kontraktu (#204)" \
    bash -c "test \"\$( fc-match -f '%{family}' Sans | cut -d, -f1 )\" = '$W204_SANS'"
  expect_ok "fc-match Monospace = $W204_MONO wg kontraktu (#204)" \
    bash -c "test \"\$( fc-match -f '%{family}' Monospace | cut -d, -f1 )\" = '$W204_MONO'"

  # Serwer X BEZ jawnej geometrii (default Xtigervnc = geometria sesji, której nie nadpisuje
  # proxy): xdpyinfo i setxkbmap muszą dać wartości kontraktu (geometria, rules/model/layout).
  W204_GEO=$(awk -F'|' '$1=="geometry" {print $3}' "$CONTRACT")
  W204_GEO_W=${W204_GEO%x*}
  W204_GEO_H=${W204_GEO#*x}
  W204_KBRULES=$(awk -F'|' '$1=="keyboard" && $2=="rules" {print $3}' "$CONTRACT")
  W204_KBMODEL=$(awk -F'|' '$1=="keyboard" && $2=="model" {print $3}' "$CONTRACT")
  W204_KBLAYOUT=$(awk -F'|' '$1=="keyboard" && $2=="layout" {print $3}' "$CONTRACT")
  W204_ICONS=$(awk -F'|' '$1=="xfconf" && $2=="xsettings" && $3=="/Net/IconThemeName" {print $5}' "$CONTRACT")
  if command -v Xtigervnc >/dev/null 2>&1; then
    # wolny numer wyświetlacza (bez kolizji z cudzymi blokadami X)
    W204_N=98
    while [ -e "/tmp/.X11-unix/X$W204_N" ] || [ -e "/tmp/.X$W204_N-lock" ]; do W204_N=$((W204_N + 1)); done
    W204_DISP=:$W204_N
    Xtigervnc "$W204_DISP" -depth 24 -localhost yes -SecurityTypes None \
      >"$W204_TMP/xvnc.log" 2>&1 &
    W204_XVNC=$!
    for _ in $(seq 1 30); do
      [ -S "/tmp/.X11-unix/X$W204_N" ] && break
      sleep 0.5
    done
    expect_ok "Serwer X wystartował na $W204_DISP (#204)" test -S "/tmp/.X11-unix/X$W204_N"
    expect_ok "Geometria sesji X = $W204_GEO wg kontraktu (xdpyinfo, #204)" \
      bash -c "DISPLAY=$W204_DISP xdpyinfo | grep -qE 'dimensions: *${W204_GEO} pixels'"
    for W204_K in rules:"$W204_KBRULES" model:"$W204_KBMODEL" layout:"$W204_KBLAYOUT"; do
      expect_ok "Klawiatura X: ${W204_K%%:*} = ${W204_K#*:} wg kontraktu (setxkbmap, #204)" \
        bash -c "test \"\$( DISPLAY=$W204_DISP setxkbmap -query | awk '/^${W204_K%%:*}:/{print \$2}' )\" = '${W204_K#*:}'"
    done

    # Krótka żywa sesja XFCE na pustym profilu: xfsettingsd (Xcursor i Xft.dpi z kontraktu
    # do xrdb), xfdesktop (tapeta SOLID pod monitorem VNC-0), motyw ikon i panel przy dolnej krawędzi.
    W204_CURSOR=$(awk -F'|' '$1=="xfconf" && $2=="xsettings" && $3=="/Gtk/CursorThemeName" {print $5}' "$CONTRACT")
    W204_DPIVAL=$(awk -F'|' '$1=="xfconf" && $2=="xsettings" && $3=="/Xft/DPI" {print $5}' "$CONTRACT")
    W204_COLOR=$(awk -F'|' '$1=="xfconf" && $2=="xfce4-desktop" && $3=="/backdrop/screen0/monitorVNC-0/workspace0/first-color" {print $5}' "$CONTRACT")
    W204_CSTYLE=$(awk -F'|' '$1=="xfconf" && $2=="xfce4-desktop" && $3=="/backdrop/screen0/monitorVNC-0/workspace0/color-style" {print $5}' "$CONTRACT")
    cat >"$W204_TMP/sesja.sh" <<EOSESJA
export DISPLAY=$W204_DISP
startxfce4 >"$W204_TMP/session.log" 2>&1 &
sesja=\$!
for i in \$(seq 1 60); do
xrdb -query 2>/dev/null | grep -q "Xft.dpi:[[:space:]]*${W204_DPIVAL}\$" && xwininfo -root -tree 2>/dev/null | grep -q '"xfce4-panel".* [0-9]*x[0-9]*+0+[0-9]* ' && break
sleep 0.5
done
rc=0
xrdb -query | grep -q "Xcursor.theme:[[:space:]]*${W204_CURSOR}\$" || { echo "xrdb Xcursor.theme"; rc=1; }
xrdb -query | grep -q "Xft.dpi:[[:space:]]*${W204_DPIVAL}\$" || { echo "xrdb Xft.dpi"; rc=1; }
xfconf-query -c xsettings -p /Net/IconThemeName 2>/dev/null | grep -qx "${W204_ICONS}" || { echo "ikony"; rc=1; }
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorVNC-0/workspace0/first-color 2>/dev/null | grep -qx "${W204_COLOR}" || { echo "tapeta first-color"; rc=1; }
xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorVNC-0/workspace0/color-style 2>/dev/null | grep -qx "${W204_CSTYLE}" || { echo "tapeta color-style"; rc=1; }
# panel na całej szerokości, dolna krawędź okna = dolna krawędź ekranu
xwininfo -root -tree | awk -v W=${W204_GEO_W} -v H=${W204_GEO_H} '
/"xfce4-panel"/ { for (i = 1; i <= NF; i++) if (\$i ~ /^[0-9]+x[0-9]+\+/) { split(\$i, g, /[x+]/); if (g[1] == W && substr(\$NF, 1) ~ /^\+[0-9]+\+[0-9]+\$/) { split(\$NF, p, "+"); if (p[3] + g[2] == H) f = 1 } } }
END { exit !f }' || { echo "panel nie przy dolnej krawędzi"; rc=1; }
kill \$sesja 2>/dev/null
exit \$rc
EOSESJA
    expect_ok "Żywa sesja XFCE: Xcursor=$W204_CURSOR, Xft.dpi=$W204_DPIVAL (xrdb), ikony=$W204_ICONS, tapeta SOLID pod monitorVNC-0, panel przy dolnej krawędzi (#204)" \
      bash -c "HOME='$W204_EMPTY' XDG_CONFIG_HOME='$W204_EMPTY/.config' timeout --kill-after=10s 120s dbus-run-session -- bash '$W204_TMP/sesja.sh' >'$W204_TMP/sesja.out' 2>&1"
    [ ! -s "$W204_TMP/sesja.out" ] || grep -v dbus-daemon "$W204_TMP/sesja.out" | sed 's/^/    sesja: /' >&2
    kill "$W204_XVNC" 2>/dev/null
    wait "$W204_XVNC" 2>/dev/null
  else
    expect_ok "Regresja: Xtigervnc nieobecny na flavorze z pulpitem (#204)" false
  fi

  # Ikony launcherów: KAŻDY .desktop z Icon= musi być rozwiązywalny (brak = FAIL).
  w204_icon_ok() {
    local name=$1 theme=$2 d
    case $name in
      /*)
        [ -f "$name" ]
        return
        ;;
    esac
    for d in /usr/share/icons/"$theme" /usr/share/icons/hicolor; do
      if find "$d" -maxdepth 5 \( -name "$name.png" -o -name "$name.svg" -o -name "$name.xpm" \) 2>/dev/null | grep -q .; then
        return 0
      fi
    done
    [ -f "/usr/share/pixmaps/$name.png" ] || [ -f "/usr/share/pixmaps/$name.xpm" ] ||
      [ -f "/usr/share/pixmaps/$name.svg" ]
  }
  # Na wlb-radiologia kafelki FSLeyes/FSL/Slicer są WYMAGANE (brak pliku = FAIL, nie pominięcie).
  if grep -qx "WLB_IMAGE_NAME=wlb-radiologia" /etc/wlb/image-release 2>/dev/null; then
    for W204_REQ in wlb-fsleyes wlb-fsl wlb-slicer; do
      expect_ok "Kafelek $W204_REQ.desktop obecny na wlb-radiologia (#204)" \
        test -f "/usr/share/applications/$W204_REQ.desktop"
    done
  fi
  # KAŻDY launcher z Icon= (wlb-* i stockowe) musi mieć rozwiązywalną ikonę (brak = FAIL).
  W204_ICON_FAIL=0
  W204_ICON_N=0
  for W204_F in /usr/share/applications/*.desktop; do
    [ -e "$W204_F" ] || continue
    W204_ICON=$(awk -F= '/^Icon=/{print $2; exit}' "$W204_F")
    # launchery bez Icon= pomijamy tylko poza wlb-* (nasze kafelki muszą mieć ikonę)
    if [ -z "$W204_ICON" ]; then
      case $(basename "$W204_F") in wlb-*) ;; *) continue ;; esac
    fi
    W204_ICON_N=$((W204_ICON_N + 1))
    if [ -n "$W204_ICON" ] && w204_icon_ok "$W204_ICON" "$W204_ICONS"; then
      ok "Launcher $(basename "$W204_F"): Icon=$W204_ICON rozwiązywalna (#204)"
    else
      ko "Launcher $(basename "$W204_F"): Icon=${W204_ICON:-BRAK} nierozwiązywalna (#204)"
      W204_ICON_FAIL=1
    fi
  done
  [ "$W204_ICON_FAIL" -eq 0 ] || ko "Część launcherów ma martwe ikony (#204)"
  [ "$W204_ICON_N" -gt 0 ] || ko "Brak jakichkolwiek launcherów z Icon= do sprawdzenia (#204)"

  # --- Testy negatywne: mechanizm MUSI wykryć zmianę/usunięcie wartości --------------
  # a) zmieniona wartość: nadpisanie motywu w pliku profilu (dokumentuje, że kontrakt
  #    nie jest egzekwowany siłą — i że test INI wywalił się na rzeczywistej zmianie).
  W204_BAD=$W204_TMP/zmieniony
  mkdir -p "$W204_BAD/.config/xfce4/xfconf/xfce-perchannel-xml"
  cp "$W204_FRESH/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml" \
    "$W204_BAD/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml"
  sed -i 's/value="Adwaita"/value="ZmienionyMotyw"/' \
    "$W204_BAD/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml"
  expect_fail "Zmieniona wartość motywu NIE przechodzi kontraktu (test negatywny, #204)" \
    w204_scope_ok "$W204_BAD"
  # b) nadpisana wartość liczbowa (DPI=120 w profilu) — kontrakt musi to wykryć.
  #    (Plik użytkownika z type="empty" NIE kasuje wartości systemowej — xfconf spada do /etc/xdg.)
  W204_DPI=$W204_TMP/dpi
  mkdir -p "$W204_DPI/.config/xfce4/xfconf/xfce-perchannel-xml"
  printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
    '<channel name="xsettings" version="1.0">' \
    '  <property name="Xft" type="empty"><property name="DPI" type="int" value="120"/></property>' \
    '</channel>' >"$W204_DPI/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml"
  expect_fail "Nadpisane /Xft/DPI=120 NIE przechodzi kontraktu (test negatywny, #204)" \
    w204_scope_ok "$W204_DPI"
  # ...ale nadpisanie badacza jest RESPEKTOWANE (kontrakt = domyślne, nie lockdown; decyzja #204).
  expect_ok "Nadpisanie badacza (DPI=120) jest respektowane przez xfconf (#204)" \
    test "$(w204_q "$W204_DPI" xsettings /Xft/DPI)" = 120
  # c) ikon nie ma — resolver musi powiedziec NIE (gwarancja, że "brak ikony = FAIL" nie jest puste).
  expect_fail "Nierozwiązywalna nazwa ikony jest odrzucana (test negatywny, #204)" \
    w204_icon_ok "wlb-ikona-nieistniejaca-xyz" "$W204_ICONS"

  rm -rf "$W204_TMP"
}

if grep -qxE 'WLB_IMAGE_NAME=wlb-(memory|radiologia)' /etc/wlb/image-release; then
  echo "== Pulpit: kontrakt wizualny XFCE (#204) =="
  if {
    declare -f ok ko expect_ok expect_fail summary w204_test_desktop
    printf '%s\n' 'set -uo pipefail' 'PASS=0 FAIL=0 SKIP=0' 'w204_test_desktop && summary'
  } | systemd-run --wait --pipe --collect --quiet \
    -p DynamicUser=yes -p PrivateNetwork=yes -p PrivateTmp=yes \
    -p ProtectHome=yes -p ProtectSystem=strict -p NoNewPrivileges=yes \
    -p 'InaccessiblePaths=-/workspace -/projekt -/data-mart -/sluza-in -/sluza-out -/sluza-odrzucone' \
    -p RuntimeMaxSec=10min /bin/bash -s; then
    ok "Kontrakt pulpitu w izolowanej sesji (#204)"
  else
    ko "Kontrakt pulpitu lub izolacja sesji (#204)"
  fi
fi
