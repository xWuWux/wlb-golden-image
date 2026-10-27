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
printf '\nsummary\n' >>"$combined"
remote_run "$combined" \
  ${WLB_TEST_NTP:+--ntp-sync} \
  ${WLB_TEST_PROXY:+--proxy-allowlist}
rm -f "$combined"
