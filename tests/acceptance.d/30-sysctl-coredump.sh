# shellcheck shell=bash
echo "== Utwardzenie jądra: sysctl i zrzuty pamięci (CIS 1.x/3.x, #63) =="
expect_ok "rp_filter=1 (#63)" test "$(sysctl -n net.ipv4.conf.all.rp_filter)" = 1
expect_ok "accept_source_route=0 (#63)" test "$(sysctl -n net.ipv4.conf.all.accept_source_route)" = 0
expect_ok "secure_redirects=0 (#63)" test "$(sysctl -n net.ipv4.conf.all.secure_redirects)" = 0
expect_ok "log_martians=1 (#63)" test "$(sysctl -n net.ipv4.conf.all.log_martians)" = 1
expect_ok "tcp_syncookies=1 (#63)" test "$(sysctl -n net.ipv4.tcp_syncookies)" = 1
expect_ok "icmp_echo_ignore_broadcasts=1 (#63)" test "$(sysctl -n net.ipv4.icmp_echo_ignore_broadcasts)" = 1
expect_ok "IPv6 accept_ra=0 (#63)" test "$(sysctl -n net.ipv6.conf.all.accept_ra)" = 0
expect_ok "IPv6 forwarding=0 (#63)" test "$(sysctl -n net.ipv6.conf.all.forwarding)" = 0
expect_ok "fs.suid_dumpable=0 (#63)" test "$(sysctl -n fs.suid_dumpable)" = 0
expect_ok "Twardy limit core=0 w limits.d (#63)" grep -qxE '\* +hard +core +0' /etc/security/limits.d/60-wlb-coredump.conf
expect_ok "systemd-coredump Storage=none (#63)" grep -qx 'Storage=none' /etc/systemd/coredump.conf.d/60-wlb.conf
