# Zarządzane przez Ansible (rola desktop). Tylko warstwa pulpitu (flavory) — baza wlb-general
# zostaje headless i tego pliku nie dostaje.
#
# Wskazujemy jupyter-remote-desktop-proxy nasz xstartup, który eksportuje XAUTHORITY do
# potomków sesji, żeby natywne apki GUI (LibreOffice Calc/Writer) mogły otworzyć display (#278).
# jrdp czyta tę zmienną ze środowiska serwera badacza (ten sam mechanizm, którego używa test #44).
c = get_config()  # noqa: F821

c.Spawner.environment.update(
    {"JUPYTER_REMOTE_DESKTOP_PROXY_XSTARTUP": "/opt/wlb/desktop/wlb-desktop-xstartup"}
)
