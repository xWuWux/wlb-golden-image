#!/usr/bin/env bats
# Testy jednostkowe rekordu użycia sesji (#98) w piaskownicy.

load helpers

setup() {
  setup_sandbox
  REC="$REPO_ROOT/ansible/roles/tljh/files/wlb-usage-record"
  export WLB_USAGE_RUN_DIR="$SANDBOX/run"
  export WLB_USAGE_OUT_DIR="$SANDBOX/out"
  mkdir -p "$WLB_USAGE_RUN_DIR"
  OUT="$WLB_USAGE_OUT_DIR/usage-$(date -u +%Y%m%d).jsonl"
}

@test "rekord łączy czasy z hooka ze szczytem zasobów z próbki (#98)" {
  printf 'MemoryPeak=10737418240\nCPUUsageNSec=4520500000000\n' \
    >"$WLB_USAGE_RUN_DIR/jupyter-tester1-singleuser.service.kv"
  run "$REC" jupyter-tester1 deadbeef lab-test01 1760000000 1760012600 12600
  [ "$status" -eq 0 ]
  [ -f "$OUT" ]
  run cat "$OUT"
  [[ "$output" == *'"hub_session":"deadbeef"'* ]]
  [[ "$output" == *'"user":"jupyter-tester1"'* ]]
  [[ "$output" == *'"lab":"lab-test01"'* ]]
  [[ "$output" == *'"duration_seconds":12600'* ]]
  [[ "$output" == *'"peak_memory_bytes":10737418240'* ]]
  [[ "$output" == *'"cpu_time_seconds":4520.500'* ]]
}

@test "brak próbki szczytu -> zera, rekord nadal poprawny (#98)" {
  run "$REC" jupyter-tester2 cafe lab-x 1760000000 1760000060 60
  [ "$status" -eq 0 ]
  run cat "$OUT"
  [[ "$output" == *'"peak_memory_bytes":0'* ]]
  [[ "$output" == *'"cpu_time_seconds":0.000'* ]]
  [[ "$output" == *'"duration_seconds":60'* ]]
}

@test "niepoprawne wartości liczbowe sprowadzane do zera (#98)" {
  printf 'MemoryPeak=[not set]\nCPUUsageNSec=\n' \
    >"$WLB_USAGE_RUN_DIR/jupyter-tester3-singleuser.service.kv"
  run "$REC" jupyter-tester3 beef lab-y 1760000000 1760000030 xx
  [ "$status" -eq 0 ]
  run cat "$OUT"
  [[ "$output" == *'"peak_memory_bytes":0'* ]]
  [[ "$output" == *'"duration_seconds":0'* ]]
}
