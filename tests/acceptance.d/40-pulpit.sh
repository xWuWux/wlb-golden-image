# shellcheck shell=bash
# Sekcja adaptacyjna: na flavorach z pulpitem (wlb-memory #106, wlb-radiologia #135, wlb-histologia #108)
# sprawdza pulpit; na wlb-general pilnuje, że GUI NIE wyciekło do bazy (regresja lekkości, #105).
echo "== Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135, wlb-histologia #108) i lekkość bazy (#105) =="
if /opt/tljh/user/bin/python -c "import jupyter_remote_desktop_proxy" 2>/dev/null; then
  expect_ok "Metadane: flavor z pulpitem wlb-memory/wlb-radiologia/wlb-histologia (#105, #135, #108)" \
    grep -qxE 'WLB_IMAGE_NAME=wlb-(memory|radiologia|histologia)' /etc/wlb/image-release
  expect_ok "XFCE na obrazie (startxfce4)" bash -c "command -v startxfce4"
  expect_ok "Serwer VNC na obrazie (TigerVNC)" \
    bash -c "command -v Xtigervnc || command -v tigervncserver || command -v vncserver"
  expect_ok "websockify na obrazie" bash -c "command -v websockify"
  # AppArmor warstwy pulpitu (#65): rola desktop wymusza enforce PO swoich pakietach — sprawdzamy nie
  # tylko obecność skryptu, ale realny stan po jego przebiegu (idempotentnym, bez fałszywego zielonego).
  expect_ok "Skrypt AppArmor enforce warstwy pulpitu na obrazie (#65)" \
    test -x /usr/local/sbin/wlb-apparmor-enforce
  # shellcheck disable=SC2016  # $() i <<< celowo rozwijane w wewnętrznym bash -c, nie tu
  expect_ok "Warstwa pulpitu kończy się licznikiem AppArmor complain = 0 (#65, CIS 1.6.3)" bash -c '
    out=$(/usr/local/sbin/wlb-apparmor-enforce) || exit 1
    grep -q "^WLB_SWITCHED=[01]$" <<<"$out" || exit 1
    [[ $(aa-status --complaining) == 0 ]]
  '
  expect_ok "Konfiguracja TigerVNC ma poprawną składnię Perla (#106)" \
    perl -c /etc/tigervnc/vncserver-config-mandatory
  # Znak dolara jest częścią sprawdzanej konfiguracji Perla.
  # shellcheck disable=SC2016
  expect_ok "Schowek VNC: polityka wrappera wyłącza odbiór (#106)" \
    grep -qxF '$AcceptCutText = 0;' /etc/tigervnc/vncserver-config-mandatory
  # shellcheck disable=SC2016
  expect_ok "Schowek VNC: polityka wrappera wyłącza wysyłanie (#106)" \
    grep -qxF '$SendCutText = 0;' /etc/tigervnc/vncserver-config-mandatory
else
  expect_fail "Regresja: obraz bazowy nie ma pulpitu (wlb-memory/wlb-radiologia/wlb-histologia, #105)" \
    grep -qxE 'WLB_IMAGE_NAME=wlb-(memory|radiologia|histologia)' /etc/wlb/image-release
  expect_fail "Regresja: pulpit XFCE nieobecny w obrazie bazowym (#105)" bash -c "command -v startxfce4"
  expect_fail "Regresja: serwer VNC nieobecny w obrazie bazowym (#105)" bash -c "command -v Xtigervnc || command -v vncserver"
fi
