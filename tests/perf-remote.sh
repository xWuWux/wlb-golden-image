# shellcheck shell=bash
# Pomiary wydajności w VM testowej (przez ci/perf.sh, z remote-common.sh).
# Wypisuje linie "metryka wartość jednostka" — porównanie z budżetem robi ci/perf.sh.
set -uo pipefail
U=perf
ms() { date +%s%3N; }

password=$(/usr/local/sbin/wlb-hub-user "$U")

# logowanie do huba — mediana z 5 prób
times=()
for _ in 1 2 3 4 5; do
  t0=$(ms)
  hub_login "$U" "$password" >/dev/null
  times+=($(($(ms) - t0)))
done
mapfile -t sorted < <(printf '%s\n' "${times[@]}" | sort -n)
echo "hub_login_ms ${sorted[2]} ms"

# pierwsze uruchomienie serwera notebooków (tworzy konto systemowe i katalog domowy)
t0=$(ms)
hub_spawn "$U"
for _ in $(seq 1 60); do
  systemctl is-active --quiet "jupyter-$U" && break
  sleep 1
done
echo "spawn_first_ms $(($(ms) - t0)) ms"

home=/workspace/jupyter-$U
cat >"$home/bench.py" <<'PY'
import time
t = time.perf_counter()
import numpy as np, pandas as pd
import_s = time.perf_counter() - t
rng = np.random.default_rng(0)
df = pd.DataFrame({"g": rng.integers(0, 1000, 5_000_000), "v": rng.random(5_000_000)})
t = time.perf_counter()
df.groupby("g")["v"].agg(["mean", "std", "count"])
print(f"python_import_pandas_ms {import_s * 1000:.0f} ms")
print(f"pandas_groupby_5m_ms {(time.perf_counter() - t) * 1000:.0f} ms")
PY
chown "jupyter-$U:" "$home/bench.py"
as "$U" /opt/tljh/user/bin/python "$home/bench.py"

t0=$(ms)
as "$U" Rscript -e 'suppressPackageStartupMessages({library(DatabaseConnector); library(FeatureExtraction); library(CohortMethod); library(PatientLevelPrediction)})' >/dev/null 2>&1
echo "r_load_hades_ms $(($(ms) - t0)) ms"

# przepustowość dysku roboczego (z pominięciem cache stron)
as "$U" dd if=/dev/zero of="$home/dd.bin" bs=1M count=1024 oflag=direct status=none
t0=$(ms)
as "$U" dd if=/dev/zero of="$home/dd.bin" bs=1M count=1024 oflag=direct conv=fsync status=none
write_ms=$(($(ms) - t0))
t0=$(ms)
as "$U" dd if="$home/dd.bin" of=/dev/null bs=1M iflag=direct status=none
read_ms=$(($(ms) - t0))
rm -f "$home/dd.bin"
echo "workspace_write_mbps $((1024 * 1000 / (write_ms > 0 ? write_ms : 1))) MB/s"
echo "workspace_read_mbps $((1024 * 1000 / (read_ms > 0 ? read_ms : 1))) MB/s"
