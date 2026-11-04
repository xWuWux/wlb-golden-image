# shellcheck shell=bash
# Sekcja adaptacyjna: tylko na flavorach z pulpitem (wlb-memory #106, wlb-radiologia #135).
# Kontrakt wizualny XFCE (#204): wartości efektywne czytane z /etc/wlb/desktop-contract
# (plik generowany z ansible/group_vars/all.yml) — test NIE duplikuje wartości.
# Kontrakt dotyczy profilu świeżego (decyzja #204): sprawdzamy scope systemowy (pusty HOME,
# tak jak konta badaczy useradd -M), profil ze skel i realne konto badacza; nadpiski
# użytkownika są dozwolone i dowiecione testem negatywnym na końcu.
if /opt/tljh/user/bin/python -c "import jupyter_remote_desktop_proxy" 2>/dev/null; then
  echo "== Pulpit: kontrakt wizualny XFCE (#204) =="
  CONTRACT=/etc/wlb/desktop-contract
  if expect_ok "Plik kontraktu /etc/wlb/desktop-contract obecny i niepusty (#204)" test -s "$CONTRACT"; then

    # w204_q HOME KANAŁ SCIEŻKA — wartość efektywna przez xfconf-query na izolowanym dbus,
    # tablice znormalizowane do "v1 v2 ..." (nagłówek "Value is an array..." odrzucany).
    w204_q() {
      HOME=$1 dbus-run-session -- xfconf-query -c "$2" -p "$3" 2>/dev/null |
        grep -vE '^Value is an array|^$' | tr '\n' ' ' | sed -e 's/ $//'
    }

    # w204_scope_ok HOME — rc=0 gdy KAŻDY wpis xfconf z kontraktu zgadza się w tym profilu.
    w204_scope_ok() {
      local h=$1 _kind chan path _typ val exp got rc=0
      while IFS='|' read -r _kind chan path _typ val; do
        exp=$(printf '%s' "$val" | tr ',' ' ')
        got=$(w204_q "$h" "$chan" "$path")
        if [ "$got" != "$exp" ]; then
          echo "  $chan $path => [$got] oczekiwano [$exp]" >&2
          rc=1
        fi
      done < <(grep '^xfconf|' "$CONTRACT")
      return "$rc"
    }

    W204_TMP=$(mktemp -d)
    W204_EMPTY=$W204_TMP/pusty
    W204_FRESH=$W204_TMP/skel
    mkdir -p "$W204_EMPTY" "$W204_FRESH"
    cp -a /etc/skel/. "$W204_FRESH"

    # Scope 1: pusty HOME = wartości efektywne konta bez żadnych plików użytkownika
    # (tak powstają konta badacza: useradd -M bez /etc/skel). To jest "świeży profil" platformy.
    expect_ok "Kontrakt xfconf: scope systemowy = wartości efektywne świeżego konta (#204)" \
      w204_scope_ok "$W204_EMPTY"
    # Scope 2: profil tworzony z /etc/skel (konta z useradd -m) — to samo drzewo źródłowe.
    expect_ok "Kontrakt xfconf: profil ze /etc/skel = wartości kontraktu (#204)" \
      w204_scope_ok "$W204_FRESH"
    # Scope 3: realne konto badacza (jeśli istnieje) — wartości efektywne "użytkowo".
    if getent passwd "jupyter-$R1" >/dev/null; then
      # Konto realnego badacza (tworzone useradd -M, bez plików profilu): odczyt po HOME
      # konta — wartości efektywne exactly takie, jakie zobaczy badacz przy pierwszym pulpicie.
      expect_ok "Kontrakt xfconf: profil badacza $R1 = wartości efektywne wg kontraktu (#204)" \
        w204_scope_ok "/workspace/jupyter-$R1"
    fi

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

    # Serwer X na geometrii z kontraktu: xdpyinfo + setxkbmap (layout wg kontraktu).
    W204_GEO=$(awk -F'|' '$1=="geometry" {print $3}' "$CONTRACT")
    W204_KBLAYOUT=$(awk -F'|' '$1=="keyboard" && $2=="layout" {print $3}' "$CONTRACT")
    if command -v Xtigervnc >/dev/null 2>&1; then
      Xtigervnc :98 -geometry "$W204_GEO" -depth 24 -SecurityTypes None \
        >/tmp/wlb204-xvnc.log 2>&1 &
      W204_XVNC=$!
      for _ in $(seq 1 30); do
        [ -S /tmp/.X11-unix/X98 ] && break
        sleep 0.5
      done
      expect_ok "Geometria sesji X = $W204_GEO wg kontraktu (xdpyinfo, #204)" \
        bash -c "DISPLAY=:98 xdpyinfo | grep -qE 'dimensions: *${W204_GEO} pixels'"
      expect_ok "Układ klawiatury X = $W204_KBLAYOUT wg kontraktu (setxkbmap, #204)" \
        bash -c "test \"\$( DISPLAY=:98 setxkbmap -query | awk '/^layout/{print \$2}' | tr -d ' ')\" = '$W204_KBLAYOUT'"

      # Krótka żywa sesja XFCE na pustym profilu: xfsettingsd (krzywa Xcursor z kontraktu
      # do xrdb), xfdesktop (tapeta pod monitorem VNC-0), motyw ikon na żywo.
      W204_CURSOR=$(awk -F'|' '$1=="xfconf" && $2=="xsettings" && $3=="/Gtk/CursorThemeName" {print $5}' "$CONTRACT")
      W204_ICONS=$(awk -F'|' '$1=="xfconf" && $2=="xsettings" && $3=="/Net/IconThemeName" {print $5}' "$CONTRACT")
      W204_COLOR=$(awk -F'|' '$1=="xfconf" && $2=="xfce4-desktop" && $3=="/backdrop/screen0/monitorVNC-0/workspace0/first-color" {print $5}' "$CONTRACT")
      # shellcheck disable=SC2016  # ścieżki i zmienne celowo rozwijane w sesji na VM
      expect_ok "Żywa sesja XFCE: Xcursor.theme=$W204_CURSOR (xrdb), ikony=$W204_ICONS, tapeta pod monitorVNC-0 (#204)" \
        bash -c "
          HOME='$W204_EMPTY' timeout --kill-after=10s 90s dbus-run-session -- bash -c '
            DISPLAY=:98 startxfce4 >/tmp/wlb204-session.log 2>&1 &
            sesja=\$!
            for i in \$(seq 1 40); do
              DISPLAY=:98 xrdb -query 2>/dev/null | grep -q \"Xcursor.theme:\\s*${W204_CURSOR}\" && break
              sleep 0.5
            done
            DISPLAY=:98 xrdb -query | grep -q \"Xcursor.theme:\\s*${W204_CURSOR}\" || exit 1
            xfconf-query -c xsettings -p /Net/IconThemeName 2>/dev/null | grep -qx \"${W204_ICONS}\" || exit 1
            xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorVNC-0/workspace0/first-color 2>/dev/null | grep -qx \"${W204_COLOR}\" || exit 1
            kill \$sesja 2>/dev/null
          '
        "
      kill "$W204_XVNC" 2>/dev/null
    else
      expect_ok "Regresja: Xtigervnc nieobecny na flavorze z pulpitem (#204)" false
    fi

    # Ikony launcherów: KAŻDY wlb-*.desktop musi mieć Icon= rozwiązywalne (brak = FAIL).
    w204_icon_ok() {
      local name=$1 theme=$2 d
      case $name in
        /*) [ -f "$name" ] ;;
      esac
      for d in /usr/share/icons/"$theme" /usr/share/icons/hicolor; do
        if find "$d" -maxdepth 5 \( -name "$name.png" -o -name "$name.svg" -o -name "$name.xpm" \) 2>/dev/null | grep -q .; then
          return 0
        fi
      done
      [ -f "/usr/share/pixmaps/$name.png" ] || [ -f "/usr/share/pixmaps/$name.xpm" ] ||
        [ -f "/usr/share/pixmaps/$name.svg" ]
    }
    W204_ICON_FAIL=0
    for W204_F in /usr/share/applications/wlb-*.desktop; do
      [ -e "$W204_F" ] || continue
      W204_ICON=$(awk -F= '/^Icon=/{print $2; exit}' "$W204_F")
      if [ -n "$W204_ICON" ] && w204_icon_ok "$W204_ICON" "$W204_ICONS"; then
        ok "Launcher $(basename "$W204_F"): Icon=$W204_ICON rozwiązywalna (#204)"
      else
        ko "Launcher $(basename "$W204_F"): Icon=${W204_ICON:-BRAK} nierozwiązywalna (#204)"
        W204_ICON_FAIL=1
      fi
    done
    [ "$W204_ICON_FAIL" -eq 0 ] || ko "Część launcherów wlb-* ma martwe ikony (#204)"

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
    # b) wartość usunięta: skasowanie wpisu /Xft/DPI w pliku profilu (typ "empty" kasuje wartość).
    W204_MISS=$W204_TMP/braki
    mkdir -p "$W204_MISS/.config/xfce4/xfconf/xfce-perchannel-xml"
    printf '%s\n' '<!DOCTYPE properties SYSTEM "xfdo-settings-1.0.dtd">' \
      '<channel name="xsettings" version="1.0">' \
      '  <property name="Xft" type="empty"><property name="DPI" type="empty"/></property>' \
      '</channel>' >"$W204_MISS/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml"
    expect_fail "Usunięta wartość /Xft/DPI nie jest raportowana jako zgodna (test negatywny, #204)" \
      bash -c "test \"\$( w204_q '$W204_MISS' xsettings /Xft/DPI )\" = \"\$( awk -F'|' '\$3==\"/Xft/DPI\" {print \$5}' '$CONTRACT' )\""
    # c) ikon nie ma — resolver musi powiedziec NIE (gwarancja, że "brak ikony = FAIL" nie jest puste).
    expect_fail "Nierozwiązywalna nazwa ikony jest odrzucana (test negatywny, #204)" \
      w204_icon_ok "wlb-ikona-nieistniejaca-xyz" "$W204_ICONS"

    rm -rf "$W204_TMP"
  fi
fi
