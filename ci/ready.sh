#!/usr/bin/env bash
# Końcowa bramka: czy PR jest gotowy do code review i merge.
#   NEEDS   JSON z wynikami jobów (toJSON(needs) w GitHub Actions)
# Etapy 1–4b (z 3.5) muszą przejść zawsze; 3r — gdy etap 3 wykonał skan (#257); 5 — gdy zmiana
# dotyczy obrazu; 6 — gdy został uruchomiony.
set -euo pipefail
python3 - <<'PY'
import json, os, sys

needs = json.loads(os.environ["NEEDS"])
image = needs["lint"].get("outputs", {}).get("image") == "true"
# Publikacja Code scanning (#257) jest wymagana, gdy etap 3 doszedł do skanu (sukces lub znaleziska);
# kontekst bez publikacji (merge queue, Dependabot poza PR) kończy job sukcesem ze stanem unsupported.
scanned = needs.get("security", {}).get("result") in ("success", "failure")
stages = [
    ("lint", "1. Lint, format i sekrety", True),
    ("build-check", "2. Build test", True),
    ("security", "3. Security & compliance", True),
    ("security-report", "3r. Publikacja Code scanning", scanned),
    ("observability", "3.5. Kontrakty obrazu", True),
    ("unit", "4. Testy jednostkowe + pokrycie", True),
    ("mutation", "4b. Testy mutacyjne", True),
    ("integration", "5. Integracja i migracja", image),
    ("perf", "6a. Benchmarki (opcjonalne)", False),
    ("ephemeral", "6b. Wdrożenie tymczasowe (opcjonalne)", False),
]
rows, ok = [], True
for job, label, required in stages:
    result = needs.get(job, {}).get("result", "skipped")
    passed = result == "success" or (result == "skipped" and not required)
    ok &= passed
    icon = {"success": "✅", "skipped": "⏭️"}.get(result, "❌")
    rows.append(f"| {label} | {icon} {result}{'' if passed else ' — **blokuje**'} |")
text = "\n".join(["## Wynik pipeline'u", "", "| Etap | Wynik |", "|---|---|", *rows, "",
                  "**Gotowe do code review i merge.**" if ok else
                  "**Nie gotowe — popraw etapy oznaczone jako blokujące.** Diagnoza i ścieżka: sekcja poniżej, "
                  "docs/ci-runbook.md.", ""])
print(text)
if path := os.environ.get("GITHUB_STEP_SUMMARY"):
    open(path, "a").write(text)
sys.exit(0 if ok else 1)
PY
