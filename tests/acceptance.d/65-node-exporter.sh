# shellcheck shell=bash
echo "== Metryki systemowe (#22) =="
expect_ok "node_exporter włączony (#22)" systemctl is-enabled prometheus-node-exporter.service
expect_ok "node_exporter działa (#22)" systemctl is-active --quiet prometheus-node-exporter.service
expect_ok "Metryki dostępne lokalnie (#22)" bash -c \
  "curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:9100/metrics | grep -q '^node_cpu_seconds_total'"
# MONITORING_CIDR zdejmuje ograniczenie do pętli: eksporter słucha na wszystkich interfejsach,
# a zapora dopuszcza port 9100 tylko z jednego źródła scrape'a (#22). Bez zmiennej zostaje pętla,
# więc test adaptuje się do konfiguracji Laboratorium, zamiast wymagać jednego wariantu.
mon_cidr=$(sed -n 's/^MONITORING_CIDR=//p' /etc/wlb/lab.env | head -1 | tr -d '"')
if [[ -n $mon_cidr ]]; then
  # nft normalizuje /32 do nagiego adresu, więc dopasowujemy obie postaci.
  mon_re=$(printf '%s' "${mon_cidr%/32}" | sed 's/\./\\./g')
  expect_ok "nftables: metryki tylko z MONITORING_CIDR na 9100 (#22)" bash -c \
    "nft list ruleset | grep -qE 'ip saddr ${mon_re}(/32)? tcp dport 9100 accept'"
  expect_ok "node_exporter słucha poza pętlą (#22)" bash -c \
    "ss -H -ltn 'sport = :9100' | awk '{print \$4}' | grep -qxE '(\\*|0\\.0\\.0\\.0):9100'"
  expect_ok "override eksportera pochodzi z firstboot (#22)" bash -c \
    "grep -q -- '--web.listen-address=0.0.0.0:9100' /etc/systemd/system/prometheus-node-exporter.service.d/20-wlb-monitoring.conf"
else
  expect_ok "node_exporter nasłuchuje tylko na IPv4 loopback (#22)" bash -c \
    "ss -H -ltn 'sport = :9100' | awk '{print \$4}' | grep -qx '127.0.0.1:9100' && [ \"\$(ss -H -ltn 'sport = :9100' | wc -l)\" -eq 1 ]"
  expect_ok "brak ekspozycji metryk bez MONITORING_CIDR (#22)" bash -c \
    "[ ! -e /etc/systemd/system/prometheus-node-exporter.service.d/20-wlb-monitoring.conf ]"
fi
expect_fail "Badacz nie może zapisać metryk (#22)" as "$R1" touch /var/lib/wlb-node-exporter/proba.prom
