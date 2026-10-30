# shellcheck shell=bash
echo "== Metryki systemowe (#22) =="
expect_ok "node_exporter włączony (#22)" systemctl is-enabled prometheus-node-exporter.service
expect_ok "node_exporter działa (#22)" systemctl is-active --quiet prometheus-node-exporter.service
expect_ok "Metryki dostępne lokalnie (#22)" bash -c \
  "curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:9100/metrics | grep -q '^node_cpu_seconds_total'"
expect_ok "node_exporter nasłuchuje tylko na IPv4 loopback (#22)" bash -c \
  "ss -H -ltn 'sport = :9100' | awk '{print \$4}' | grep -qx '127.0.0.1:9100' && [ \"\$(ss -H -ltn 'sport = :9100' | wc -l)\" -eq 1 ]"
expect_fail "Badacz nie może zapisać metryk (#22)" as "$R1" touch /var/lib/wlb-node-exporter/proba.prom
