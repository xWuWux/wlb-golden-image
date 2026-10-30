# shellcheck shell=bash
echo "== Zagregowane metryki stanu WLB (#22) =="
expect_ok "Timer wlb-health włączony (#22)" systemctl is-enabled --quiet wlb-health.timer
expect_ok "Timer wlb-health działa (#22)" systemctl is-active --quiet wlb-health.timer
expect_ok "Pomiar wlb-health kończy się poprawnie (#22)" systemctl start wlb-health.service
expect_ok "Kolejka eksportu poprawnie zmierzona (#22)" bash -c \
  "curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:9100/metrics | grep -qx 'wlb_health_queue_collect_success 1'"
expect_ok "Pliki kolejki SIEM poprawnie zmierzone (#22)" bash -c \
  "curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:9100/metrics | grep -qx 'wlb_health_siem_spool_collect_success 1'"
expect_ok "Świeża próbka wlb-health (#22)" bash -c \
  "v=\$(awk '\$1 == \"wlb_health_timestamp_seconds\" {print \$2}' /var/lib/wlb-node-exporter/wlb-health.prom); [[ \$v =~ ^[0-9]+\$ ]] && (( \$(date +%s) - v < 180 ))"
