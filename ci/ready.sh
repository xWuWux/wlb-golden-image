#!/usr/bin/env bash
# Końcowa bramka: czy PR jest gotowy do code review i merge.
#   NEEDS   JSON z wynikami jobów (toJSON(needs) w GitHub Actions)
# Etapy 1–4b (z 3.5) muszą przejść zawsze; 3r — gdy etap 3 wykonał skan (#257); 5 — gdy zmiana
# dotyczy obrazu; 6 — gdy został uruchomiony.
set -euo pipefail
python3 - <<'PY'
import json, os, sys
from pathlib import Path

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
    ("formal-logic", "4c. Dowody logiki WLB", needs["lint"].get("outputs", {}).get("formal") != "false"),
]
if "build-base" in needs:
    stages.append(("build-base", "5a. Budowa bazy", image))
stages.extend([
    ("integration", "5. Integracja i migracja", image),
    ("perf", "6a. Benchmarki (opcjonalne)", False),
    ("ephemeral", "6b. Wdrożenie tymczasowe (opcjonalne)", False),
])
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
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")

# Automatyczna inspekcja PR i Karta Oceny dla recenzenta (Pre-Review Inspector)
try:
    sys.path.insert(0, str(Path("ci").resolve()))
    import pr_inspector

    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if not base_ref:
        print("Uwaga: brak GITHUB_BASE_REF — inspekcja PR pominięta", file=sys.stderr)
    else:
        if not base_ref.startswith("origin/"):
            base_ref = f"origin/{base_ref}"

        report = pr_inspector.inspect_pr(base=base_ref, head="HEAD")
        if report.total_files == 0:
            raise RuntimeError("inspekcja zwróciła pusty diff")
        inspector_md = pr_inspector.render_markdown_report(report)
        print("\n" + inspector_md)
        if path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n" + inspector_md + "\n")
except Exception as exc:
    # Inspekcja jest narzędziem pomocniczym i nie może wywrócić bramki gotowości
    print(f"Uwaga: inspekcja PR pominięta ({exc})", file=sys.stderr)

sys.exit(0 if ok else 1)
PY
