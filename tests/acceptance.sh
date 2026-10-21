#!/usr/bin/env bash
# Uruchamia kryteria akceptacji MVP na działającej VM testowej (tests/run-local.sh).
set -euo pipefail
# shellcheck source=tests/lib/local-common.sh
. "$(dirname "$0")/lib/local-common.sh"
require_vm
# WLB_TEST_NTP=1   → test synchronizacji NTP (#36)
# WLB_TEST_PROXY=1 → test allowlisty na prawdziwym proxy (#16)
remote_run "$ROOT/tests/acceptance-remote.sh" \
  ${WLB_TEST_NTP:+--ntp-sync} \
  ${WLB_TEST_PROXY:+--proxy-allowlist}
