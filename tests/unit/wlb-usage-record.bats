#!/usr/bin/env bats
# Testy jednostkowe rekordu użycia sesji (#98) w piaskownicy.
# Kontrakt v1: zer udają tylko poprawny pomiar; brak to null + status/powód.
# Próbka musi pasować bootem i oknem czasowym sesji — dziedzictwo metryk po poprzedniej
# sesji tego samego badacza jest odrzucane (patrz przegląd #98).

load helpers

setup() {
  setup_sandbox
  REC="$REPO_ROOT/ansible/roles/tljh/files/wlb-usage-record"
  export WLB_USAGE_RUN_DIR="$SANDBOX/run"
  export WLB_USAGE_OUT_DIR="$SANDBOX/out"
  export WLB_BOOT_ID_FILE="$SANDBOX/boot_id"
  printf 'boot-piaskownica\n' >"$WLB_BOOT_ID_FILE"
  mkdir -p "$WLB_USAGE_RUN_DIR"
  OUT="$WLB_USAGE_OUT_DIR/usage-$(date -u +%Y%m%d).jsonl"
  NOW=$(date +%s)
}

# write_kv JEDNOSTKA BootID Znacznik_Czasu [MemoryPeak= CPU= ITV=]
write_kv() {
  local unit=$1 boot=$2 ts=$3
  shift 3
  {
    printf 'Unit=%s\nBootID=%s\nInvocationID=inv-1\nSampledAtEpoch=%s\nMONO=100\n' "$unit" "$boot" "$ts"
    printf '%s\n' "$@"
  } >"$WLB_USAGE_RUN_DIR/$unit.kv"
}

rec_field() { # rec_field KLUCZ — wartosć pola z jedynego rekordu (JSON, nie grep tekstu)
  python3 - "$OUT" "$1" <<'PY'
import json, sys
rec = json.loads(open(sys.argv[1], encoding="utf-8").read().strip())
print(rec[sys.argv[2]])
PY
}

@test "spójna próbka tej samej sesji -> rekord complete z pelnymi danymi (#98)" {
  write_kv jupyter-tester1.service boot-piaskownica "$NOW" \
    'MemoryPeak=10737418240' 'CPUUsageNSec=4520500000000' 'CPUIntervalMax=1.500000'
  run "$REC" jupyter-tester1.service deadbeef lab-test01 $((NOW - 600)) "$NOW" 600 spawner_env
  [ "$status" -eq 0 ]
  [ "$(rec_field status)" = complete ]
  [ "$(stat -c %a "$OUT")" = 640 ] # plik raportu 0640 — bez odczytu przez badacza
  [ "$(rec_field memory_peak_bytes)" = 10737418240 ]
  [ "$(rec_field cpu_time_seconds)" = 4520.5 ]
  [ "$(rec_field hub_session)" = deadbeef ]
  [ "$(rec_field unit)" = jupyter-tester1.service ]
  [ "$(rec_field user)" = jupyter-tester1 ]
  [ "$(rec_field duration_seconds)" = 600 ]
}

@test "brak próbki -> no_samples i null, nigdy zero udające pomiar (#98)" {
  run "$REC" jupyter-tester2.service cafe lab-x $((NOW - 60)) "$NOW" 60 spawner_env
  [ "$status" -eq 0 ]
  [ "$(rec_field status)" = no_samples ]
  [ "$(rec_field memory_peak_bytes)" = None ]
  [ "$(rec_field cpu_time_seconds)" = None ]
  [ "$(rec_field sample)" = None ]
}

@test "próbka z innego bootu jest odrzucana (nie przezywa reboota jako 'nasza') (#98)" {
  write_kv jupyter-tester3.service boot-przed-rebootem "$NOW" 'MemoryPeak=999'
  run "$REC" jupyter-tester3.service beef lab-y $((NOW - 60)) "$NOW" 60 spawner_env
  [ "$(rec_field status)" = no_samples ]
  python3 - "$OUT" <<'PY'
import json, sys
rec = json.loads(open(sys.argv[1], encoding="utf-8").read().strip())
assert "sample_from_other_boot" in rec["quality"], rec["quality"]
assert rec["memory_peak_bytes"] is None
PY
}

@test "próbka spoza okna sesji -> odrzucona z powodem (dziedzictwo po poprzedniej sesji) (#98)" {
  write_kv jupyter-tester4.service boot-piaskownica $((NOW - 7200)) \
    'MemoryPeak=4242' 'CPUUsageNSec=1'
  run "$REC" jupyter-tester4.service f00d lab-z $((NOW - 60)) "$NOW" 60 spawner_env
  [ "$(rec_field status)" = no_samples ]
  python3 - "$OUT" <<'PY'
import json, sys
rec = json.loads(open(sys.argv[1], encoding="utf-8").read().strip())
assert "sample_outside_session_window" in rec["quality"], rec["quality"]
PY
}

@test "UINT64_MAX i [not set] to brak pomiaru, nie rozmiar (#98)" {
  write_kv jupyter-tester5.service boot-piaskownica "$NOW" \
    'MemoryPeak=[not set]' 'CPUUsageNSec=18446744073709551615'
  run "$REC" jupyter-tester5.service aa lab-w $((NOW - 60)) "$NOW" 60 spawner_env
  [ "$(rec_field memory_peak_bytes)" = None ]
  [ "$(rec_field cpu_time_seconds)" = None ]
  [ "$(rec_field status)" = partial ] # próbka nasza (boot+okno), ale wartosci nie do uzycia
}

@test "niepoprawny czas trwania -> duration null, status partial (#98)" {
  write_kv jupyter-tester6.service boot-piaskownica "$NOW" \
    'MemoryPeak=1' 'CPUUsageNSec=1'
  run "$REC" jupyter-tester6.service bb lab-v $((NOW - 30)) "$NOW" xx spawner_env
  [ "$(rec_field duration_seconds)" = None ]
  python3 - "$OUT" <<'PY'
import json, sys
rec = json.loads(open(sys.argv[1], encoding="utf-8").read().strip())
assert rec["status"] == "partial"
assert "duration_unavailable" in rec["quality"]
PY
}

@test "cudzolow i polskie znaki w lab nie psuja JSON — rekord caly sie parsuje (#98)" {
  run "$REC" jupyter-tester7.service cc 'ła"b\ux00' $((NOW - 5)) "$NOW" 5 hub_env
  [ "$status" -eq 0 ]
  python3 - "$OUT" <<'PY'
import json, sys
rec = json.loads(open(sys.argv[1], encoding="utf-8").read().strip())
assert rec["lab"] == 'ła"b\\ux00'
assert rec["lab_source"] == "hub_env"
PY
}

@test "zle uzycie (za malo argumentow) konczy sie 2 bez zapisu (#98)" {
  run "$REC" jupyter-tester8.service
  [ "$status" -eq 2 ]
  [ ! -e "$OUT" ]
}
