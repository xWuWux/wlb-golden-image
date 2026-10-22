# shellcheck shell=bash
echo "== AppArmor (CIS 1.6, #65) =="
expect_ok "AppArmor włączony (aa-enabled)" aa-enabled
expect_ok "apparmor=1 w parametrach jądra (GRUB)" grep -qw apparmor=1 /proc/cmdline
expect_ok "apparmor-utils zainstalowany (aa-enforce)" command -v aa-enforce
expect_ok "Żaden profil nie jest w trybie complain" test "$(aa-status --complaining)" = 0
expect_ok "Profil rsyslogd w trybie enforce (#6)" bash -c 'aa-status --json | grep -i rsyslogd | grep -qi enforce'
