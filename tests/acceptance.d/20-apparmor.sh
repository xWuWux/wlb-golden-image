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
expect_ok "Licznik profili w complain = 0" test "$(aa-status --complaining)" = 0
# Nagłówki „0 profiles/processes are in complain mode." są zawsze; liczy się tylko wpis pod nagłówkiem profili.
expect_fail "Zaden profil nie jest w trybie complain (lista)" bash -c "aa-status --verbose | awk '/^[0-9]+ profiles are in complain mode/{f=1;next} /^[0-9]/{f=0} f' | grep -q ."
expect_ok "Profil rsyslogd w trybie enforce (#6)" bash -c 'aa-status --json | grep -i rsyslogd | grep -qi enforce'
expect_fail "Profil rsyslogd nie jest w trybie complain (#6)" bash -c 'aa-status --verbose | grep -i "rsyslogd.*complain mode"'
