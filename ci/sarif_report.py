#!/usr/bin/env python3
"""Przygotowanie raportów SARIF do publikacji w GitHub code scanning (#257).

Job skanujący nie ma uprawnień zapisu, więc cała walidacja i sanityzacja dzieje się
tutaj: sprawdzamy, że raport jest kompletnym SARIF 2.1.0 właściwego narzędzia, usuwamy
z niego fragmenty kodu (snippet/contextRegion), a wynik zapisujemy jako artefakt dla
osobnego joba publikującego. Ten job czyta już tylko gotowe pliki i manifest — nie
uruchamia żadnych skryptów z repozytorium.

Brak raportu nie jest tym samym co raport czysty: wynik ``not_run``/``error`` nigdy nie
jest publikowany, a plik wyjściowy przebiegu zakończonego błędem jest usuwany.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Report:
    """Opis jednego raportu SARIF oczekiwanego w katalogu SCA."""

    tool: str
    sarif: str
    category: str
    driver: str
    requires_rules: bool = False


REPORTS: dict[str, Report] = {
    "semgrep": Report(
        tool="semgrep",
        sarif="semgrep.sarif",
        category="semgrep",
        driver="semgrep",
        requires_rules=True,
    ),
    "checkov": Report(
        tool="checkov",
        sarif="checkov.sarif",
        category="checkov",
        driver="checkov",
        requires_rules=False,
    ),
}
OUTCOMES = ("clean", "findings", "error", "not_run")
MAX_GZIP_BYTES = 10 * 1024 * 1024  # limit GitHub dla uploadu (gzip)
MAX_RAW_BYTES = 100 * 1024 * 1024  # zanim w ogóle parsujemy
MAX_RUNS = 20
MAX_RESULTS_PER_RUN = 25_000
MAX_RULES_PER_RUN = 25_000

_RUN_ENV = (
    ("repository", "GITHUB_REPOSITORY"),
    ("sha", "GITHUB_SHA"),
    ("ref", "GITHUB_REF"),
    ("event", "GITHUB_EVENT_NAME"),
    ("run_id", "GITHUB_RUN_ID"),
    ("run_attempt", "GITHUB_RUN_ATTEMPT"),
)


class ReportError(Exception):
    """Raport nie nadaje się do publikacji; komunikat nigdy nie zawiera jego treści."""


@dataclass(frozen=True)
class ReportInfo:
    """Metadane przyjętego raportu, liczone już po sanityzacji.

    ``result_count`` to liczba aktywnych wyników (wyciszone ``# nosemgrep`` nie liczą się
    do klasyfikacji), a ``suppressed_count`` — liczba wyników wyciszonych.
    """

    tool: str
    category: str
    sha256: str
    result_count: int
    driver_version: str
    rules_digest: str
    suppressed_count: int = 0


def _expected(expected_tool: str) -> Report:
    try:
        return REPORTS[expected_tool]
    except KeyError as exc:
        raise ValueError(f"nieznane narzędzie: {expected_tool}") from exc


def _validate_run(run: object, expected: Report) -> None:
    if not isinstance(run, dict):
        raise ReportError(f"raport {expected.sarif} zawiera niepoprawny przebieg")
    tool = run.get("tool")
    driver = tool.get("driver") if isinstance(tool, dict) else None
    name = driver.get("name") if isinstance(driver, dict) else None
    if not isinstance(name, str) or expected.driver not in name.lower():
        raise ReportError(f"raport {expected.sarif} nie pochodzi z narzędzia {expected.tool}")
    invocations = run.get("invocations")
    if isinstance(invocations, list):
        for invocation in invocations:
            if isinstance(invocation, dict) and invocation.get("executionSuccessful") is False:
                raise ReportError("skaner zgłosił nieudane wykonanie")
    if "results" in run:
        results = run["results"]
        if not isinstance(results, list):
            raise ReportError(f"raport {expected.sarif}: results nie jest listą")
        if len(results) > MAX_RESULTS_PER_RUN:
            raise ReportError(f"raport {expected.sarif} ma zbyt wiele wyników")
    rules = driver.get("rules")
    if rules is not None:
        if not isinstance(rules, list):
            raise ReportError(f"raport {expected.sarif}: rules nie jest listą")
        if len(rules) > MAX_RULES_PER_RUN:
            raise ReportError(f"raport {expected.sarif} ma zbyt wiele reguł")


def load_report(path: Path, expected_tool: str) -> dict:
    """Wczytuje i waliduje SARIF 2.1.0 wskazanego narzędzia; błąd -> ReportError."""
    path = Path(path)
    expected = _expected(expected_tool)
    if path.is_symlink():
        raise ReportError(f"raport {expected.sarif} jest dowiązaniem symbolicznym")
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise ReportError(f"brak raportu {expected.sarif}") from exc
    except OSError as exc:
        raise ReportError(f"nie można odczytać raportu {expected.sarif}") from exc
    if not stat.S_ISREG(st.st_mode):
        raise ReportError(f"raport {expected.sarif} nie jest zwykłym plikiem")
    if st.st_size > MAX_RAW_BYTES:
        raise ReportError(f"raport {expected.sarif} przekracza limit rozmiaru")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ReportError(f"raport {expected.sarif} nie jest poprawnym UTF-8") from exc
    except OSError as exc:
        raise ReportError(f"nie można odczytać raportu {expected.sarif}") from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportError(f"raport {expected.sarif} nie jest poprawnym JSON") from exc
    if not isinstance(doc, dict):
        raise ReportError(f"raport {expected.sarif} nie jest obiektem JSON")
    if doc.get("version") != "2.1.0":
        raise ReportError(f"raport {expected.sarif} nie jest w wersji SARIF 2.1.0")
    runs = doc.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ReportError(f"raport {expected.sarif} nie zawiera przebiegów")
    if len(runs) > MAX_RUNS:
        raise ReportError(f"raport {expected.sarif} ma zbyt wiele przebiegów")
    for run in runs:
        _validate_run(run, expected)
    if expected.requires_rules:
        total_rules = sum(len(run["tool"]["driver"].get("rules") or []) for run in runs)
        if total_rules == 0:
            raise ReportError(f"raport {expected.sarif} nie zawiera reguł")
    return doc


def _scrub_physical_locations(node: object) -> None:
    """Rekurencyjnie usuwa snippet i contextRegion z każdego physicalLocation."""
    if isinstance(node, dict):
        physical = node.get("physicalLocation")
        if isinstance(physical, dict):
            region = physical.get("region")
            if isinstance(region, dict):
                region.pop("snippet", None)
            physical.pop("contextRegion", None)
        for value in node.values():
            _scrub_physical_locations(value)
    elif isinstance(node, list):
        for item in node:
            _scrub_physical_locations(item)


def _sanitize_notification_message(message: object) -> None:
    """Przycina treść notyfikacji do pierwszej linii i 200 znaków, usuwa markdown."""
    if not isinstance(message, dict):
        return
    message.pop("markdown", None)
    text = message.get("text")
    if not isinstance(text, str):
        return
    lines = text.splitlines()
    first = lines[0] if lines else ""
    if len(first) > 200:
        first = first[:200]
    if first != text:
        first += "…"
    message["text"] = first


def _sanitize_notifications(run: dict) -> None:
    """Czyści notyfikacje narzędzia w danym przebiegu (często zawierają kod źródłowy)."""
    invocations = run.get("invocations")
    if not isinstance(invocations, list):
        return
    for invocation in invocations:
        if not isinstance(invocation, dict):
            continue
        for key in ("toolExecutionNotifications", "toolConfigurationNotifications"):
            notifications = invocation.get(key)
            if not isinstance(notifications, list):
                continue
            for notification in notifications:
                if isinstance(notification, dict):
                    _sanitize_notification_message(notification.get("message"))


def sanitize(doc: dict) -> dict:
    """Zwraca głęboką kopię raportu bez fragmentów kodu w wynikach.

    Snippet p/secrets może zawierać wykryty sekret, a code scanning i tak pokazuje kod
    z repozytorium. Reguły, komunikaty wyników, ruleId i odciski palców pozostają bez
    zmian. Notyfikacje narzędzia bywają jednak nośnikiem długich fragmentów kodu, więc
    ich treść jest przycinana, a markdown usuwany.
    """
    clean = copy.deepcopy(doc)
    runs = clean.get("runs")
    if isinstance(runs, list):
        for run in runs:
            if isinstance(run, dict):
                _sanitize_notifications(run)
                results = run.get("results")
                if isinstance(results, list):
                    for result in results:
                        _scrub_physical_locations(result)
    return clean


def _is_suppressed(result: object) -> bool:
    """Wynik wyciszony: suppressions to niepusta lista bez rejected/underReview."""
    if not isinstance(result, dict):
        return False
    suppressions = result.get("suppressions")
    if not isinstance(suppressions, list) or not suppressions:
        return False
    return not any(
        isinstance(item, dict) and item.get("status") in ("rejected", "underReview") for item in suppressions
    )


def classify(exit_code: int | None, info: ReportInfo | None) -> str:
    """Klasyfikuje przebieg skanera: clean/findings/error/not_run."""
    if exit_code is None:
        return "not_run"
    if info is None:
        return "error"
    if exit_code == 0:
        return "clean" if info.result_count == 0 else "findings"
    if exit_code == 1 and info.result_count > 0:
        return "findings"
    return "error"


def read_exit_code(path: Path) -> int | None:
    """Kod wyjścia skanera: brak pliku -> None, istniejący lecz niepoprawny -> -1."""
    path = Path(path)
    try:
        if path.is_symlink():
            return -1
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        return -1
    if not stat.S_ISREG(st.st_mode):
        return -1
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return -1
    if not text:
        return -1
    try:
        return int(text)
    except ValueError:
        return -1


def drop_suppressed(doc: dict) -> dict:
    """Zwraca kopię raportu bez wyników wyciszonych w kodzie (``# nosemgrep``, ``checkov:skip``).

    GitHub Code scanning ignoruje pole ``suppressions`` i pokazałby takie wyniki jako otwarte alerty,
    choć bramka etapu 3 ich nie liczy, a uzasadnienie jest w kodzie. Liczbę wyciszeń zachowuje manifest.
    """
    kept = copy.deepcopy(doc)
    for run in kept.get("runs") or []:
        if isinstance(run, dict) and isinstance(run.get("results"), list):
            run["results"] = [result for result in run["results"] if not _is_suppressed(result)]
    return kept


def _report_info(report: Report, clean: dict, payload: bytes) -> ReportInfo:
    """Metadane liczone z raportu po sanityzacji, ale PRZED usunięciem wyciszeń (liczniki)."""
    runs = clean["runs"]
    results = [result for run in runs for result in (run.get("results") or [])]
    suppressed_count = sum(1 for result in results if _is_suppressed(result))
    result_count = len(results) - suppressed_count
    rules = [run["tool"]["driver"].get("rules") or [] for run in runs]
    canonical = json.dumps(rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    driver_version = ""
    for run in runs:
        driver = run["tool"]["driver"]
        # checkov: version; semgrep: tylko semanticVersion
        version = driver.get("version") or driver.get("semanticVersion")
        if isinstance(version, str) and version:
            driver_version = version
            break
    return ReportInfo(
        tool=report.tool,
        category=report.category,
        sha256=hashlib.sha256(payload).hexdigest(),
        result_count=result_count,
        driver_version=driver_version,
        rules_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        suppressed_count=suppressed_count,
    )


def _prepare_report(report: Report, source: Path, target: Path) -> ReportInfo:
    """Waliduje, sanityzuje i zapisuje raport; przy błędzie nie zostawia pliku."""
    try:
        doc = load_report(source, report.tool)
        clean = sanitize(doc)
        payload = json.dumps(drop_suppressed(clean), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        target.write_bytes(payload)
        if len(gzip.compress(payload)) > MAX_GZIP_BYTES:
            raise ReportError(f"raport {report.sarif} przekracza limit rozmiaru gzip")
    except ReportError:
        target.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise ReportError(f"nie udało się zapisać raportu {report.sarif}") from exc
    return _report_info(report, clean, payload)


def _mismatch_reason(exit_code: int) -> str:
    if exit_code == 1:
        return "kod wyjścia 1, ale raport nie zawiera wyników"
    return f"kod wyjścia skanera {exit_code} oznacza błąd narzędzia"


def _run_metadata(env: Mapping[str, str]) -> dict[str, str]:
    return {key: str(env.get(name) or "") for key, name in _RUN_ENV}


def _publish_label(entry: dict) -> str:
    if entry["publish"]:
        return "tak"
    reason = entry.get("reason")
    return f"nie — {reason}" if reason else "nie"


def _summary_table(entries: list[dict]) -> str:
    lines = [
        "### Raporty SARIF dla Code scanning (#257)",
        "",
        "| Narzędzie | Kategoria | Wynik skanu | Wyników | Wersja | Reguły | Publikacja |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        rules = entry.get("rules_digest")
        lines.append(
            f"| {entry['tool']} | {entry['category']} | {entry['outcome']} | "
            f"{entry.get('result_count', '—')} | {entry.get('driver_version') or '—'} | "
            f"{rules[:12] if rules else '—'} | {_publish_label(entry)} |"
        )
    return "\n".join(lines) + "\n"


def _append_github_output(path: str, entries: list[dict]) -> None:
    with Path(path).open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(f"{entry['tool']}={entry['outcome']}\n")


def _write_summary(env: Mapping[str, str], entries: list[dict]) -> None:
    table = _summary_table(entries)
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as fh:
            fh.write(table)
    else:
        sys.stdout.write(table)


def prepare(sca_dir: Path, out_dir: Path, env: Mapping[str, str]) -> dict:
    """Przygotowuje artefakty code scanning i zwraca manifest."""
    sca_dir = Path(sca_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in (*[report.sarif for report in REPORTS.values()], "manifest.json"):
        (out_dir / name).unlink(missing_ok=True)

    entries: list[dict] = []
    for tool, report in REPORTS.items():
        exit_code = read_exit_code(sca_dir / f"{tool}.exit")
        target = out_dir / report.sarif
        info: ReportInfo | None = None
        reason: str | None = None
        if exit_code is None:
            outcome = "not_run"
        else:
            try:
                info = _prepare_report(report, sca_dir / report.sarif, target)
            except ReportError as exc:
                outcome = "error"
                reason = str(exc)
            else:
                outcome = classify(exit_code, info)
                if outcome == "error":
                    target.unlink(missing_ok=True)
                    reason = _mismatch_reason(exit_code)

        entry: dict = {
            "tool": report.tool,
            "category": report.category,
            "outcome": outcome,
            "publish": outcome in ("clean", "findings"),
            "exit_code": exit_code,
        }
        if reason is not None:
            entry["reason"] = reason
        if entry["publish"] and info is not None:
            entry["sha256"] = info.sha256
            entry["result_count"] = info.result_count
            entry["suppressed_count"] = info.suppressed_count
            entry["driver_version"] = info.driver_version
            entry["rules_digest"] = info.rules_digest
        entries.append(entry)

    manifest = {"schema": 1, "run": _run_metadata(env), "reports": entries}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    output = env.get("GITHUB_OUTPUT")
    if output:
        _append_github_output(output, entries)
    _write_summary(env, entries)
    return manifest


def main(argv: list[str] | None = None) -> int:
    """CLI: ``prepare --sca-dir PATH --out-dir PATH``; 2 tylko przy błędzie użycia."""
    parser = argparse.ArgumentParser(description="Przygotowuje raporty SARIF do publikacji (#257).")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare", help="waliduje i sanityzuje raporty SARIF")
    command.add_argument("--sca-dir", type=Path, required=True)
    command.add_argument("--out-dir", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    prepare(args.sca_dir, args.out_dir, os.environ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
