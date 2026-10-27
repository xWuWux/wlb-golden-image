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
combined=$(mktemp)
cat "$ROOT/tests/acceptance-remote.sh" "$ROOT"/tests/acceptance.d/*.sh >"$combined"
# #149: program testowy trafia do VM razem z akceptacją, nie do obrazu produkcyjnego.
{
  printf "\nif python3 - \"\$R1\" <<'WLB_RESOURCE_TEST'\n"
  cat "$ROOT/tests/sluza_resources.py"
  printf "\nWLB_RESOURCE_TEST\nthen ok 'Limity i izolacja śluzy (#149)'; else ko 'Limity i izolacja śluzy (#149)'; fi\n"
  printf '\nsummary\n'
} >>"$combined"
remote_run "$combined" \
  ${WLB_TEST_NTP:+--ntp-sync} \
  ${WLB_TEST_PROXY:+--proxy-allowlist}
rm -f "$combined"
