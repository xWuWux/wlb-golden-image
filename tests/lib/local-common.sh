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

# _perf_cgroup_cpus KORZEŃ — liczba vCPU z LIMITU CPU cgroup (nie z całego hosta): cgroup v2 cpu.max
# ("quota period"; quota="max" = brak limitu), fallback v1 cpu/cpu.cfs_quota_us + cpu.cfs_period_us
# (quota=-1 = brak limitu), fallback nproc. Zaokrągla w górę (ceil) i zwraca co najmniej 1.
_perf_cgroup_cpus() {
  local root=$1 quota period n
  if [[ -r $root/cpu.max ]]; then
    read -r quota period <"$root/cpu.max" 2>/dev/null || true
    if [[ $quota =~ ^[0-9]+$ && $period =~ ^[1-9][0-9]*$ ]]; then
      n=$(((quota + period - 1) / period))
      ((n < 1)) && n=1
      echo "$n"
      return
    fi
  fi
  if [[ -r $root/cpu/cpu.cfs_quota_us && -r $root/cpu/cpu.cfs_period_us ]]; then
    quota=$(<"$root/cpu/cpu.cfs_quota_us")
    period=$(<"$root/cpu/cpu.cfs_period_us")
    if [[ $quota =~ ^[0-9]+$ && $period =~ ^[1-9][0-9]*$ ]]; then
      n=$(((quota + period - 1) / period))
      ((n < 1)) && n=1
      echo "$n"
      return
    fi
  fi
  nproc
}

# _perf_cgroup_mem_mb KORZEŃ MEMTOTAL_MB — min(MemTotal, LIMIT pamięci cgroup) w MiB: v2 memory.max,
# fallback v1 memory/memory.limit_in_bytes. "max"/"infinity"/wartość >= MemTotal = brak limitu -> MemTotal.
_perf_cgroup_mem_mb() {
  local root=$1 memtotal=$2 raw limit_mb
  if [[ -r $root/memory.max ]]; then
    raw=$(<"$root/memory.max")
  elif [[ -r $root/memory/memory.limit_in_bytes ]]; then
    raw=$(<"$root/memory/memory.limit_in_bytes")
  else
    raw=""
  fi
  if [[ $raw =~ ^[0-9]+$ ]]; then
    limit_mb=$((raw / 1024 / 1024))
    if ((limit_mb > 0 && limit_mb < memtotal)); then
      echo "$limit_mb"
      return
    fi
  fi
  echo "$memtotal"
}

# perf_vm_resources — ustawia VM_CPUS/VM_MEMORY z LIMITÓW CGROUP runnera (nie całego hosta), jeśli nie
# podano. Runner CI bywa w cgroup mniejszym niż host; nproc//proc/meminfo widzą host, więc VM mogła
# przekroczyć limit runnera, a rezerwa 2560 MiB dawała UJEMNE VM_MEMORY (uwaga P2 z recenzji #381).
# Czyta cpu.max/memory.max (cgroup v2) z fallbackiem na v1 i na nproc//proc/meminfo; clamp pamięci do
# min 1 GiB. Testowalne bez zależności od hosta: WLB_CGROUP_ROOT (korzeń cgroup) i WLB_MEMINFO (meminfo).
perf_vm_resources() {
  local cgroot meminfo cpus memtotal_mb mem_mb
  cgroot=${WLB_CGROUP_ROOT:-/sys/fs/cgroup}
  meminfo=${WLB_MEMINFO:-/proc/meminfo}
  cpus=$(_perf_cgroup_cpus "$cgroot")
  memtotal_mb=$(($(awk '/^MemTotal:/ {print $2}' "$meminfo") / 1024))
  mem_mb=$(_perf_cgroup_mem_mb "$cgroot" "$memtotal_mb")
  mem_mb=$((mem_mb - 2560))        # rezerwa na hosta/hypervisor
  ((mem_mb < 1024)) && mem_mb=1024 # clamp: VM dostaje min 1 GiB nawet przy ciasnym/ujemnym limicie
  export VM_CPUS=${VM_CPUS:-$((cpus < 4 ? cpus : 4))}
  export VM_MEMORY=${VM_MEMORY:-$((mem_mb < 8192 ? mem_mb : 8192))}
}

require_vm() {
  if ! { [[ -f $T/qemu.pid ]] && kill -0 "$(cat "$T/qemu.pid")" 2>/dev/null; }; then
    echo "VM testowa nie działa — make test-up"
    exit 1
  fi
}
