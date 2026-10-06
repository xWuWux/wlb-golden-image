#!/usr/bin/env bats
# Testy helperów pomiarów wydajności etapu 6a (#10): median, perf_vm_resources.

load helpers

@test "median: nieparzysta liczba próbek to wartość środkowa (#10)" {
  source "$REPO_ROOT/tests/lib/remote-common.sh"
  [ "$(median 30 10 20)" -eq 20 ]
}

@test "median: parzysta liczba próbek — dolna środkowa (#10)" {
  source "$REPO_ROOT/tests/lib/remote-common.sh"
  [ "$(median 40 10 30 20)" -eq 20 ]
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
  [ "$VM_MEMORY" -le 8192 ]
}
