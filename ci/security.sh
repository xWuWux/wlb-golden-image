#!/usr/bin/env bash
# Stage 3: Security & compliance — SAST, skan IaC, podatności zależności (SCA) i licencje.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require semgrep bandit checkov osv-scanner python3
mkdir -p build/sca

sast_semgrep() {
  # tylko pliki śledzone przez git; reguły społecznościowe, bez telemetrii
  semgrep scan --metrics=off --error --quiet \
    --config p/default --config p/python --config p/github-actions --config p/secrets \
    --sarif-output=build/sca/semgrep.sarif .
}

sast_bandit() {
  bandit -q -ll ci/*.py ansible/roles/tljh/files/wlb-hub-user
}

iac_checkov() {
  checkov -d . --framework ansible github_actions secrets --compact --quiet \
    --skip-path .tools --skip-path build --skip-path output \
    --output cli --output sarif --output-file-path console,build/sca/checkov.sarif
}

LOCKED=0
if python3 -c 'import json,sys; sys.exit(0 if json.load(open("envs/r/renv.lock"))["Packages"] else 1)' &&
  [[ -f envs/python/environment.lock.yml ]]; then
  LOCKED=1
fi

sca_osv() {
  if [[ $LOCKED != 1 ]]; then
    echo "Brak zamrożonych wersji (make freeze po pierwszym budowaniu) — SCA zależności pominięte."
    summary <<<"> **SCA pominięte:** brak locków w envs/. Po pierwszym budowaniu obrazu uruchom \`make freeze\`."
    return 0
  fi
  python3 ci/sca_requirements.py envs/python/environment.lock.yml build/sca/requirements.txt
  # --no-resolve: locki zawierają już pełny zestaw zależności
  osv-scanner scan source --no-resolve --format markdown --output-file build/sca/osv.md \
    -L envs/r/renv.lock -L build/sca/requirements.txt || {
    summary <build/sca/osv.md
    cat build/sca/osv.md
    return 1
  }
}

licenses() {
  python3 ci/license_check.py
}

run_check "SAST: semgrep" sast_semgrep
run_check "SAST: bandit (Python)" sast_bandit
run_check "IaC: checkov (Ansible, GitHub Actions, sekrety)" iac_checkov
run_check "SCA: podatności zależności (osv-scanner)" sca_osv
run_check "Licencje (ci/license-policy.yml)" licenses
finish
