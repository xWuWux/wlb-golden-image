#!/usr/bin/env bash
# Stage 4b: bez argumentów uruchamia pełny zakres, --since REF wybiera cele z diffu.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
export PATH="$TOOLS_DIR/venv-unit/bin:$PATH"
require mutmut bats pytest python3 flock
mkdir -p build
exec 9>build/.mutation.lock
flock -n 9 || die "testy mutacyjne już działają w tym drzewie roboczym"
rm -rf build/mutation mutants .mutmut-cache
mkdir -p build/mutation
exec python3 ci/mutation_plan.py "$@"
