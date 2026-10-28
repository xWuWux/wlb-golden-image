# shellcheck shell=bash
echo "== AppArmor (CIS 1.6, #65) =="
expect_ok "AppArmor włączony (aa-enabled)" aa-enabled
expect_ok "apparmor=1 w parametrach jądra (GRUB)" grep -qw apparmor=1 /proc/cmdline
expect_ok "security=apparmor w parametrach jądra (GRUB)" grep -qw security=apparmor /proc/cmdline
# Parametry mają pochodzić z dropina o prefiksie 60-: 50- startowało do alfabetycznego wyścigu
# z 50-cloudimg-settings.cfg, a pozostawiony stary plik podwajał wpisy w cmdline jądra (#65).
expect_ok "Dropin GRUB 60-wlb-apparmor.cfg istnieje" test -f /etc/default/grub.d/60-wlb-apparmor.cfg
expect_ok "Stary dropin GRUB 50-wlb-apparmor.cfg usunięty" bash -c '! test -e /etc/default/grub.d/50-wlb-apparmor.cfg'
expect_ok "apparmor-utils zainstalowany (aa-enforce, aa-status)" command -v aa-enforce
# CIS 1.6.3: żaden profil nie może zostać w complain. Dystrybucyjne profile (m.in. transmission
# z bazowego pakietu `apparmor`) Ubuntu ładuje w complain — rola base musi je przełączyć na enforce.
# Licznik `aa-status --complaining` to autorytatywne, wersyjnie stabilne kryterium (#65, #157).
# NIE grepować `aa-status --verbose | grep "complain mode"` — ten wzorzec trafia wiersz-licznik
# „N profiles are in complain mode." także dla N=0, więc expect_fail oblewałby POPRAWNY obraz.
expect_ok "Licznik profili w complain = 0" test "$(aa-status --complaining)" = 0
# Dokładny tryb profilu (wlb-apparmor-mode), nie `grep rsyslogd | grep enforce`: ten drugi zalicza
# jednowierszowy JSON, gdzie rsyslogd jest unconfined, a "enforce" ma INNY profil w tej samej linii (#65).
# shellcheck disable=SC2016  # $() rozwija wewnętrzny bash (expect_ok uruchamia polecenie na VM)
expect_ok "Profil rsyslogd w trybie enforce (#6)" bash -c '[[ $(wlb-apparmor-mode rsyslogd) == enforce ]]'
