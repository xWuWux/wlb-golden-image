#!/usr/bin/env bash
# Uruchamia kryteria akceptacji MVP na działającej VM testowej (tests/run-local.sh).
set -euo pipefail
# shellcheck source=tests/lib/local-common.sh
. "$(dirname "$0")/lib/local-common.sh"
require_vm
# WLB_TEST_NTP=1 (ustawiane przez ci/integration.sh, gdy wystartował testowy serwer czasu) → test
# faktycznej synchronizacji NTP w VM; bez niego ten test robi SKIP (#36).
remote_run "$ROOT/tests/acceptance-remote.sh" ${WLB_TEST_NTP:+--ntp-sync}
