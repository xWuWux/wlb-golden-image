# shellcheck shell=bash
# Wspólne funkcje skryptów testowych uruchamianych na hoście (VM testowa z tests/run-local.sh).

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
T="$ROOT/build/test"
SSH=(ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
  -i "$T/id_ed25519" -p "${SSH_PORT:-2222}" wlbadmin@127.0.0.1)

# remote_run SKRYPT [ARG...] — wykonuje skrypt w VM jako root, z funkcjami z remote-common.sh.
# Skrypt trafia najpierw do pliku, a uruchamiany jest ze stdin z /dev/null: przy "bash -s" polecenia
# czytające stdin (np. ausearch, gdy stdin nie jest terminalem) zjadały resztę skryptu.
remote_run() {
  local script=$1
  shift
  cat "$ROOT/tests/lib/remote-common.sh" "$script" |
    "${SSH[@]}" "f=\$(mktemp) && cat >\"\$f\" && sudo bash \"\$f\" $(printf '%q ' "$@") </dev/null; rc=\$?; rm -f \"\$f\"; exit \$rc"
}

# perf_vm_resources — ustawia VM_CPUS/VM_MEMORY z zasobów hosta (jak ci/integration.sh), jeśli nie
# podano. Bez tego ci/perf.sh brałby domyślne 4 vCPU / 8 GB z run-local.sh, czyli VM większą niż
# host runnera (2 vCPU / ~7 GB) — zagnieżdżona wirtualizacja z nadsubskrypcją zaburza pomiary (#10).
perf_vm_resources() {
  local cpus mem_mb
  cpus=$(nproc)
  mem_mb=$(($(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 - 2560))
  export VM_CPUS=${VM_CPUS:-$((cpus < 4 ? cpus : 4))}
  export VM_MEMORY=${VM_MEMORY:-$((mem_mb < 8192 ? mem_mb : 8192))}
}

require_vm() {
  if ! { [[ -f $T/qemu.pid ]] && kill -0 "$(cat "$T/qemu.pid")" 2>/dev/null; }; then
    echo "VM testowa nie działa — make test-up"
    exit 1
  fi
}
