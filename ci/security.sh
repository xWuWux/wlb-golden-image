#!/usr/bin/env bash
# Stage 3: Security & compliance — SAST, skan IaC, podatności zależności (SCA) i licencje.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require semgrep bandit checkov osv-scanner python3
mkdir -p build/sca
# fixture kontraktu SARIF (celowe znaleziska) — skanowany tylko przez sarif_contract, nie przez główne skany
CONTRACT=tests/fixtures/sarif-contract

sast_semgrep() {
  local rc=0
  # tylko pliki śledzone przez git; reguły społecznościowe, bez telemetrii.
  # Tekstowe wyjście semgrepa zawiera dopasowane linie kodu (przy p/secrets — wykryty sekret), a log CI
  # publicznego repo widzi każdy, więc stdout idzie do /dev/null; błędy narzędzia zostają na stderr (#257).
  scan_with_status build/sca semgrep semgrep scan --metrics=off --error --quiet \
    --config p/default --config p/python --config p/github-actions --config p/secrets \
    --exclude "$CONTRACT" --sarif-output=build/sca/semgrep.sarif . >/dev/null || rc=$?
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
  # Framework secrets checkova 3.x nie zgłasza checków nawet na plikach kontrolnych (#257) — sekrety
  # pokrywają gitleaks (etap 1) i semgrep p/secrets; nie traktować checkova jako warstwy ochrony sekretów.
  scan_with_status build/sca checkov checkov -d . --framework ansible github_actions secrets --compact --quiet \
    --skip-path .tools --skip-path build --skip-path output --skip-path "$CONTRACT" \
    --output cli --output sarif --output-file-path console,build/sca/checkov.sarif
}

# Kontrakt SARIF na prawdziwych, przypiętych skanerach (#257): te same wersje semgrep/checkov co główny skan
# przetwarzają fixture z celowymi znaleziskami, a ci/sarif_report.py prepare musi dać findings z oczekiwanymi
# regułami, bez wartości canary w publikowanym SARIF, manifeście i logu. Łapie zmianę formatu wyjścia
# narzędzia (nowa wersja serializera), której nie złapią testy jednostkowe na fixture JSON.
sarif_contract() {
  local dir=build/sca/contract out=build/sca/contract-out log=build/sca/contract.log rc=0 src
  rm -rf "$dir" "$out" "$log"
  mkdir -p "$dir"
  # kopia poza repozytorium: domyślne wykluczenia semgrepa pomijają katalogi tests/ (i build/)
  src=$(mktemp -d)
  cp -R "$CONTRACT/." "$src"
  {
    scan_with_status "$dir" semgrep semgrep scan --metrics=off --error --quiet --config p/secrets \
      --sarif-output="$dir/semgrep.sarif" "$src" >/dev/null || true
    scan_with_status "$dir" checkov checkov -d "$src" --framework github_actions --compact --quiet \
      --output cli --output sarif --output-file-path "console,$dir/checkov.sarif" || true
    env -u GITHUB_OUTPUT -u GITHUB_STEP_SUMMARY python3 ci/sarif_report.py prepare --sca-dir "$dir" --out-dir "$out"
  } >"$log" 2>&1 || rc=$?
  rm -rf "$src"
  python3 - "$out" "$log" "$rc" <<'PY'
import json, sys
from pathlib import Path

out, log, rc = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
canary = "AKIAWLB257CANARY" + "0000"  # sklejane, żeby sam skrypt nie był znaleziskiem
expected = {"semgrep": "detected-aws-access-key-id-value", "checkov": "CKV2_GHA_1"}
errors = [] if rc == 0 else [f"prepare zakończył się kodem {rc}"]
manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8")) if (out / "manifest.json").is_file() else {}
outcomes = {entry["tool"]: entry for entry in manifest.get("reports", [])}
for tool, rule in expected.items():
    entry = outcomes.get(tool, {})
    if entry.get("outcome") != "findings" or not entry.get("publish"):
        errors.append(f"{tool}: oczekiwano findings do publikacji, jest {entry.get('outcome')} ({entry.get('reason', '')})")
        continue
    published = (out / f"{tool}.sarif").read_text(encoding="utf-8")
    rules = {r.get("ruleId", "") for run in json.loads(published)["runs"] for r in run["results"]}
    if not any(rule in rule_id for rule_id in rules):
        errors.append(f"{tool}: brak oczekiwanej reguły {rule} w publikowanym raporcie")
for path in [*out.glob("*"), log]:
    if canary in path.read_text(encoding="utf-8", errors="replace"):
        errors.append(f"canary w {path.name} — wyciek treści dopasowania")
print("\n".join(f"BŁĄD kontraktu SARIF: {e}" for e in errors) or "Kontrakt SARIF: oba skanery -> findings, bez canary.")
sys.exit(1 if errors else 0)
PY
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
run_check "IaC: checkov (Ansible, GitHub Actions)" iac_checkov
run_check "Kontrakt SARIF na przypiętych skanerach (#257)" sarif_contract
run_check "SCA: podatności zależności (osv-scanner)" sca_osv
run_check "Licencje (ci/license-policy.yml)" licenses
run_check "Istnienie pakietów (anty-halucynacja LLM)" pkg_existence
finish
