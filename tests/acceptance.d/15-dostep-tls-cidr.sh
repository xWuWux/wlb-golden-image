# shellcheck shell=bash
# Dostęp do huba/SSH: wymuszony zakres źródłowy (CIDR) i warunkowy port TLS (#18/IMG-005).
echo "== Dostęp: wymuszony CIDR + TLS huba (#18) =="

# Fail-secure CIDR: firstboot odmawia pracy bez zakresu i odrzuca 0.0.0.0/0; w nftables jest realny CIDR.
expect_ok "nftables: brak 0.0.0.0/0 (wymuszony CIDR, #18)" bash -c '! grep -q "0.0.0.0/0" /etc/nftables.conf'
expect_ok "nftables: dostęp do huba z konkretnego HUB_ALLOWED_CIDR" \
  grep -qE 'ip saddr [0-9.]+/[0-9]+ tcp dport' /etc/nftables.conf
expect_ok "nftables: SSH administratora z ADMIN_SSH_CIDR (dport 22)" \
  grep -qE 'ip saddr [0-9.]+/[0-9]+ tcp dport 22 accept' /etc/nftables.conf

# TLS huba: porty zależą od HUB_TLS. W teście HUB_TLS=0 (dev HTTP) → 80 otwarte, 443 NIE.
# Walidacja HUB_TLS=1 (443 nasłuchuje, https, 80 przekierowuje) — #18 inkrement 2.
expect_ok "Hub po HTTP w teście (HUB_TLS=0): port 80 otwarty" \
  grep -qE 'tcp dport (80|\{ 80)' /etc/nftables.conf
expect_fail "443 nie jest otwarte przy HUB_TLS=0 (port warunkowy, #18)" grep -q '443' /etc/nftables.conf
