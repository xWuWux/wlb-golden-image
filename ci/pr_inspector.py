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
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path


class PRInspectionError(RuntimeError):
    """Błąd uniemożliwiający wiarygodną inspekcję PR-a."""


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
    uncovered_prod: list[str] = field(default_factory=list)


# --- Wzorce klasyfikacji plików ----------------------------------------------

SECURITY_PATH_PARTS = frozenset(
    {
        "nftables",
        "nftables.conf",
        "15-dostep",
        "20-apparmor",
        "net_probe",
        "apparmor",
        "sudo",
        "polkit",
        "wlb-hub-revoke",
        "entra",
        "oidc",
        "auth",
        "sluza-out",
        "wlb-sluza-out-mover",
        "wlb-export",
        "storage",
    }
)

PATTERNS_PIPELINE = re.compile(r"^(?:\.github/workflows/|ci/|packer/)")
PATTERNS_PROD_CODE = re.compile(r"^(?:ansible/|packer/|ci/|scripts/|przewodnik-vm\.sh)")
PATTERNS_TESTS = re.compile(r"^tests/")
PATTERNS_DOCS = re.compile(r"^(?:docs/|.*\.md$)")
SKIP_SMELL_PATHS = re.compile(r"^(?:docs/|tests/|CHANGELOG\.md$|.*\.md$)")

SIZE_TIERS = (("XS", 50), ("S", 250), ("M", 600), ("L", 1000))
SIZE_DESCRIPTIONS = {
    "XS": "Bardzo mały (trywialna poprawka / dokumentacja)",
    "S": "Mały (łatwy i szybki do dokładnego code review, ~10-15 min)",
    "M": "Średni (standardowy PR z nową funkcjonalnością)",
    "L": "Duży (wymaga podzielenia uwagi na moduły)",
    "XL": "Bardzo duży (rekomendacja: rozważyć rozbicie na mniejsze PR-y)",
}

# Wzorce wymagają pozycji komendy (początek linii lub po separatorze shella),
# a nie dowolnego wystąpienia tekstu w docstringu/fiksturze.
COMMAND_SMELLS = (
    re.compile(r"(?:^|[;&|]\s*)(?:sudo\s+)?chmod\s+(?:-[A-Za-z]+\s+)*(?:0?777|a\+rwx)\b"),
    re.compile(r"(?:^|[;&|]\s*)(?:curl|wget)\b.*\|\s*(?:sudo\s+)?(?:bash|sh)\b"),
    re.compile(r"(?:^|[;&|]\s*)eval\s+\$"),
    re.compile(r"^\s*permissions:\s*write-all\b"),
)


# --- Parser numstat i diff ---------------------------------------------------


def parse_numstat(numstat_text: str) -> list[FileDiff]:
    """Parsuje wyjście git diff --numstat do listy obiektów FileDiff."""
    files: list[FileDiff] = []
    for raw_line in numstat_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            raise PRInspectionError(f"Nieoczekiwana linia numstat: {line!r}")
        ins_str, del_str, file_path = parts
        if ins_str == "-" and del_str == "-":
            files.append(FileDiff(path=file_path, insertions=0, deletions=0, is_binary=True))
            continue
        try:
            ins = int(ins_str)
            dels = int(del_str)
        except ValueError as exc:
            raise PRInspectionError(f"Niepoprawne liczby w linii numstat: {line!r}") from exc
        files.append(FileDiff(path=file_path, insertions=ins, deletions=dels))
    return files


def classify_size(insertions: int, deletions: int) -> tuple[str, str]:
    """Klasyfikuje wielkość zmiany (XS, S, M, L, XL) na podstawie liczby linii."""
    total = insertions + deletions
    for category, upper in SIZE_TIERS:
        if total < upper:
            return category, SIZE_DESCRIPTIONS[category]
    return "XL", SIZE_DESCRIPTIONS["XL"]


def _is_security_path(path: str) -> bool:
    """Czy ścieżka dotyczy bezpieczeństwa/sieci/izolacji.

    Używamy segmentów ścieżki, a nie dowolnych substringów, żeby dokumentacja
    typu docs/auth.md nie była fałszywie klasyfikowana jako HIGH.
    """
    if path.startswith(("docs/", "CHANGELOG.md")):
        return False
    return any(part in SECURITY_PATH_PARTS for part in Path(path).parts)


def _path_risks(files: list[FileDiff]) -> list[RiskFactor]:
    risks: list[RiskFactor] = []

    sec_files = [f.path for f in files if _is_security_path(f.path)]
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
                reason="Zmiana ról Ansible konfigurujących środowisko badacza i usługi VM.",
                files=sys_files,
            )
        )

    return risks


def analyze_risks(files: list[FileDiff], smells: list[str] | None = None) -> tuple[str, list[RiskFactor]]:
    """Identyfikuje strefy ryzyka architektury, bezpieczeństwa i smells w diffie."""
    risks = _path_risks(files)
    if smells:
        risks.append(
            RiskFactor(
                level="HIGH",
                area="Ryzykowne wzorce w diffie",
                reason="Wykryto potencjalnie niebezpieczne komendy lub wzorce w dodanych liniach.",
                files=[],
            )
        )

    if any(r.level in ("CRITICAL", "HIGH") for r in risks):
        overall = "HIGH"
    elif any(r.level == "MEDIUM" for r in risks):
        overall = "MEDIUM"
    else:
        overall = "LOW"
    return overall, risks


def _candidate_tests(path: str) -> list[str]:
    """Zwraca wzorce plików testów, które mogą odpowiadać danemu plikowi produkcyjnemu."""
    if path.startswith("ci/"):
        stem = Path(path).stem
        return [f"tests/unit/test_{stem}.py", f"tests/unit/{stem}.bats"]
    if path.startswith("ansible/roles/"):
        parts = path.split("/")
        role = parts[2] if len(parts) > 2 else ""
        return [f"tests/unit/*{role}*", f"tests/acceptance.d/*{role}*"]
    if path.startswith("packer/"):
        return ["tests/unit/*packer*", "tests/acceptance.d/*packer*"]
    if path.startswith("scripts/") or path == "przewodnik-vm.sh":
        stem = Path(path).stem
        return [f"tests/unit/test_{stem}.py", f"tests/unit/{stem}.bats"]
    return []


def check_test_completeness(files: list[FileDiff]) -> tuple[bool, bool, str, list[str]]:
    """Weryfikuje, czy zmiany w kodzie wykonawczym mają odpowiadające zmiany w testach."""
    prod = [f.path for f in files if PATTERNS_PROD_CODE.search(f.path) and not PATTERNS_TESTS.search(f.path)]
    test_files = [f for f in files if PATTERNS_TESTS.search(f.path)]
    test_paths = [f.path for f in test_files]

    uncovered = [
        path
        for path in prod
        if not any(fnmatch(test_path, pattern) for pattern in _candidate_tests(path) for test_path in test_paths)
    ]

    has_prod = bool(prod)
    has_tests = bool(test_paths)
    test_ins = sum(f.insertions for f in test_files)
    test_del = sum(f.deletions for f in test_files)

    if has_prod and not has_tests:
        assessment = "⚠️ Wykryto zmiany w kodzie wykonawczym/CI bez modyfikacji testów w tests/"
    elif has_prod and uncovered:
        assessment = "⚠️ Testy obecne, ale brak bezpośredniego pokrycia dla: " + ", ".join(f"`{p}`" for p in uncovered)
    elif has_prod:
        assessment = f"✅ Kod wykonawczy powiązany ze zmianami w testach (+{test_ins}/-{test_del} w tests/)"
    elif has_tests:
        assessment = f"✅ Rozszerzenie zestawu testów (+{test_ins}/-{test_del} w tests/)"
    else:
        assessment = "ℹ️ Zmiana dotyczy wyłącznie dokumentacji lub plików konfiguracyjnych"

    return has_prod, has_tests, assessment, uncovered


def _iter_diff_lines(diff_text: str) -> Iterator[tuple[str, str, str]]:
    """Yields (path, marker, content) dla linii diffu z informacją o pliku."""
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if line.startswith("+++ /dev/null"):
            current = None
            continue
        if current is None:
            continue
        if line.startswith((" ", "+")):
            yield current, line[0], line[1:]


def check_changelog(files: list[FileDiff], diff_text: str, has_prod: bool) -> tuple[bool, str]:
    """Weryfikuje, czy w PR modyfikującym zachowanie dodano wpis w sekcji ## Niewydane."""
    changed = any(f.path == "CHANGELOG.md" for f in files)

    if not has_prod:
        return changed, "ℹ️ Wpis w CHANGELOG.md opcjonalny dla zmian czysto dokumentacyjnych/testowych"
    if not changed:
        return False, "⚠️ Zmiana kodu/CI bez wpisu w CHANGELOG.md (wymagana sekcja ## Niewydane)"

    section: str | None = None
    entry_added = False
    for path, marker, content in _iter_diff_lines(diff_text):
        if path != "CHANGELOG.md":
            continue
        if content.startswith("## "):
            section = content.strip()
        elif marker == "+" and section == "## Niewydane" and content.strip().startswith(("- ", "* ")):
            entry_added = True

    if entry_added:
        return True, "✅ Wpis w sekcji ## Niewydane obecny"
    return False, "⚠️ Zmieniono CHANGELOG.md, ale brak wpisu w sekcji ## Niewydane"


def scan_diff_smells(diff_text: str) -> list[str]:
    """Skanuje dodane linie w diffie pod kątem ryzykownych wzorców shella i konfiguracji."""
    smells: list[str] = []
    for path, marker, content in _iter_diff_lines(diff_text):
        if marker != "+" or SKIP_SMELL_PATHS.search(path):
            continue
        text = content.strip()
        if not text or text.startswith("#"):
            continue
        for pattern in COMMAND_SMELLS:
            if pattern.search(text):
                smells.append(f"{path}: {text[:80]}")
                break
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
        elif r.area == "Ryzykowne wzorce w diffie":
            questions.append(
                "Czy wykryte wzorce (np. `chmod 777`, `curl | bash`) są realnym kodem produkcyjnym, "
                "a nie fiksturą testową lub przykładem w dokumentacji?"
            )

    if has_prod_without_tests:
        questions.insert(
            0,
            "PR modyfikuje kod produkcyjny bez zmian w testach — czy zachowanie jest pokryte "
            "istniejącymi testami akceptacyjnymi?",
        )

    if not questions:
        questions.append("Czy zmiana w dokumentacji/testach jest spójna z aktualną architekturą Laboratorium?")

    return list(dict.fromkeys(questions))[:8]


# --- Pobieranie diffu z gita -------------------------------------------------


def _run_git_diff(args: list[str], cwd: Path) -> str:
    try:
        res = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "-c",
                "core.quotePath=false",
                "-C",
                str(cwd),
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                *args,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return res.stdout
    except subprocess.CalledProcessError as exc:
        raise PRInspectionError(f"git diff {' '.join(args)} nie powiódł się: {exc.stderr.strip()}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PRInspectionError(f"git diff nie powiódł się: {exc}") from exc


def get_git_diff_numstat(base: str, head: str, cwd: Path) -> str:
    """Zwraca wynik git diff --numstat pomiędzy bazą a headem."""
    try:
        return _run_git_diff(["--numstat", f"{base}...{head}"], cwd)
    except PRInspectionError:
        return _run_git_diff(["--numstat", f"{base}..{head}"], cwd)


def get_git_diff_text(base: str, head: str, cwd: Path) -> str:
    """Zwraca pełny tekst diffu do analizy podejrzanych wzorców."""
    try:
        return _run_git_diff([f"{base}...{head}"], cwd)
    except PRInspectionError:
        return _run_git_diff([f"{base}..{head}"], cwd)


def resolve_base_ref(ref: str, cwd: Path) -> str:
    """Rozwiązuje lokalny lub zdalny ref bazowy; rzuca PRInspectionError, jeśli nie istnieje."""
    ref = ref.strip()
    if not ref:
        raise PRInspectionError("Brak gałęzi bazowej do inspekcji PR")

    for candidate in (ref, f"origin/{ref}"):
        try:
            res = subprocess.run(  # noqa: S603
                ["git", "-C", str(cwd), "rev-parse", "--verify", "--quiet", candidate],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PRInspectionError(f"Nie można zweryfikować refu {candidate}: {exc}") from exc
        if res.returncode == 0:
            return candidate
    raise PRInspectionError(f"Nie znaleziono gałęzi bazowej: {ref!r}")


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
    if not raw_numstat.strip():
        raise PRInspectionError(f"git diff {base}...{head} zwrócił pusty wynik — nie można zbudować karty")
    raw_diff = diff_text if diff_text is not None else get_git_diff_text(base, head, root)

    files = parse_numstat(raw_numstat)

    total_files = len(files)
    total_ins = sum(f.insertions for f in files)
    total_del = sum(f.deletions for f in files)

    size_cat, size_desc = classify_size(total_ins, total_del)
    smells = scan_diff_smells(raw_diff)
    overall_risk, risks = analyze_risks(files, smells)

    has_prod, has_tests, test_assess, uncovered_prod = check_test_completeness(files)
    has_cl, cl_assess = check_changelog(files, raw_diff, has_prod)
    has_docs = any(PATTERNS_DOCS.search(f.path) for f in files)

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
        uncovered_prod=uncovered_prod,
    )


def _md_cell(value: str) -> str:
    """Escapuje wartość do komórki tabeli Markdown."""
    return str(value).replace("|", r"\|").replace("\n", " ")


def render_markdown_report(report: PRInspectionReport) -> str:
    """Renderuje Kartę Oceny PR w formacie GitHub Flavored Markdown."""
    risk_icons = {"CRITICAL": "🟥", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
    risk_icon = risk_icons.get(report.overall_risk, "⚪")

    cl_status = "CHANGELOG zaktualizowany" if report.has_changelog else "Brak wpisu w CHANGELOG"
    test_status = "Obecne w PR" if report.has_tests else "Brak zmian w tests/"

    lines = [
        "## 🔍 Automatyczna Karta PR (Pre-Review Inspector)",
        "",
        f"Analiza zmian względem bazowej gałęzi `{_md_cell(report.base_ref)}`:",
        "",
        "| Wskaźnik / Kontrola | Wartość | Ocena i status |",
        "|---|---|---|",
        (
            f"| **Rozmiar zmian** | +{report.total_insertions} / -{report.total_deletions} "
            f"({report.total_files} plików) | `{report.size_category}` — {_md_cell(report.size_description)} |"
        ),
        f"| **Korelacja z testami** | {_md_cell(test_status)} | {_md_cell(report.test_assessment)} |",
        (
            f"| **Poziom ryzyka** | {risk_icon} `{report.overall_risk}` | "
            f"Zidentyfikowano {len(report.risks)} obszar(y) ryzyka |"
        ),
        f"| **Rejestr zmian** | {cl_status} | {_md_cell(report.changelog_assessment)} |",
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
            file_sample = ", ".join(f"`{_md_cell(f)}`" for f in r.files[:3])
            if len(r.files) > 3:
                file_sample += f" (+{len(r.files) - 3})"
            icon = risk_icons.get(r.level, "⚪")
            lines.append(f"| {_md_cell(r.area)} | {icon} `{r.level}` | {file_sample} | {_md_cell(r.reason)} |")
        lines.append("")

    if report.smells:
        lines.extend(
            [
                "### ⚠️ Wykryte wzorce wymagające uwagi (Smells)",
                "",
            ]
        )
        for smell in report.smells:
            lines.append(f"- ⚠️ {_md_cell(smell)}")
        lines.append("")

    if report.reviewer_questions:
        lines.extend(
            [
                "### 💡 Pytania pomocnicze dla Recenzenta:",
                "",
            ]
        )
        for idx, q in enumerate(report.reviewer_questions, 1):
            lines.append(f"{idx}. {_md_cell(q)}")
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

    if args.command != "inspect":
        return 2

    try:
        base_ref = resolve_base_ref(args.base, Path.cwd())
        report = inspect_pr(base=base_ref, head=args.head)
    except (PRInspectionError, OSError) as exc:
        print(f"BŁĄD inspekcji PR: {exc}", file=sys.stderr)
        return 2

    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"BŁĄD zapisu {args.output}: {exc}", file=sys.stderr)
            return 2

    md = render_markdown_report(report)
    print(md)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if (args.summary or step_summary) and step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(md + "\n")
        except OSError as exc:
            print(f"BŁĄD zapisu GITHUB_STEP_SUMMARY: {exc}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
