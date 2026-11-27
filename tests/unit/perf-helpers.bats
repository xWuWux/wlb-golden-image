#!/usr/bin/env bats
# Testy helperów pomiarów wydajności etapu 6a (#10): median, perf_vm_resources.

load helpers

# _mk_cgroot — świeży katalog pełniący rolę korzenia cgroup w teście (WLB_CGROUP_ROOT).
_mk_cgroot() {
  mkdir -p "$BATS_TEST_TMPDIR/cg"
  echo "$BATS_TEST_TMPDIR/cg"
}
# _mk_meminfo MEMTOTAL_MB — plik /proc/meminfo z zadanym MemTotal (WLB_MEMINFO), bez zależności od hosta.
_mk_meminfo() {
  printf 'MemTotal:       %d kB\n' "$(($1 * 1024))" >"$BATS_TEST_TMPDIR/meminfo"
  echo "$BATS_TEST_TMPDIR/meminfo"
}
# _cgroot_env KORZEŃ MEMINFO — ustawia hooki testowe perf_vm_resources. Eksport w ZWYKŁEJ funkcji (nie
# @test), więc shellcheck nie modeluje go jako podpowłoki @bats (brak SC2030/SC2031), a rozdzielenie od
# command substitution unika SC2155. Zmienne i tak żyją tylko w ramach danego @testu (izolacja bats).
_cgroot_env() {
  export WLB_CGROUP_ROOT="$1"
  export WLB_MEMINFO="$2"
}

@test "median: nieparzysta liczba próbek to wartość środkowa (#10)" {
  source "$REPO_ROOT/tests/lib/remote-common.sh"
  [ "$(median 30 10 20)" -eq 20 ]
}

@test "median: parzysta liczba próbek — średnia dwóch środkowych (#10)" {
  source "$REPO_ROOT/tests/lib/remote-common.sh"
  [ "$(median 40 10 30 20)" = "25.000" ]
  [ "$(median 15 10)" = "12.500" ]
}

@test "median: jedna próbka (#10)" {
  source "$REPO_ROOT/tests/lib/remote-common.sh"
  [ "$(median 7)" -eq 7 ]
}

@test "median: brak próbek zwraca błąd (#10)" {
  source "$REPO_ROOT/tests/lib/remote-common.sh"
  run median
  [ "$status" -ne 0 ]
}

@test "perf_vm_resources: respektuje podane VM_CPUS/VM_MEMORY (#10)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  VM_CPUS=2 VM_MEMORY=4096
  perf_vm_resources
  [ "$VM_CPUS" -eq 2 ]
  [ "$VM_MEMORY" -eq 4096 ]
}

@test "perf_vm_resources: bez wartości — czapka 4 vCPU / 8192 MB wyliczona z hosta (#10)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  unset VM_CPUS VM_MEMORY
  perf_vm_resources
  [ "$VM_CPUS" -ge 1 ]
  [ "$VM_CPUS" -le 4 ]
  [ -n "$VM_MEMORY" ]
  [ "$VM_MEMORY" -ge 1024 ]
  [ "$VM_MEMORY" -le 8192 ]
}

@test "perf_vm_resources: cgroup v2 cpu.max 200000/100000 -> 2 vCPU (#10/#384)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  cg=$(_mk_cgroot)
  echo "200000 100000" >"$cg/cpu.max"
  _cgroot_env "$cg" "$(_mk_meminfo 16384)"
  unset VM_CPUS VM_MEMORY
  perf_vm_resources
  [ "$VM_CPUS" -eq 2 ]
}

@test "perf_vm_resources: cgroup v2 cpu.max 'max' -> fallback nproc (#10/#384)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  nproc() { echo 3; } # stub: host ma 3 vCPU, cgroup bez limitu
  cg=$(_mk_cgroot)
  echo "max 100000" >"$cg/cpu.max"
  _cgroot_env "$cg" "$(_mk_meminfo 16384)"
  unset VM_CPUS VM_MEMORY
  perf_vm_resources
  [ "$VM_CPUS" -eq 3 ]
}

@test "perf_vm_resources: cgroup v1 cfs_quota/period zaokrągla w górę (1.5 -> 2) (#10/#384)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  cg=$(_mk_cgroot)
  mkdir -p "$cg/cpu"
  echo 150000 >"$cg/cpu/cpu.cfs_quota_us"
  echo 100000 >"$cg/cpu/cpu.cfs_period_us"
  _cgroot_env "$cg" "$(_mk_meminfo 16384)"
  unset VM_CPUS VM_MEMORY
  perf_vm_resources
  [ "$VM_CPUS" -eq 2 ]
}

@test "perf_vm_resources: memory.max < MemTotal -> VM_MEMORY = limit - 2560 (#10/#384)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  cg=$(_mk_cgroot)
  echo $((6144 * 1024 * 1024)) >"$cg/memory.max" # 6144 MiB, host 32 GiB
  _cgroot_env "$cg" "$(_mk_meminfo 32768)"
  unset VM_CPUS VM_MEMORY
  perf_vm_resources
  [ "$VM_MEMORY" -eq 3584 ] # 6144 - 2560
}

@test "perf_vm_resources: limit pamięci poniżej rezerwy -> clamp VM_MEMORY=1024 (#10/#384)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  cg=$(_mk_cgroot)
  echo $((2048 * 1024 * 1024)) >"$cg/memory.max" # 2048-2560 = -512 -> clamp 1024
  _cgroot_env "$cg" "$(_mk_meminfo 32768)"
  unset VM_CPUS VM_MEMORY
  perf_vm_resources
  [ "$VM_MEMORY" -eq 1024 ]
}

@test "perf_vm_resources: memory.max 'max' -> bez limitu, z MemTotal (#10/#384)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  cg=$(_mk_cgroot)
  echo max >"$cg/memory.max"
  _cgroot_env "$cg" "$(_mk_meminfo 9216)"
  unset VM_CPUS VM_MEMORY
  perf_vm_resources
  [ "$VM_MEMORY" -eq 6656 ] # 9216 - 2560
}

@test "perf_vm_resources: env VM_CPUS/VM_MEMORY nadpisują limity cgroup (#10/#384)" {
  source "$REPO_ROOT/tests/lib/local-common.sh"
  cg=$(_mk_cgroot)
  echo "100000 100000" >"$cg/cpu.max"
  echo $((2048 * 1024 * 1024)) >"$cg/memory.max"
  _cgroot_env "$cg" "$(_mk_meminfo 32768)"
  VM_CPUS=2 VM_MEMORY=4096
  perf_vm_resources
  [ "$VM_CPUS" -eq 2 ]
  [ "$VM_MEMORY" -eq 4096 ]
}
