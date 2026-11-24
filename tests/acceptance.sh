#!/usr/bin/env bash
# Uruchamia kryteria akceptacji MVP na działającej VM testowej (tests/run-local.sh).
set -euo pipefail
# shellcheck source=tests/lib/local-common.sh
. "$(dirname "$0")/lib/local-common.sh"
require_vm
# WLB_TEST_NTP=1   → test synchronizacji NTP (#36)
# WLB_TEST_PROXY=1 → test kontraktu z atrapą proxy (#16)
# Jeden skrypt na VM: rdzeń (acceptance-remote.sh) + fragmenty obszarów (acceptance.d/*.sh,
# po nazwie) + summary. Sklejanie na HOŚCIE — VM dostaje pojedynczy plik (remote_run dokłada
# remote-common.sh). Dzięki temu nowy feature = nowy plik fragmentu, bez konfliktów na wspólnym pliku.
shopt -s nullglob
# #277: ścieżki fixture E2E są jednym kontraktem (ci/e2e-fixture-paths.txt) — ten sam plik
# czyta bramka wydania. Wstrzykujemy tablicę do sklejonego skryptu, żeby fragment akceptacji
# nie powtarzał listy ścieżek.
e2e_contract="$ROOT/ci/e2e-fixture-paths.txt"
[[ -s $e2e_contract ]] || {
  echo "Brak kontraktu ścieżek E2E: $e2e_contract (#277)" >&2
  exit 1
}
e2e_paths=()
while IFS= read -r line || [[ -n $line ]]; do
  line=${line%$'\r'}
  case $line in '' | '#'*) continue ;; esac
  e2e_paths+=("$line")
done <"$e2e_contract"
((${#e2e_paths[@]})) || {
  echo "Pusty kontrakt ścieżek E2E: $e2e_contract (#277)" >&2
  exit 1
}
combined=$(mktemp)
{
  printf '\nWLB_E2E_FIXTURE_PATHS=('
  printf ' %q' "${e2e_paths[@]}"
  printf ' )\n'
  # #323: helper sond egress jest testowy; nie trafia do obrazu produkcyjnego. Tworzymy go
  # w VM przed rdzeniem akceptacji, bo sekcja 6b wywołuje go jako badacz.
  printf "\ncat >/tmp/wlb-net-probe.py <<'WLB_NET_PROBE'\n"
  cat "$ROOT/tests/lib/net_probe.py"
  printf "\nWLB_NET_PROBE\n"
  cat "$ROOT/tests/lib/e2e-fixture.sh" "$ROOT/tests/lib/kafelki-exec.sh" \
    "$ROOT/tests/acceptance-remote.sh" "$ROOT"/tests/acceptance.d/*.sh
} >"$combined"
# #292: WLB_CHANNEL_GATING=1 promuje niezgodności matrycy kanałów do FAIL (domyślnie SKIP, jak #138).
channel_gating=
if [[ ${WLB_CHANNEL_GATING:-0} == 1 ]]; then channel_gating=--channel-gating; fi
# #149: program testowy trafia do VM razem z akceptacją, nie do obrazu produkcyjnego.
{
  printf "\nif python3 - \"\$R1\" <<'WLB_RESOURCE_TEST'\n"
  cat "$ROOT/tests/sluza_resources.py"
  printf "\nWLB_RESOURCE_TEST\nthen ok 'Limity i izolacja śluzy (#149)'; else ko 'Limity i izolacja śluzy (#149)'; fi\n"
  # #349 A1: XML jest raportem obok historycznego stdout; finalizacja przed summary,
  # żeby kod wyjścia summary (FAIL) pozostał ostatnim kodem skryptu.
  printf '\njunit_finalize || true\n'
  printf '\nsummary\n'
} >>"$combined"
remote_run "$combined" \
  ${channel_gating:+--channel-gating} \
  ${WLB_TEST_NTP:+--ntp-sync} \
  ${WLB_TEST_PROXY:+--proxy-allowlist}
rm -f "$combined"
