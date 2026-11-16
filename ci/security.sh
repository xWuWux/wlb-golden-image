#!/usr/bin/env bash
# Stage 3: Security & compliance — SAST, skan IaC, podatności zależności (SCA) i licencje.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require semgrep bandit checkov osv-scanner python3
mkdir -p build/sca

sast_semgrep() {
  local rc=0
  # tylko pliki śledzone przez git; reguły społecznościowe, bez telemetrii.
  # Tekstowe wyjście semgrepa zawiera dopasowane linie kodu (przy p/secrets — wykryty sekret), a log CI
  # publicznego repo widzi każdy, więc stdout idzie do /dev/null; błędy narzędzia zostają na stderr (#257).
  scan_with_status build/sca semgrep semgrep scan --metrics=off --error --quiet \
    --config p/default --config p/python --config p/github-actions --config p/secrets \
    --sarif-output=build/sca/semgrep.sarif . >/dev/null || rc=$?
  semgrep_findings build/sca/semgrep.sarif
  return "$rc"
}

# semgrep_findings PLIK — do logu tylko reguła i plik:linia aktywnych wyników, bez treści kodu (#257)
semgrep_findings() {
  [[ -f $1 ]] || return 0
  python3 - "$1" <<'PY' || true
import json, sys
for run in json.load(open(sys.argv[1], encoding="utf-8")).get("runs", []):
    for res in run.get("results", []):
        if res.get("suppressions"):
            continue
        loc = (res.get("locations") or [{}])[0].get("physicalLocation", {})
        line = loc.get("region", {}).get("startLine", "?")
        print(f"  {res.get('ruleId')}  {loc.get('artifactLocation', {}).get('uri')}:{line}")
PY
}

sast_bandit() {
  # bez fragmentu kodu i komunikatu (B105/B106 wklejają wartość hasła) — tylko plik:linia i id testu (#257)
  bandit -q -ll --format custom --msg-template "{relpath}:{line} {test_id} {severity}/{confidence}" ci/*.py ansible/roles/tljh/files/wlb-hub-user ansible/roles/monitoring/files/wlb-health
}

iac_checkov() {
  scan_with_status build/sca checkov checkov -d . --framework ansible github_actions secrets --compact --quiet \
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

# Anty-halucynacja LLM: zadeklarowane pakiety muszą istnieć w oficjalnych rejestrach (PyPI/conda-forge/
# CRAN-snapshot/GitHub) oraz w archiwum Ubuntu noble (apt/OS; indeks Packages, także nazwy wirtualne
# z Provides). Deterministyczne, bez zapytań do LLM; fail-closed przy błędzie rejestru.
pkg_existence() {
  python3 ci/check_package_existence.py --root . --ecosystems python,r,linux
}

run_check "SAST: semgrep" sast_semgrep
run_check "SAST: bandit (Python)" sast_bandit
run_check "IaC: checkov (Ansible, GitHub Actions, sekrety)" iac_checkov
run_check "SCA: podatności zależności (osv-scanner)" sca_osv
run_check "Licencje (ci/license-policy.yml)" licenses
run_check "Istnienie pakietów (anty-halucynacja LLM)" pkg_existence
finish
