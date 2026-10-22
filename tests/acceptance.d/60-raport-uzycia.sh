# shellcheck shell=bash
echo "== Raport użycia/pojemności sesji (#98) =="
expect_ok "Sampler użycia wykonywalny (#98)" test -x /opt/wlb/bin/wlb-usage-sampler
expect_ok "Rekord użycia wykonywalny (#98)" test -x /opt/wlb/bin/wlb-usage-record
expect_ok "Timer samplera włączony (#98)" systemctl is-enabled wlb-usage-sampler.timer
expect_ok "Katalog raportów 0750, nie dla badaczy (#98)" \
  bash -c "[ \"\$(stat -c %a /var/log/wlb/sessions)\" = 750 ]"
expect_fail "Badacz nie czyta raportów użycia (#98)" as $R1 ls /var/log/wlb/sessions
mkdir -p /run/wlb/usage
printf 'MemoryPeak=1048576\nCPUUsageNSec=1000000000\n' >/run/wlb/usage/jupyter-tester1-singleuser.service.kv
/opt/wlb/bin/wlb-usage-record jupyter-tester1 testsession lab-test01 1760000000 1760000060 60
expect_ok "Rekord użycia zapisany do JSONL (#98)" \
  bash -c "grep -q '\"hub_session\":\"testsession\".*\"peak_memory_bytes\":1048576' /var/log/wlb/sessions/usage-*.jsonl"
