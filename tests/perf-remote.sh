# shellcheck shell=bash
# Pomiary wydajności w VM testowej (przez ci/perf.sh, z remote-common.sh).
# Argument: liczba powtórzeń (PERF_REPEAT, domyślnie 1). Każda metryka:
#   - sprawdza, czy operacja się UDAŁA (kod 302, Rscript=0, is-active) — nieudana nie jest liczona
#     jako „szybka”, lecz pomijana, więc ci/perf.sh potraktuje ją jako brak pomiaru (przekroczenie);
#   - przy >1 powtórzeniu wypisuje medianę jako wartość kanoniczną oraz linię „SAMPLE metryka v1 v2…”
#     (ci/perf.sh zapisuje ją osobno do kalibracji; porównanie z budżetem bierze tylko medianę).
set -uo pipefail
REPEAT=${1:-1}
[[ $REPEAT =~ ^[0-9]+$ ]] && ((REPEAT >= 1)) || REPEAT=1
U=perf
ms() { date +%s%3N; }

# emit METRYKA JEDNOSTKA PRÓBKA... — mediana jako wartość metryki + surowe próbki (SAMPLE).
# Brak próbek (same niepowodzenia) → nic nie wypisuje = „brak pomiaru” w budżecie.
emit() {
  local metric=$1 unit=$2
  shift 2
  (($# > 0)) || return 0
  echo "$metric $(median "$@") $unit"
  echo "SAMPLE $metric $*"
}

password=$(/usr/local/sbin/wlb-hub-user "$U")

# logowanie do huba — zawsze 5 prób (tanie), liczymy tylko udane (302)
login_times=()
for _ in 1 2 3 4 5; do
  t0=$(ms)
  [[ $(hub_login "$U" "$password") == 302 ]] && login_times+=("$(($(ms) - t0))")
done
emit hub_login_ms ms "${login_times[@]}"

# pierwsze uruchomienie serwera notebooków — REPEAT powtórzeń, każde na nowym koncie.
# Pierwsze (U=perf) zostaje do dalszych benchmarków (katalog domowy, środowiska).
spawn_times=()
for i in $(seq 1 "$REPEAT"); do
  su=$U
  ((i == 1)) || su="perf-spawn-$i"
  if [[ $su == "$U" ]]; then pw=$password; else pw=$(/usr/local/sbin/wlb-hub-user "$su"); fi
  [[ $(hub_login "$su" "$pw") == 302 ]] || continue
  t0=$(ms)
  hub_spawn "$su" || continue
  active=0
  for _ in $(seq 1 60); do
    systemctl is-active --quiet "jupyter-$su" && {
      active=1
      break
    }
    sleep 1
  done
  ((active == 1)) && spawn_times+=("$(($(ms) - t0))")
  # zwolnij RAM: dodatkowe serwery nie są potrzebne dalej (jupyter-perf zostaje do benchmarków).
  # Bez tego 5 serwerów naraz zapycha pamięć małej VM i ciężkie metryki thrashują (OOM/zawieszenie).
  [[ $su == "$U" ]] || systemctl stop "jupyter-$su" &>/dev/null || true
done
emit spawn_first_ms ms "${spawn_times[@]}"

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

  for _ in $(seq 1 "$REPEAT"); do
    # Każdą operację ogranicza timeout: zawieszona/thrashująca na małej VM daje „brak pomiaru”
    # (nie wisi do limitu całego etapu). Progi >> budżetu, więc nie ucinają legalnie wolnych.
    # pandas: tylko gdy skrypt zakończył się sukcesem (brak pakietu nie może wyjść „szybko”)
    if out=$(as "$U" timeout 120 /opt/tljh/user/bin/python "$home/bench.py" 2>/dev/null); then
      import_times+=("$(awk '/python_import_pandas_ms/ {print $2}' <<<"$out")")
      groupby_times+=("$(awk '/pandas_groupby_5m_ms/ {print $2}' <<<"$out")")
    fi
    # HADES: sprawdzamy kod wyjścia Rscript (brak pakietu → błąd, nie „świetny” czas)
    t0=$(ms)
    if as "$U" timeout 180 Rscript -e 'suppressPackageStartupMessages({library(DatabaseConnector); library(FeatureExtraction); library(CohortMethod); library(PatientLevelPrediction)})' >/dev/null 2>&1; then
      hades_times+=("$(($(ms) - t0))")
    fi
    # przepustowość dysku roboczego (z pominięciem cache stron)
    as "$U" timeout 120 dd if=/dev/zero of="$home/dd.bin" bs=1M count=1024 oflag=direct status=none || true
    t0=$(ms)
    if as "$U" timeout 120 dd if=/dev/zero of="$home/dd.bin" bs=1M count=1024 oflag=direct conv=fsync status=none; then
      wms=$(($(ms) - t0))
      write_mbps+=("$((1024 * 1000 / (wms > 0 ? wms : 1)))")
    fi
    t0=$(ms)
    if as "$U" timeout 120 dd if="$home/dd.bin" of=/dev/null bs=1M iflag=direct status=none; then
      rms=$(($(ms) - t0))
      read_mbps+=("$((1024 * 1000 / (rms > 0 ? rms : 1)))")
    fi
    rm -f "$home/dd.bin"
  done
fi
emit python_import_pandas_ms ms "${import_times[@]}"
emit pandas_groupby_5m_ms ms "${groupby_times[@]}"
emit r_load_hades_ms ms "${hades_times[@]}"
emit workspace_write_mbps MB/s "${write_mbps[@]}"
emit workspace_read_mbps MB/s "${read_mbps[@]}"
