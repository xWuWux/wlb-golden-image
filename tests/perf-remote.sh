# shellcheck shell=bash
# Pomiary wydajności w VM testowej (przez ci/perf.sh, z remote-common.sh).
# Argument: liczba powtórzeń (PERF_REPEAT, domyślnie 1). Każda metryka:
#   - wymaga kompletu udanych prób (kod 302, Rscript=0, is-active); częściowa seria
#     zachowuje surowe próbki, ale nie emituje mediany i kończy skrypt błędem;
#   - przy >1 powtórzeniu wypisuje medianę jako wartość kanoniczną oraz linię „SAMPLE metryka v1 v2…”
#     (ci/perf.sh zapisuje ją osobno do kalibracji; porównanie z budżetem bierze tylko medianę).
set -uo pipefail
export LC_ALL=C
REPEAT=${1:-1}
if [[ ! $REPEAT =~ ^[1-9][0-9]*$ ]] || ((REPEAT > 20)); then
  echo "ERROR configuration reason=invalid_repeat value=$REPEAT"
  exit 2
fi
U=perf
MEASUREMENT_FAILED=0
ms() { date +%s%3N; }

# Zegar musi mieć rozdzielczość ms. Bez tego każdy pomiar byłby przypadkowy.
clock_probe=$(ms 2>/dev/null || true)
if [[ ! $clock_probe =~ ^[0-9]+$ ]]; then
  echo "ERROR clock reason=unsupported_date value=$clock_probe"
  exit 2
fi

# error METRYKA OCZEKIWANE ZAOBSERWOWANE POWÓD [KLUCZ=WARTOŚĆ...]
# Zachowuje nieudaną próbę w artefakcie, ale nie udaje poprawnego SAMPLE.
error() {
  local metric=$1 expected=$2 observed=$3 reason=$4
  shift 4
  printf 'ERROR %s expected=%s observed=%s reason=%s' "$metric" "$expected" "$observed" "$reason"
  printf ' %s' "$@"
  echo
  MEASUREMENT_FAILED=1
}

# RAW METRYKA WARTOŚCI... — surowe wartości bez oceny; tylko do diagnostyki.
raw() {
  local metric=$1
  shift
  printf 'RAW %s' "$metric"
  printf ' %q' "$@"
  echo
}

# DETAIL KLUCZ=WARTOŚĆ... — przyczyna nieudanej operacji (timeout, kod HTTP, brak pakietu).
detail() {
  printf 'DETAIL %s\n' "$*"
}

# emit METRYKA JEDNOSTKA OCZEKIWANE PRÓBKA... — tylko komplet poprawnych próbek daje medianę.
# OCZEKIWANE: dodatnia liczba całkowita. SAMPLE jest emitowany dopiero po walidacji, więc
# artefakt kalibracyjny nie zawiera niepełnych ani uszkodzonych serii (#10).
emit() {
  local metric=$1 unit=$2 expected=$3 value i
  local -a samples
  shift 3
  samples=("$@")
  if [[ ! $metric =~ ^[a-z][a-z0-9_]*$ ]] || [[ ! $unit =~ ^[A-Za-z%/._-]+$ ]]; then
    raw "$metric" "${samples[@]}"
    error "$metric" "${expected:-0}" "$#" invalid_metric_or_unit
    return 0
  fi
  if [[ ! $expected =~ ^[1-9][0-9]*$ ]]; then
    raw "$metric" "${samples[@]}"
    error "$metric" "${expected:-0}" "$#" invalid_expected
    return 0
  fi
  if ((${#samples[@]} != expected)); then
    raw "$metric" "${samples[@]}"
    error "$metric" "$expected" "${#samples[@]}" incomplete
    return 0
  fi
  for i in "${!samples[@]}"; do
    value=${samples[$i]}
    if [[ ! $value =~ ^[0-9]+$ ]]; then
      raw "$metric" "${samples[@]}"
      error "$metric" "$expected" "${#samples[@]}" invalid_sample "index=$i" "value=$value"
      return 0
    fi
  done
  echo "SAMPLE $metric ${samples[*]}"
  echo "$metric $(median "${samples[@]}") $unit"
}

# Testy jednostkowe ładują wyłącznie funkcje (source); bez tej bramki source uruchomiłby
# provisioning VM. Wykonanie skryptu przez `bash perf-remote.sh` lub `bash -s` nie ustawia tej zmiennej.
if [[ ${PERF_REMOTE_FUNCTIONS_ONLY:-0} == 1 ]]; then
  return 0
fi

password=$(/usr/local/sbin/wlb-hub-user "$U")

# logowanie do huba — jedna niezmierzona rozgrzewka (cold start TLS/SQLite), potem 5 prób.
# Warmup nie jest wliczany do progu: mierzymy steady-state logowania, nie pierwsze połączenie.
# Dla metryk cold-start (np. import pandas) pierwsza próba pozostaje w serii — patrz niżej.
hub_login "$U" "$password" >/dev/null 2>&1 || true
login_times=()
for attempt in 1 2 3 4 5; do
  t0=$(ms)
  code=$(hub_login "$U" "$password")
  if [[ $code == 302 ]]; then
    login_times+=("$(($(ms) - t0))")
  else
    detail "hub_login attempt=$attempt status=$code"
  fi
done
emit hub_login_ms ms 5 "${login_times[@]}"

# pierwsze uruchomienie serwera notebooków — REPEAT powtórzeń, każde na nowym koncie.
# Pierwsze (U=perf) zostaje do dalszych benchmarków (katalog domowy, środowiska).
spawn_times=()
for i in $(seq 1 "$REPEAT"); do
  su=$U
  ((i == 1)) || su="perf-spawn-$i"
  if [[ $su == "$U" ]]; then pw=$password; else pw=$(/usr/local/sbin/wlb-hub-user "$su"); fi
  code=$(hub_login "$su" "$pw")
  if [[ $code != 302 ]]; then
    detail "spawn_login user=$su attempt=$i status=$code"
    continue
  fi
  t0=$(ms)
  if ! hub_spawn "$su"; then
    detail "spawn_timeout user=$su attempt=$i"
    continue
  fi
  active=0
  for _ in $(seq 1 60); do
    systemctl is-active --quiet "jupyter-$su" && {
      active=1
      break
    }
    sleep 1
  done
  if ((active == 1)); then
    spawn_times+=("$(($(ms) - t0))")
  else
    detail "spawn_inactive user=$su attempt=$i"
  fi
  # zwolnij RAM: dodatkowe serwery nie są potrzebne dalej (jupyter-perf zostaje do benchmarków).
  # Bez tego 5 serwerów naraz zapycha pamięć małej VM i ciężkie metryki thrashują (OOM/zawieszenie).
  [[ $su == "$U" ]] || systemctl stop "jupyter-$su" &>/dev/null || true
done
emit spawn_first_ms ms "$REPEAT" "${spawn_times[@]}"

# benchmarki w katalogu domowym badacza perf (wymaga udanego spawnu U=perf)
home=/workspace/jupyter-$U
import_times=() groupby_times=() hades_times=() write_mbps=() read_mbps=()
if id "jupyter-$U" &>/dev/null && [[ -d $home ]]; then
  cat >"$home/bench.py" <<'PY'
import time
t = time.perf_counter()
import numpy as np, pandas as pd
import_s = time.perf_counter() - t
rng = np.random.default_rng(0)
df = pd.DataFrame({"g": rng.integers(0, 1000, 5_000_000), "v": rng.random(5_000_000)})
t = time.perf_counter()
df.groupby("g")["v"].agg(["mean", "std", "count"])
print(f"python_import_pandas_ms {import_s * 1000:.0f}")
print(f"pandas_groupby_5m_ms {(time.perf_counter() - t) * 1000:.0f}")
PY
  chown "jupyter-$U:" "$home/bench.py"

  for attempt in $(seq 1 "$REPEAT"); do
    # Każdą operację ogranicza timeout: zawieszona/thrashująca na małej VM daje „brak pomiaru”
    # (nie wisi do limitu całego etapu). Progi >> budżetu, więc nie ucinają legalnie wolnych.
    # pandas: tylko gdy skrypt zakończył się sukcesem (brak pakietu nie może wyjść „szybko”)
    if out=$(as "$U" timeout 120 /opt/tljh/user/bin/python "$home/bench.py" 2>/dev/null); then
      import_times+=("$(awk '/python_import_pandas_ms/ {print $2}' <<<"$out")")
      groupby_times+=("$(awk '/pandas_groupby_5m_ms/ {print $2}' <<<"$out")")
    else
      rc=$?
      detail "pandas exit=$rc attempt=$attempt"
    fi
    # HADES: sprawdzamy kod wyjścia Rscript (brak pakietu → błąd, nie „świetny” czas)
    t0=$(ms)
    if as "$U" timeout 180 Rscript -e 'suppressPackageStartupMessages({library(DatabaseConnector); library(FeatureExtraction); library(CohortMethod); library(PatientLevelPrediction)})' >/dev/null 2>&1; then
      hades_times+=("$(($(ms) - t0))")
    else
      rc=$?
      detail "hades exit=$rc attempt=$attempt"
    fi
    # Przepustowość dysku roboczego. Pierwszy dd tylko alokuje plik (nie jest mierzony);
    # mierzony jest steady-state overwrite po alokacji, a nie koszt pierwszego zapisu qcow2.
    # O_DIRECT w gościu nie omija cache QEMU/hosta — odczyt po zapisie jest optymistyczny.
    prealloc_rc=0
    as "$U" timeout 120 dd if=/dev/zero of="$home/dd.bin" bs=1M count=1024 oflag=direct status=none ||
      prealloc_rc=$?
    ((prealloc_rc == 0)) || detail "write_prealloc exit=$prealloc_rc attempt=$attempt"
    t0=$(ms)
    write_ok=0
    if as "$U" timeout 120 dd if=/dev/zero of="$home/dd.bin" bs=1M count=1024 oflag=direct conv=fsync status=none; then
      elapsed=$(($(ms) - t0))
      bytes=$(stat -c %s "$home/dd.bin" 2>/dev/null || echo 0)
      if ((elapsed > 0)) && ((bytes == 1024 * 1024 * 1024)); then
        write_mbps+=("$((bytes * 1000 / (elapsed * 1048576)))")
        write_ok=1
      else
        detail "write_invalid elapsed_ms=$elapsed bytes=$bytes attempt=$attempt"
      fi
    else
      rc=$?
      detail "write exit=$rc attempt=$attempt"
    fi
    if ((write_ok == 1)); then
      bytes=$(stat -c %s "$home/dd.bin" 2>/dev/null || echo 0)
      if ((bytes == 1024 * 1024 * 1024)); then
        t0=$(ms)
        if as "$U" timeout 120 dd if="$home/dd.bin" of=/dev/null bs=1M iflag=direct status=none; then
          elapsed=$(($(ms) - t0))
          if ((elapsed > 0)); then
            read_mbps+=("$((bytes * 1000 / (elapsed * 1048576)))")
          else
            detail "read_zero_duration attempt=$attempt"
          fi
        else
          rc=$?
          detail "read exit=$rc attempt=$attempt"
        fi
      else
        detail "read_wrong_size bytes=$bytes attempt=$attempt"
      fi
    fi
    rm -f "$home/dd.bin"
  done
fi
emit python_import_pandas_ms ms "$REPEAT" "${import_times[@]}"
emit pandas_groupby_5m_ms ms "$REPEAT" "${groupby_times[@]}"
emit r_load_hades_ms ms "$REPEAT" "${hades_times[@]}"
emit workspace_write_mbps MiB/s "$REPEAT" "${write_mbps[@]}"
emit workspace_read_mbps MiB/s "$REPEAT" "${read_mbps[@]}"
exit "$MEASUREMENT_FAILED"
