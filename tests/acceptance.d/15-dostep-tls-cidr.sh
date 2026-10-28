# shellcheck shell=bash
# Dostęp do huba/SSH na AKTYWNYM rulesecie + rzeczywista odpowiedź huba: wymuszony CIDR i warunkowy
# TLS huba (#18/IMG-005). Sprawdzamy ruch filtrowany przez jądro (nft list ruleset), dokładny CIDR i
# port oraz faktyczne HTTPS/redirect — nie plik konfiguracyjny ani regułę pasującą do dowolnego portu.
echo "== Dostęp: wymuszony CIDR + TLS huba (#18) =="

# Oczekiwane wartości z kontraktu administratora (lab.env), nie odczyt konfiguracji jako oczekiwania.
hub_cidr=$(sed -n 's/^[[:space:]]*HUB_ALLOWED_CIDR=//p' /etc/wlb/lab.env | tr -d '"' | head -1)
ssh_cidr=$(sed -n 's/^[[:space:]]*ADMIN_SSH_CIDR=//p' /etc/wlb/lab.env | tr -d '"' | head -1)
hub_tls=1
grep -qE '^[[:space:]]*HUB_TLS=0[[:space:]]*$' /etc/wlb/lab.env && hub_tls=0

ruleset=$(nft list ruleset)
in_ruleset() { grep -qE "$1" <<<"$ruleset"; } # dokładny wzorzec na aktywnym rulesecie w jądrze
re() { printf '%s' "${1//./\\.}"; }           # kropki jako literały w ERE

expect_ok "Polityka wejścia: drop (#18)" in_ruleset 'hook input .*policy drop'
expect_fail "nftables: brak 0.0.0.0/0 w aktywnym rulesecie (#18)" in_ruleset '0\.0\.0\.0/0'
expect_ok "nftables: SSH tylko z ADMIN_SSH_CIDR na porcie 22 (#18)" \
  in_ruleset "ip saddr $(re "$ssh_cidr") tcp dport 22 accept"

if [[ $hub_tls == 1 ]]; then
  expect_ok "nftables: hub z HUB_ALLOWED_CIDR na 80 i 443 (TLS, #18)" \
    in_ruleset "ip saddr $(re "$hub_cidr") tcp dport \{ 80, 443 \} accept"
  # 443 nasłuchuje i odpowiada po HTTPS z weryfikacją CA + nazwy serwera — bez -k (cert ma SAN localhost).
  expect_ok "Hub odpowiada po HTTPS na 443 z zaufanym certem (#18)" \
    curl -sf --cacert /etc/wlb/hub-ca.pem -o /dev/null https://localhost/hub/api
  # Weryfikacja jest realna: bez zaufanej CA połączenie pada (nie jest obchodzone -k).
  expect_fail "HTTPS bez zaufanej CA jest odrzucone (#18)" \
    curl -sf --cacert /dev/null -o /dev/null https://localhost/hub/api
  # Port 80 przekierowuje na HTTPS (traefik), nie serwuje huba po jawnym tekście.
  redirect_to_https() {
    local code loc
    code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost/hub/api)
    loc=$(curl -s -o /dev/null -w '%{redirect_url}' http://localhost/hub/api)
    [[ $code == 30[0-9] && $loc == https://* ]]
  }
  expect_ok "HTTP na 80 przekierowuje na HTTPS (#18)" redirect_to_https
else
  expect_ok "nftables: hub z HUB_ALLOWED_CIDR tylko na 80 (HUB_TLS=0, #18)" \
    in_ruleset "ip saddr $(re "$hub_cidr") tcp dport 80 accept"
  expect_fail "443 nie jest otwarte przy HUB_TLS=0 (#18)" in_ruleset 'dport 443'
fi
