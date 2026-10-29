#!/usr/bin/env bats
# Testy jednostkowe samplera zasobów (#98) w piaskownicy z atrapa systemctl.
# Pilnuja: realnej nazwy jednostki (bez "-singleuser"), tozsamosci probki (BootID/InvocationID),
# odfiltrowania konwencji systemd („[not set]", UINT64_MAX) oraz ciaglosci miedzypróbkowej.

load helpers

setup() {
  setup_sandbox
  SAMP="$REPO_ROOT/ansible/roles/tljh/files/wlb-usage-sampler"
  export WLB_USAGE_RUN_DIR="$SANDBOX/run"
  export WLB_BOOT_ID_FILE="$SANDBOX/boot_id"
  export WLB_UPTIME_FILE="$SANDBOX/uptime"
  printf 'boot-AAA\n' >"$WLB_BOOT_ID_FILE"
  printf '100.00 50.00\n' >"$WLB_UPTIME_FILE"
  mkdir -p "$SANDBOX/props"
  # atrapa systemctl: list-units zwraca liste z pliku; show czyta wlaściwosci z props/<unit>.<PROP>
  cat >"$STUBS/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "systemctl $*" >>"$CALLS"
case $1 in
  list-units) cat "$STUB_UNITS" 2>/dev/null || true ;;
  show)
    unit=$2 prop=${4#-p} # -p PROP --value
    f="$WLB_ROOT/props/$unit.${prop#-p}"
    [[ -f $f ]] && cat "$f"
    exit 0
    ;;
esac
EOF
  chmod +x "$STUBS/systemctl"
  export STUB_UNITS="$SANDBOX/units"
  printf 'jupyter-tester1.service\n' >"$STUB_UNITS"
}

prop() { # prop JEDNOSTKA WLAŚCIWOSĆ ZAWARTOŚĆ
  printf '%s\n' "$3" >"$SANDBOX/props/$1.$2"
}

kv() { cat "$WLB_USAGE_RUN_DIR/$1.kv"; }

@test "aktywna jednostka: pelna tozsamosc probki i pomiar zapisane (#98)" {
  prop jupyter-tester1.service MemoryPeak 1048576
  prop jupyter-tester1.service CPUUsageNSec 5000000000
  prop jupyter-tester1.service InvocationID inv-1
  run "$SAMP"
  [ "$status" -eq 0 ]
  kv jupyter-tester1.service | grep -qx 'Unit=jupyter-tester1.service'
  kv jupyter-tester1.service | grep -qx 'BootID=boot-AAA'
  kv jupyter-tester1.service | grep -qx 'MemoryPeak=1048576'
  kv jupyter-tester1.service | grep -qx 'CPUUsageNSec=5000000000'
  kv jupyter-tester1.service | grep -qx 'InvocationID=inv-1'
}

@test "konwencje systemd ([not set], UINT64_MAX) to brak klucza, nie zero (#98)" {
  prop jupyter-tester1.service MemoryPeak '[not set]'
  prop jupyter-tester1.service CPUUsageNSec 18446744073709551615
  prop jupyter-tester1.service InvocationID inv-1
  run "$SAMP"
  [ "$status" -eq 0 ]
  refute bash -c "grep -q '^MemoryPeak=' '$WLB_USAGE_RUN_DIR/jupyter-tester1.service.kv'"
  refute bash -c "grep -q '^CPUUsageNSec=' '$WLB_USAGE_RUN_DIR/jupyter-tester1.service.kv'"
}

@test "ta sama instancja: CPUIntervalMax z delty; nowa instancja interval resetuje (#98)" {
  prop jupyter-tester1.service MemoryPeak 1
  prop jupyter-tester1.service InvocationID inv-1
  prop jupyter-tester1.service CPUUsageNSec 1000000000
  "$SAMP"
  kv jupyter-tester1.service | grep -qx 'CPUUsageNSec=1000000000'
  refute grep -q 'CPUIntervalMax' "$WLB_USAGE_RUN_DIR/jupyter-tester1.service.kv"

  printf '200.00 90.00\n' >"$WLB_UPTIME_FILE" # +100 s
  prop jupyter-tester1.service CPUUsageNSec 7000000000 # +6e9 ns w 100 s = 0.06 rdzenia
  "$SAMP"
  kv jupyter-tester1.service | grep -q 'CPUIntervalMax=0.060000'

  # restart jednostki: nowy InvocationID, skumulowany CPU padl — delta z inv-1 nie moze zostac
  prop jupyter-tester1.service InvocationID inv-2
  prop jupyter-tester1.service CPUUsageNSec 100000000
  "$SAMP"
  kv jupyter-tester1.service | grep -qx 'InvocationID=inv-2'
  refute grep -q 'CPUIntervalMax' "$WLB_USAGE_RUN_DIR/jupyter-tester1.service.kv"
}

@test "brak aktywnych jednostek: zadnych plikow i zadnego awaryjnego tmp (#98)" {
  : >"$STUB_UNITS"
  run "$SAMP"
  [ "$status" -eq 0 ]
  [ -z "$(ls -A "$WLB_USAGE_RUN_DIR" 2>/dev/null || true)" ]
}
