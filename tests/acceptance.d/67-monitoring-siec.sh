# shellcheck shell=bash
echo "== Ekspozycja metryk dla sieci monitoringu (#22) =="
# Prawdziwa próba sieciowa niezależna od lab.env Laboratorium testowego: dwa źródła w osobnych
# przestrzeniach sieciowych połączone z VM przez veth (ruch wchodzi interfejsem veth, nie lo, więc
# przechodzi przez łańcuch input zapory). Dozwolone źródło musi pobrać /metrics, drugie nie może się
# połączyć; to samo po przeładowaniu zapory, po wyłączeniu i po przerwanym wyłączeniu. Na końcu
# przywracamy stan z lab.env (w teście: brak ekspozycji).
MON_OK_VM=198.51.100.1 MON_OK_SRC=198.51.100.2 MON_NO_VM=198.51.100.5 MON_NO_SRC=198.51.100.6
mon_pids=()
mon_netns() { # NAZWA ADRES_VM ADRES_ŹRÓDŁA — wypisuje PID procesu trzymającego przestrzeń sieciową
  local pid
  unshare -n sleep 900 >/dev/null 2>&1 &
  pid=$!
  sleep 0.3
  ip link add "wlbm-$1" type veth peer name "wlbm-$1-p" &&
    ip link set "wlbm-$1-p" netns "$pid" &&
    ip addr add "$2/30" dev "wlbm-$1" && ip link set "wlbm-$1" up &&
    nsenter -t "$pid" -n ip addr add "$3/30" dev "wlbm-$1-p" &&
    nsenter -t "$pid" -n ip link set "wlbm-$1-p" up &&
    nsenter -t "$pid" -n ip link set lo up || return 1
  echo "$pid"
}
mon_scrape() { # PID ADRES_VM — czy źródło pobiera metryki VM
  nsenter -t "$1" -n curl --noproxy '*' -fsS --max-time 3 "http://$2:9100/metrics" | grep -q '^node_cpu_seconds_total'
}
mon_loop_only() {
  [ "$(ss -H -ltn 'sport = :9100' | awk '{print $4}')" = "127.0.0.1:9100" ]
}
mon_exposed() {
  ss -H -ltn 'sport = :9100' | awk '{print $4}' | grep -qxE '(\*|0\.0\.0\.0):9100'
}
mon_hub_rule() {
  nft list chain inet wlb input | grep -qE 'tcp dport (80|\{ 80, 443 \}) accept'
}
if pid_ok=$(mon_netns ok "$MON_OK_VM" "$MON_OK_SRC") && pid_no=$(mon_netns no "$MON_NO_VM" "$MON_NO_SRC"); then
  mon_pids=("$pid_ok" "$pid_no")
  ok "Środowisko próby sieciowej: dwa źródła przez veth (#22)"
  expect_fail "Domyślnie: dozwolone źródło nie pobiera metryk (#22)" mon_scrape "$pid_ok" "$MON_OK_VM"

  expect_ok "wlb-monitoring apply $MON_OK_SRC/32 (#22)" wlb-monitoring apply "$MON_OK_SRC/32"
  expect_ok "Dozwolone źródło pobiera /metrics (#22)" mon_scrape "$pid_ok" "$MON_OK_VM"
  expect_fail "Inne źródło nie łączy się z 9100 (#22)" mon_scrape "$pid_no" "$MON_NO_VM"
  expect_ok "Port 9100 dopuszczony tylko w łańcuchu monitoring_in (#22)" bash -c \
    "[ \"\$(nft list ruleset | grep -c 'dport 9100')\" -eq 1 ] && nft list chain inet wlb monitoring_in | grep -q 'ip saddr $MON_OK_SRC tcp dport 9100 accept'"
  expect_ok "Włączenie nie zmienia dostępu do huba (reguła i odpowiedź) (#22)" bash -c \
    "$(declare -f mon_hub_rule); mon_hub_rule && curl -sf -o /dev/null '$HUB/hub/api'"
  expect_ok "Efektywna komenda eksportera: 0.0.0.0 + flagi z obrazu (#22)" bash -c \
    "a=\$(ps -o args= -C prometheus-node-exporter); [[ \$a == *--web.listen-address=0.0.0.0:9100* && \$a == *--collector.textfile.directory=/var/lib/wlb-node-exporter* ]]"

  # restart zapory (PartOf): eksporter zatrzymywany przed zrzuceniem reguł i startowany po nich
  expect_ok "Restart zapory: reguła odtworzona z include (#22)" systemctl restart nftables
  expect_ok "Po restarcie zapory eksporter działa (#22)" systemctl is-active --quiet prometheus-node-exporter.service
  expect_ok "Po restarcie zapory dozwolone źródło pobiera (#22)" mon_scrape "$pid_ok" "$MON_OK_VM"
  expect_fail "Po restarcie zapory inne źródło odrzucane (#22)" mon_scrape "$pid_no" "$MON_NO_VM"

  # utrata ochrony zamyka nasłuch: stop zapory zatrzymuje eksporter, a guard nie pozwala go uruchomić
  systemctl stop nftables
  expect_fail "Stop zapory zatrzymuje eksporter poza pętlą (#22)" systemctl is-active --quiet prometheus-node-exporter.service
  expect_fail "Bez zapory eksporter poza pętlą nie startuje (guard) (#22)" systemctl start prometheus-node-exporter.service
  expect_fail "Bez zapory nic nie słucha poza pętlą (#22)" mon_exposed
  systemctl start nftables
  systemctl start prometheus-node-exporter.service
  expect_ok "Po powrocie zapory ekspozycja wraca (#22)" mon_scrape "$pid_ok" "$MON_OK_VM"

  expect_ok "wlb-monitoring disable (#22)" wlb-monitoring disable
  expect_fail "Po wyłączeniu dozwolone źródło traci dostęp (#22)" mon_scrape "$pid_ok" "$MON_OK_VM"
  expect_ok "Po wyłączeniu nasłuch tylko na pętli (#22)" mon_loop_only
  expect_fail "Po wyłączeniu brak reguły 9100 w rulesecie (#22)" bash -c "nft list ruleset | grep -q 'dport 9100'"

  # przerwane wyłączenie: override usunięty, proces nadal słucha na 0.0.0.0 — ponowienie naprawia stan
  wlb-monitoring apply "$MON_OK_SRC/32" >/dev/null
  rm -f /etc/systemd/system/prometheus-node-exporter.service.d/20-wlb-monitoring.conf
  expect_ok "Symulacja przerwanego wyłączenia: proces poza pętlą (#22)" mon_exposed
  expect_ok "Ponowione disable naprawia stan (#22)" wlb-monitoring disable
  expect_ok "Po naprawie nasłuch tylko na pętli (#22)" mon_loop_only

  expect_fail "Niekanoniczny zakres jest odrzucany bez zmian (#22)" wlb-monitoring apply 0.0.0.0/1
  expect_ok "Po odrzuceniu nadal tylko pętla (#22)" mon_loop_only
else
  ko "Środowisko próby sieciowej: dwa źródła przez veth (#22) — brak veth/netns w obrazie?"
fi
# sprzątanie i stan z lab.env (w teście bez MONITORING_CIDR = brak ekspozycji)
for p in "${mon_pids[@]}"; do kill "$p" 2>/dev/null; done
ip link del wlbm-ok 2>/dev/null
ip link del wlbm-no 2>/dev/null
mon_cidr=$(sed -n 's/^MONITORING_CIDR=//p' /etc/wlb/lab.env | head -1 | tr -d '"')
if [[ -n $mon_cidr ]]; then wlb-monitoring apply "$mon_cidr" >/dev/null; else wlb-monitoring disable >/dev/null; fi
