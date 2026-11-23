#!/usr/bin/env python3
"""Automatyczna inspekcja PR i karta oceny dla recenzenta (Pre-Review Inspector).

Działa w końcowym etapie potoku CI ("Gotowe do code review", ci/ready.sh) oraz lokalnie.
Analizuje `git diff` pod kątem:
1. Rozmiaru i złożoności zmiany (kategorie XS, S, M, L, XL).
2. Korelacji kodu wykonawczego z testami (reguła regress-first: kod produkcyjny wymaga testów).
3. Macierzy ryzyka architektury i bezpieczeństwa (firewall, AppArmor, uprawnienia, pipeline).
4. Spójności dokumentacji (CHANGELOG.md).
5. Wykrywania ryzykownych wzorców w diffie (security smells: chmod 777, curl|bash, itp.).
6. Generowania celowanych pytań kontrolnych dla recenzenta-człowieka.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FileDiff:
    path: str
    insertions: int
    deletions: int
    is_binary: bool = False


@dataclass
class RiskFactor:
    level: str  # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    area: str
    reason: str
    files: list[str] = field(default_factory=list)


@dataclass
class PRInspectionReport:
    base_ref: str
    head_ref: str
    total_files: int
    total_insertions: int
    total_deletions: int
    size_category: str
    size_description: str
    has_prod_code: bool
    has_tests: bool
    has_docs: bool
    has_changelog: bool
    test_assessment: str
    changelog_assessment: str
    overall_risk: str
    risks: list[RiskFactor] = field(default_factory=list)
    smells: list[str] = field(default_factory=list)
    reviewer_questions: list[str] = field(default_factory=list)


# --- Wzorce klasyfikacji plików ----------------------------------------------

PATTERNS_SECURITY = re.compile(
    r"(nftables|15-dostep|20-apparmor|net_probe|apparmor|sudo|polkit|wlb-hub-revoke|"
    r"entra|oidc|auth|sluza-out|wlb-sluza-out-mover|wlb-export|storage)"
)

PATTERNS_PIPELINE = re.compile(r"(\.github/workflows/|ci/|packer/)")

PATTERNS_PROD_CODE = re.compile(r"^(ansible/roles/|packer/scripts/|ci/|przewodnik-vm\.sh)")

PATTERNS_TESTS = re.compile(r"^tests/")

PATTERNS_DOCS = re.compile(r"^(docs/|.*\.md$)")


# --- Parser numstat i diff ----------------------------------------------------


def parse_numstat(numstat_text: str) -> list[FileDiff]:
    """Parsuje wyjście git diff --numstat do listy obiektów FileDiff."""
    files: list[FileDiff] = []
    for line in numstat_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 3:
            continue
        ins_str, del_str, file_path = parts[0], parts[1], parts[2]
        if ins_str == "-" and del_str == "-":
            files.append(FileDiff(path=file_path, insertions=0, deletions=0, is_binary=True))
        else:
            try:
                ins = int(ins_str)
                dels = int(del_str)
            except ValueError:
                ins, dels = 0, 0
            files.append(FileDiff(path=file_path, insertions=ins, deletions=dels))
    return files


def classify_size(insertions: int, deletions: int) -> tuple[str, str]:
    """Klasyfikuje wielkość zmiany (XS, S, M, L, XL) na podstawie liczby linii."""
    total = insertions + deletions
    if total < 50:
        return "XS", "Bardzo mały (trywialna poprawka / dokumentacja)"
    if total < 200:
        return "S", "Mały (łatwy i szybki do dokładnego code review, ~10-15 min)"
    if total < 500:
        return "M", "Średni (standardowy PR z nową funkcjonalnością)"
    if total < 1000:
        return "L", "Duży (wymaga podzielenia uwagi na moduły)"
    return "XL", "Bardzo duży (rekomendacja: rozważyć rozbicie na mniejsze PR-y)"


def analyze_risks(files: list[FileDiff]) -> tuple[str, list[RiskFactor]]:
    """Identyfikuje strefy ryzyka architektury i bezpieczeństwa na podstawie zmodyfikowanych ścieżek."""
    risks: list[RiskFactor] = []

    sec_files = [f.path for f in files if PATTERNS_SECURITY.search(f.path)]
    if sec_files:
        risks.append(
            RiskFactor(
                level="HIGH",
                area="Bezpieczeństwo, sieć i izolacja",
                reason=(
                    "Zmiana dotyka reguł zapory ogniowej (nftables), profili AppArmor, "
                    "uwierzytelniania lub śluzy danych."
                ),
                files=sec_files,
            )
        )

    pipe_files = [f.path for f in files if PATTERNS_PIPELINE.search(f.path) and f.path not in sec_files]
    if pipe_files:
        risks.append(
            RiskFactor(
                level="MEDIUM",
                area="Potok CI/CD i budowa obrazu",
                reason="Modyfikacja konfiguracji GitHub Actions, Packera lub skryptów integracyjnych.",
                files=pipe_files,
            )
        )

    sys_files = [
        f.path
        for f in files
        if f.path.startswith("ansible/roles/") and f.path not in sec_files and f.path not in pipe_files
    ]
    if sys_files:
        risks.append(
            RiskFactor(
                level="MEDIUM",
                area="Konfiguracja systemu i usług",
                reason="Zmiana ról Ansible konfiguruących środowisko badacza i usługi VM.",
                files=sys_files,
            )
        )

    if any(r.level in ("CRITICAL", "HIGH") for r in risks):
        overall = "HIGH"
    elif any(r.level == "MEDIUM" for r in risks):
        overall = "MEDIUM"
    else:
        overall = "LOW"

    return overall, risks


def check_test_completeness(files: list[FileDiff]) -> tuple[bool, bool, str]:
    """Weryfikuje, czy zmiany w kodzie wykonawczym posiadają odpowiadające zmiany w testach."""
    has_prod = any(PATTERNS_PROD_CODE.search(f.path) and not PATTERNS_TESTS.search(f.path) for f in files)
    test_files = [f for f in files if PATTERNS_TESTS.search(f.path)]
    has_tests = len(test_files) > 0

    test_ins = sum(f.insertions for f in test_files)
    test_del = sum(f.deletions for f in test_files)

    if has_prod and not has_tests:
        assessment = "⚠️ Wykryto zmiany w kodzie wykonawczym/CI bez modyfikacji testów w tests/"
    elif has_prod and has_tests:
        assessment = f"✅ Kod wykonawczy powiązany ze zmianami w testach (+{test_ins}/-{test_del} w tests/)"
    elif has_tests:
        assessment = f"✅ Rozszerzenie zestawu testów (+{test_ins}/-{test_del} w tests/)"
    else:
        assessment = "ℹ️ Zmiana dotyczy wyłącznie dokumentacji lub plików konfiguracyjnych"

    return has_prod, has_tests, assessment


def check_changelog(files: list[FileDiff], has_prod: bool) -> tuple[bool, str]:
    """Weryfikuje, czy w PR modyfikującym zachowanie zaktualizowano CHANGELOG.md."""
    has_cl = any(f.path == "CHANGELOG.md" for f in files)
    if has_prod:
        if has_cl:
            assessment = "✅ Wpis w CHANGELOG.md obecny"
        else:
            assessment = "⚠️ Zmiana kodu/CI bez wpisu w CHANGELOG.md (rekomendacja: sekcja ## Niewydane)"
    else:
        assessment = "ℹ️ Wpis w CHANGELOG.md opcjonalny dla zmian czysto dokumentacyjnych/testowych"
    return has_cl, assessment


def scan_diff_smells(diff_text: str) -> list[str]:
    """Skanuje dodane linie w diffie pod kątem ryzykownych wzorców shella i konfiguracji."""
    smells: list[str] = []
    added_lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added_lines.append(line[1:].strip())

    for line in added_lines:
        if re.search(r"\bchmod\s+(0?777|a\+rwx)\b", line):
            smells.append(f"Niebezpieczne uprawnienia pliku (`chmod 777` / `a+rwx`): `{line[:80]}`")
        if re.search(r"curl\s+.*\|\s*(bash|sh)\b", line):
            smells.append(f"Bezpośrednie uruchomienie zdalnego skryptu (`curl | bash`): `{line[:80]}`")
        if re.search(r"\beval\s+\$", line):
            smells.append(f"Użycie dynamicznego `eval $...`: `{line[:80]}`")
        if re.search(r"permissions:\s*write-all\b", line):
            smells.append(f"Szerokie uprawnienia `permissions: write-all` w workflow GitHub Actions: `{line[:80]}`")

    # Deduplikacja
    return list(dict.fromkeys(smells))


def generate_reviewer_questions(risks: list[RiskFactor], has_prod_without_tests: bool) -> list[str]:
    """Generuje dynamiczną listę pytań kontrolnych dla recenzenta."""
    questions: list[str] = []

    for r in risks:
        if r.area == "Bezpieczeństwo, sieć i izolacja":
            questions.append(
                "Czy reguły firewalla / nftables są domyślnie zamknięte (`fail-closed`, polityka drop) "
                "i egress nie został niekontrolowanie otwarty?"
            )
            questions.append(
                "Czy modyfikowane profile AppArmor działają w trybie enforce i nie powodują "
                "cichych odmów w logach audytu?"
            )
            questions.append(
                "Czy operacje na śluzie eksportu walidują sumy SHA-256 oraz uniemożliwiają wyjście "
                "poza katalog docelowy przez dowiązania symboliczne?"
            )
        elif r.area == "Potok CI/CD i budowa obrazu":
            questions.append(
                "Czy nowe kroki w pipeline działają pod strażnikiem `ci/guard.sh` z limitem czasu i pamięci?"
            )
            questions.append("Czy długoterminowe artefakty posiadają odpowiednio skonfigurowaną retencję?")
        elif r.area == "Konfiguracja systemu i usług":
            questions.append(
                "Czy skrypty instalacyjne oraz role Ansible są w pełni idempotentne przy wielokrotnym uruchomieniu?"
            )

    if has_prod_without_tests:
        questions.insert(
            0,
            "PR modyfikuje kod produkcyjny bez zmian w testach — czy zachowanie jest pokryte "
            "istniejącymi testami akceptacyjnymi?",
        )

    if not questions:
        questions.append("Czy zmiana w dokumentacji/testach jest spójna z aktualną architekturą Laboratorium?")

    # Unikalne do 5 pytań
    return list(dict.fromkeys(questions))[:5]


# --- Pobieranie diffu z gita -------------------------------------------------


def get_git_diff_numstat(base: str, head: str, cwd: Path) -> str:
    """Zwraca wynik git diff --numstat pomiędzy bazą a headem."""
    cmd = ["git", "-C", str(cwd), "diff", "--numstat", f"{base}...{head}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
        return res.stdout
    except subprocess.CalledProcessError:
        # Fallback na dwukropek lub HEAD~1
        fallback_cmd = ["git", "-C", str(cwd), "diff", "--numstat", f"{base}..{head}"]
        try:
            res = subprocess.run(fallback_cmd, capture_output=True, text=True, check=True)  # noqa: S603
            return res.stdout
        except subprocess.CalledProcessError:
            return ""


def get_git_diff_text(base: str, head: str, cwd: Path) -> str:
    """Zwraca pełny tekst diffu do analizy podejrzanych wzorców."""
    cmd = ["git", "-C", str(cwd), "diff", f"{base}...{head}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
        return res.stdout
    except subprocess.CalledProcessError:
        fallback_cmd = ["git", "-C", str(cwd), "diff", f"{base}..{head}"]
        try:
            res = subprocess.run(fallback_cmd, capture_output=True, text=True, check=True)  # noqa: S603
            return res.stdout
        except subprocess.CalledProcessError:
            return ""


def inspect_pr(
    base: str = "origin/main",
    head: str = "HEAD",
    cwd: Path | None = None,
    numstat_text: str | None = None,
    diff_text: str | None = None,
) -> PRInspectionReport:
    """Główna funkcja audytująca stan zmian w PR."""
    root = cwd or Path.cwd()

    raw_numstat = numstat_text if numstat_text is not None else get_git_diff_numstat(base, head, root)
    raw_diff = diff_text if diff_text is not None else get_git_diff_text(base, head, root)

    files = parse_numstat(raw_numstat)

    total_files = len(files)
    total_ins = sum(f.insertions for f in files)
    total_del = sum(f.deletions for f in files)

    size_cat, size_desc = classify_size(total_ins, total_del)
    overall_risk, risks = analyze_risks(files)

    has_prod, has_tests, test_assess = check_test_completeness(files)
    has_cl, cl_assess = check_changelog(files, has_prod)
    has_docs = any(PATTERNS_DOCS.search(f.path) for f in files)

    smells = scan_diff_smells(raw_diff)
    questions = generate_reviewer_questions(risks, has_prod and not has_tests)

    return PRInspectionReport(
        base_ref=base,
        head_ref=head,
        total_files=total_files,
        total_insertions=total_ins,
        total_deletions=total_del,
        size_category=size_cat,
        size_description=size_desc,
        has_prod_code=has_prod,
        has_tests=has_tests,
        has_docs=has_docs,
        has_changelog=has_cl,
        test_assessment=test_assess,
        changelog_assessment=cl_assess,
        overall_risk=overall_risk,
        risks=risks,
        smells=smells,
        reviewer_questions=questions,
    )


def render_markdown_report(report: PRInspectionReport) -> str:
    """Renderuje Kartę Oceny PR w formacie GitHub Flavored Markdown."""
    risk_icons = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
    risk_icon = risk_icons.get(report.overall_risk, "⚪")

    cl_status = "CHANGELOG zaktualizowany" if report.has_changelog else "Brak wpisu w CHANGELOG"
    test_status = "Obecne w PR" if report.has_tests else "Brak zmian w tests/"

    lines = [
        "## 🔍 Automatyczna Karta PR (Pre-Review Inspector)",
        "",
        f"Analiza zmian względem bazowej gałęzi `{report.base_ref}`:",
        "",
        "| Wskaźnik / Kontrola | Wartość | Ocena i status |",
        "|---|---|---|",
        (
            f"| **Rozmiar zmian** | +{report.total_insertions} / -{report.total_deletions} "
            f"({report.total_files} plików) | `{report.size_category}` — {report.size_description} |"
        ),
        f"| **Korelacja z testami** | {test_status} | {report.test_assessment} |",
        (
            f"| **Poziom ryzyka** | {risk_icon} `{report.overall_risk}` | "
            f"Zidentyfikowano {len(report.risks)} obszar(y) ryzyka |"
        ),
        f"| **Rejestr zmian** | {cl_status} | {report.changelog_assessment} |",
        "",
    ]

    if report.risks:
        lines.extend(
            [
                "### 🛡️ Zidentyfikowane strefy ryzyka architektury",
                "",
                "| Obszar | Poziom | Pliki objęte zmianą | Uzasadnienie |",
                "|---|---|---|---|",
            ]
        )
        for r in report.risks:
            file_sample = ", ".join(f"`{f}`" for f in r.files[:3])
            if len(r.files) > 3:
                file_sample += f" (+{len(r.files) - 3})"
            icon = risk_icons.get(r.level, "⚪")
            lines.append(f"| {r.area} | {icon} `{r.level}` | {file_sample} | {r.reason} |")
        lines.append("")

    if report.smells:
        lines.extend(
            [
                "### ⚠️ Wykryte wzorce wymagające uwagi (Smells)",
                "",
            ]
        )
        for smell in report.smells:
            lines.append(f"- ⚠️ {smell}")
        lines.append("")

    if report.reviewer_questions:
        lines.extend(
            [
                "### 💡 Pytania pomocnicze dla Recenzenta:",
                "",
            ]
        )
        for idx, q in enumerate(report.reviewer_questions, 1):
            lines.append(f"{idx}. {q}")
        lines.append("")

    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Punkt wejścia CLI."""
    parser = argparse.ArgumentParser(
        prog="pr_inspector.py",
        description="Automatyczna inspekcja PR i karta oceny dla recenzenta (WLB CI ready)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_cmd = subparsers.add_parser("inspect", help="Analizuje diff PR-a i generuje raport")
    inspect_cmd.add_argument(
        "--base",
        default=os.environ.get("GITHUB_BASE_REF", "origin/main"),
        help="Gałąź bazowa porównania (domyślnie: GITHUB_BASE_REF lub origin/main)",
    )
    inspect_cmd.add_argument(
        "--head",
        default="HEAD",
        help="Gałąź docelowa / commit (domyślnie: HEAD)",
    )
    inspect_cmd.add_argument(
        "--output",
        type=Path,
        help="Opcjonalna ścieżka zapisu raportu w formacie JSON",
    )
    inspect_cmd.add_argument(
        "--summary",
        action="store_true",
        help="Dopisuje wyrenderowany raport do GITHUB_STEP_SUMMARY oraz wypisuje na stdout",
    )

    args = parser.parse_args(argv)

    if args.command == "inspect":
        base_ref = args.base
        if not base_ref.startswith("origin/") and "/" not in base_ref:
            base_ref = f"origin/{base_ref}"

        report = inspect_pr(base=base_ref, head=args.head)

        if args.output:
            try:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
            except OSError as exc:
                print(f"BŁĄD zapisu {args.output}: {exc}", file=sys.stderr)

        md = render_markdown_report(report)
        print(md)

        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if (args.summary or step_summary) and step_summary:
            try:
                with open(step_summary, "a", encoding="utf-8") as f:
                    f.write(md + "\n")
            except OSError as exc:
                print(f"Ostrzeżenie: nie udało się dopisać do GITHUB_STEP_SUMMARY: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
