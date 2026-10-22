# shellcheck shell=bash
# Sekcja adaptacyjna: na wlb-memory sprawdza pulpit; na wlb-general pilnuje, że GUI NIE wyciekło do bazy.
echo "== Pulpit / flavor wlb-memory (#106) i regresja lekkości bazy (#105) =="
if /opt/tljh/user/bin/python -c "import jupyter_remote_desktop_proxy" 2>/dev/null; then
  expect_ok "Metadane: WLB_IMAGE_NAME=wlb-memory (#105)" grep -qx "WLB_IMAGE_NAME=wlb-memory" /etc/wlb/image-release
  expect_ok "XFCE na obrazie (startxfce4)" bash -c "command -v startxfce4"
  expect_ok "Serwer VNC na obrazie (TigerVNC)" \
    bash -c "command -v Xtigervnc || command -v tigervncserver || command -v vncserver"
  expect_ok "websockify na obrazie" bash -c "command -v websockify"
  expect_ok "Schowek VNC wyłączony — konfiguracja obecna (#106)" test -f /etc/tigervnc/vncserver-config-mandatory
else
  expect_fail "Regresja: obraz bazowy nie jest wlb-memory (#105)" grep -qx "WLB_IMAGE_NAME=wlb-memory" /etc/wlb/image-release
  expect_fail "Regresja: pulpit XFCE nieobecny w obrazie bazowym (#105)" bash -c "command -v startxfce4"
  expect_fail "Regresja: serwer VNC nieobecny w obrazie bazowym (#105)" bash -c "command -v Xtigervnc || command -v vncserver"
fi
