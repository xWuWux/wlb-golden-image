#!/usr/bin/env bash
# Uruchamia kryteria akceptacji MVP na działającej VM testowej (tests/run-local.sh).
set -euo pipefail
# shellcheck source=tests/lib/local-common.sh
. "$(dirname "$0")/lib/local-common.sh"
require_vm
# WLB_TEST_NTP / WLB_TEST_PROXY (ustawiane przez ci/integration.sh, gdy wystartowały testowe serwery:
# czasu i proxy z allowlistą) → testy synchronizacji NTP (#36) i allowlisty proxy (#16); bez nich SKIP.
remote_run "$ROOT/tests/acceptance-remote.sh" ${WLB_TEST_NTP:+--ntp-sync} ${WLB_TEST_PROXY:+--proxy-allowlist}
