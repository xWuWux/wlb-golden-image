# shellcheck shell=bash
echo "== Raport użycia/pojemności sesji (#98) =="
expect_ok "Sampler użycia wykonywalny (#98)" test -x /opt/wlb/bin/wlb-usage-sampler
expect_ok "Rekord użycia wykonywalny (#98)" test -x /opt/wlb/bin/wlb-usage-record
expect_ok "Timer samplera włączony (#98)" systemctl is-enabled wlb-usage-sampler.timer
expect_ok "Katalog raportów 0750, nie dla badaczy (#98)" \
  bash -c "[ \"\$(stat -c %a /var/log/wlb/sessions)\" = 750 ]"
expect_fail "Badacz nie czyta raportów użycia (#98)" as $R1 ls /var/log/wlb/sessions
expect_ok "Reguła tmpfiles dla katalogu stanu (#98)" test -f /etc/tmpfiles.d/wlb-usage.conf
expect_fail "Katalog stanu korelacji nie do odczytu przez badacza (#98)" as $R1 ls /run/wlb/usage/sessions

# Nazwę jednostki bierzemy z rzeczywistości (TLJH: jupyter-<login>.service), nie ze szywu —
# stary test podstawiał fikcyjne "jupyter-<login>-singleuser.service.kv" i przez to jego
# zieloność maskowała samplera, który w produkcji nie łowi nic (#98).
UNIT=jupyter-$R1.service
NOW=$(date +%s)
mkdir -p /run/wlb/usage

cat >/tmp/wlb-98-verify.py <<'PY'
import glob, json, sys

sid, want = sys.argv[1], sys.argv[2]
recs = [
    json.loads(line)
    for path in sorted(glob.glob("/var/log/wlb/sessions/usage-*.jsonl"))
    for line in open(path, encoding="utf-8")
    if line.strip() and sid in line
]
if not recs:
    sys.exit(1)
r = recs[-1]
ok = r["status"] == want
if want == "complete":
    ok = ok and r["memory_peak_bytes"] == 1048576 and r["cpu_interval_max_cores"] == 0.5
if want == "no_samples":
    ok = (ok and r["memory_peak_bytes"] is None
          and "sample_from_other_boot" in r["quality"])
sys.exit(0 if ok else 1)
PY

printf 'Unit=%s\nBootID=%s\nInvocationID=inv-akceptacja\nSampledAtEpoch=%s\nMONO=%s\nMemoryPeak=1048576\nCPUUsageNSec=1000000000\nCPUIntervalMax=0.500000\n' \
  "$UNIT" "$(cat /proc/sys/kernel/random/boot_id)" "$NOW" "$NOW" >"/run/wlb/usage/$UNIT.kv"
/opt/wlb/bin/wlb-usage-record "$UNIT" testsession lab-test01 $((NOW - 60)) "$NOW" 60 spawner_env
expect_ok "Rekord complete: tozsama probka w oknie sesji, pelne wartosci (#98)" \
  python3 /tmp/wlb-98-verify.py testsession complete
expect_ok "Plik raportu 0640 od narodzin (#98)" \
  bash -c "[ \"\$(stat -c %a \"\$(ls /var/log/wlb/sessions/usage-*.jsonl | tail -1)\")\" = 640 ]"

# Samplera wlaczamy na zywo: jednostka serwera badacza musi zostac spróbkowana pod wlasciwa
# nazwą i z pelną tozsamością (BootID + InvocationID).
if systemctl is-active --quiet "$UNIT"; then
  rm -f "/run/wlb/usage/$UNIT.kv"
  systemctl start wlb-usage-sampler.service
  expect_ok "Sampler łowi rzeczywista jednostke serwera badacza (#98)" \
    test -s "/run/wlb/usage/$UNIT.kv"
  expect_ok "Probka niesie BootID i InvocationID (#98)" \
    bash -c "grep -q '^BootID=' '/run/wlb/usage/$UNIT.kv' && grep -qE '^InvocationID=.{8}' '/run/wlb/usage/$UNIT.kv'"
else
  skip "Samplera na zywej jednostce — serwer $R1 nieaktywny w tym punkcie akceptacji"
fi

# Próbka z innego bootu (reboot miedzy sesjami) nie moze podrobić rekordu wartosciami (#98).
printf 'Unit=%s\nBootID=inny-boot-id\nSampledAtEpoch=%s\nMemoryPeak=999999999\nCPUUsageNSec=1\n' \
  "$UNIT" "$NOW" >"/run/wlb/usage/$UNIT.kv"
/opt/wlb/bin/wlb-usage-record "$UNIT" testsession-stary lab-test01 $((NOW - 60)) "$NOW" 60 spawner_env
expect_ok "Probka z obcego bootu -> no_samples i null, nie zero udajace pomiar (#98)" \
  python3 /tmp/wlb-98-verify.py testsession-stary no_samples

rm -f /tmp/wlb-98-verify.py
