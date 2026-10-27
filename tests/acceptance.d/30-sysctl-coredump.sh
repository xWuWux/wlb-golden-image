# shellcheck shell=bash
echo "== Utwardzenie jądra: sysctl i zrzuty pamięci (#63) =="
# Niezależny kontrakt oczekiwanych wartości, nie odczyt konfiguracji jako oczekiwania.
# Błąd sysctl też musi dać FAIL (nawet jeśli polecenie wypisało oczekiwaną wartość).
# check_sysctl KEY EXPECTED: dwa napisy; kod 0 tylko po poprawnym odczycie i zgodności.
check_sysctl() {
  local actual
  actual=$(sysctl -n "$1") || return 1
  [[ $actual == "$2" ]]
}
while read -r key expected; do
  expect_ok "$key=$expected (#63)" check_sysctl "$key" "$expected"
done <<'SYSCTL'
kernel.dmesg_restrict 1
kernel.kptr_restrict 2
kernel.yama.ptrace_scope 1
net.ipv4.ip_forward 0
net.ipv4.conf.all.accept_redirects 0
net.ipv4.conf.default.accept_redirects 0
net.ipv6.conf.all.accept_redirects 0
net.ipv4.conf.all.send_redirects 0
net.ipv4.conf.default.send_redirects 0
net.ipv4.conf.all.rp_filter 1
net.ipv4.conf.default.rp_filter 1
net.ipv4.conf.all.accept_source_route 0
net.ipv4.conf.default.accept_source_route 0
net.ipv4.conf.all.secure_redirects 0
net.ipv4.conf.default.secure_redirects 0
net.ipv4.conf.all.log_martians 1
net.ipv4.conf.default.log_martians 1
net.ipv4.tcp_syncookies 1
net.ipv4.icmp_echo_ignore_broadcasts 1
net.ipv4.icmp_ignore_bogus_error_responses 1
net.ipv6.conf.all.accept_ra 0
net.ipv6.conf.default.accept_ra 0
net.ipv6.conf.all.forwarding 0
net.ipv6.conf.all.accept_source_route 0
net.ipv6.conf.default.accept_source_route 0
fs.protected_hardlinks 1
fs.protected_symlinks 1
fs.protected_fifos 2
fs.protected_regular 2
fs.suid_dumpable 0
SYSCTL

expect_ok "Twardy limit core=0 w limits.d (#63)" grep -qxE '\* +hard +core +0' /etc/security/limits.d/60-wlb-coredump.conf
expect_ok "systemd-coredump Storage=none (#63)" grep -qx 'Storage=none' /etc/systemd/coredump.conf.d/60-wlb.conf
expect_ok "systemd-coredump ProcessSizeMax=0 (#63)" grep -qx 'ProcessSizeMax=0' /etc/systemd/coredump.conf.d/60-wlb.conf
