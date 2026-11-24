"""Parser i normalizator raportów JUnit XML (etap 4 pytest + etap 5 akceptacja).

Zgodny ze specyfikacją PR A2 dla issue #349.
Obsługuje dwa źródła raportów:
1. Pytest JUnit XML (etap 4) — test_id = f"{classname}::{name}" (lub name, gdy brak classname).
2. Acceptance JUnit XML (etap 5: acceptance-stage5) — test_id = name.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FlakyReportError(Exception):
    """Bazowy błąd modułu raportowania testów niestabilnych."""


class MalformedReportError(FlakyReportError):
    """Plik raportu jest uszkodzony, niepełny lub nie spełnia kontraktu JUnit."""


@dataclass(frozen=True)
class TestResult:
    test_id: str
    status: str  # "pass" | "fail" | "skip" | "error"
    time: float
    skip_reason: str | None = None
    source_stage: str = "stage4:unit"
    failure_message: str | None = None


def _clean_text(elem: ET.Element | None) -> str:
    """Zwraca oczyszczony tekst elementu XML lub pusty łańcuch."""
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


def parse_junit(path: str | Path, source_stage: str | None = None) -> list[TestResult]:
    """Parsuje plik JUnit XML i zwraca listę obiektów TestResult.

    Wymóg fail-closed: w przypadku braku pliku, błędu I/O, pustego pliku
    lub uszkodzonego XML-a zgłasza wyjątek (MalformedReportError lub FileNotFoundError).
    Nigdy nie zwraca pustej listy po cichu przy błędnym wejściu.

    Obsługa subtestów:
    Wiele znaczników <failure> w obrębie jednego <testcase> zostaje połączonych
    w jedno pole failure_message, nie gubiąc komunikatów asercji.

    Mapowanie test_id i source_stage:
    - acceptance-stage5 (<testsuite name="acceptance-stage5"):
      test_id = name, source_stage = "stage5:acceptance".
    - pytest JUnit:
      test_id = f"{classname}::{name}" (lub name), source_stage = "stage4:unit".
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Plik raportu JUnit nie istnieje: {file_path}")

    try:
        content = file_path.read_bytes()
    except OSError as exc:
        raise MalformedReportError(f"Nie udało się odczytać pliku {file_path}: {exc}") from exc

    if not content.strip():
        raise MalformedReportError(f"Plik raportu JUnit jest pusty: {file_path}")

    try:
        # S314: stdlib xml parsing zaufanych raportów z pipeline CI (wymóg PR A2 bez zewnętrznych zależności)
        root = ET.fromstring(content)  # noqa: S314 # nosec B314
    except ET.ParseError as exc:
        raise MalformedReportError(f"Niepoprawny lub ucięty plik XML w {file_path}: {exc}") from exc

    results: list[TestResult] = []

    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = root.findall("testsuite")
        if not suites:
            # Niektóre reportery umieszczają <testcase> bezpośrednio w <testsuites>
            testcases = root.findall("testcase")
            if testcases:
                suites = [root]
    else:
        raise MalformedReportError(
            f"Oczekiwano elementu głównego <testsuite> lub <testsuites>, otrzymano: <{root.tag}> w {file_path}"
        )

    for suite in suites:
        suite_name = suite.get("name", "")

        if source_stage is not None:
            stage = source_stage
        elif suite_name == "acceptance-stage5" or "acceptance" in suite_name.lower():
            stage = "stage5:acceptance"
        else:
            stage = "stage4:unit"

        for tc in suite.iter("testcase"):
            tc_name = tc.get("name", "").strip()
            if not tc_name:
                raise MalformedReportError(f"Element <testcase> bez atrybutu 'name' w {file_path}")

            classname = tc.get("classname", "").strip()

            if stage == "stage5:acceptance":
                test_id = tc_name
            elif classname:
                test_id = f"{classname}::{tc_name}"
            else:
                test_id = tc_name

            raw_time = tc.get("time")
            try:
                time_val = float(raw_time) if raw_time is not None else 0.0
                if time_val < 0.0:
                    time_val = 0.0
            except (ValueError, TypeError):
                time_val = 0.0

            failures = tc.findall("failure")
            errors = tc.findall("error")
            skipped = tc.findall("skipped")

            status = "pass"
            skip_reason: str | None = None
            failure_message: str | None = None

            if errors:
                status = "error"
                messages: list[str] = []
                for err in errors:
                    msg = err.get("message")
                    text = _clean_text(err)
                    detail = msg if msg else text
                    if detail:
                        messages.append(detail)
                failure_message = "\n".join(messages) if messages else "Error"
            elif failures:
                status = "fail"
                messages = []
                for fail in failures:
                    msg = fail.get("message")
                    text = _clean_text(fail)
                    if msg and text and msg != text:
                        messages.append(f"{msg}: {text}")
                    elif msg:
                        messages.append(msg)
                    elif text:
                        messages.append(text)
                failure_message = "\n".join(messages) if messages else "Assertion failed"
            elif skipped:
                status = "skip"
                reasons: list[str] = []
                for skip in skipped:
                    msg = skip.get("message")
                    text = _clean_text(skip)
                    detail = msg if msg else text
                    if detail:
                        reasons.append(detail)
                skip_reason = "; ".join(reasons) if reasons else None

            results.append(
                TestResult(
                    test_id=test_id,
                    status=status,
                    time=time_val,
                    skip_reason=skip_reason,
                    source_stage=stage,
                    failure_message=failure_message,
                )
            )

    return results


@dataclass
class FlakySummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_s: float = 0.0


def collect_reports(
    reports_path: str | Path,
    job: str = "4. Testy jednostkowe + pokrycie",
    commit_sha: str = "",
    run_id: str = "",
    attempt: int = 1,
) -> dict[str, Any]:
    """Zbiera i normalizuje wyniki testów z katalogu lub pliku raportów JUnit XML.

    Obsługuje raporty bats (np. build/test-reports/bats/report.xml) oraz pytest (pytest.xml).
    Gwarantuje unikalność test_id poprzez doklejanie sufiksów #2, #3 w przypadku duplikatów.
    W przypadku braku plików zwraca pustą, zwalidowaną strukturę schema_version 1.0 (fail-safe).
    """
    reports_dir = Path(reports_path)
    summary = FlakySummary()
    tests_payload: list[dict[str, Any]] = []
    seen_counts: dict[str, int] = {}

    eff_commit = commit_sha or os.environ.get("GITHUB_SHA", "unknown")
    eff_run_id = run_id or os.environ.get("GITHUB_RUN_ID", "0")
    try:
        eff_attempt = int(attempt or os.environ.get("GITHUB_RUN_ATTEMPT", 1))
    except (ValueError, TypeError):
        eff_attempt = 1

    empty_payload: dict[str, Any] = {
        "schema_version": "1.0",
        "job": job,
        "commit_sha": eff_commit,
        "run_id": eff_run_id,
        "attempt": eff_attempt,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "summary": asdict(summary),
        "tests": [],
    }

    if not reports_dir.exists():
        return empty_payload

    xml_files = [reports_dir] if reports_dir.is_file() else sorted(reports_dir.glob("**/*.xml"))

    if not xml_files:
        return empty_payload

    all_results: list[TestResult] = []
    for xml_file in xml_files:
        try:
            results = parse_junit(xml_file)
            all_results.extend(results)
        except Exception as exc:
            all_results.append(
                TestResult(
                    test_id=f"malformed_report::{xml_file.name}",
                    status="error",
                    time=0.0,
                    source_stage="stage4:unit",
                    failure_message=f"Błąd parsowania JUnit XML ({xml_file}): {exc}",
                )
            )

    for r in all_results:
        tid = r.test_id
        if tid in seen_counts:
            seen_counts[tid] += 1
            tid = f"{tid}#{seen_counts[tid]}"
        else:
            seen_counts[tid] = 1

        summary.total += 1
        summary.duration_s += r.time
        if r.status == "pass":
            summary.passed += 1
        elif r.status == "fail":
            summary.failed += 1
        elif r.status == "error":
            summary.errors += 1
        elif r.status == "skip":
            summary.skipped += 1

        tests_payload.append(
            {
                "test_id": tid,
                "status": r.status,
                "duration_s": round(r.time, 4),
                "source_stage": r.source_stage,
                "skip_reason": r.skip_reason,
                "failure_message": r.failure_message,
            }
        )

    summary.duration_s = round(summary.duration_s, 4)

    return {
        "schema_version": "1.0",
        "job": job,
        "commit_sha": eff_commit,
        "run_id": eff_run_id,
        "attempt": eff_attempt,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "summary": asdict(summary),
        "tests": tests_payload,
    }


def render_step_summary(payload: dict[str, Any]) -> str:
    """Renderuje zwięzłe podsumowanie Markdown dla GITHUB_STEP_SUMMARY."""
    s = payload.get("summary", {})
    job = payload.get("job", "")
    commit = str(payload.get("commit_sha", ""))[:8]
    attempt = payload.get("attempt", 1)

    lines = [
        "### Telemetria testów (per-test, #349)",
        "",
        f"**Job:** `{job}` | **Commit:** `{commit}` | **Attempt:** `{attempt}`",
        "",
        "| Metryka | Wartość |",
        "|---|---|",
        f"| Łącznie testów | {s.get('total', 0)} |",
        f"| Passed | {s.get('passed', 0)} |",
        f"| Failed | {s.get('failed', 0)} |",
        f"| Errors | {s.get('errors', 0)} |",
        f"| Skipped | {s.get('skipped', 0)} |",
        f"| Czas trwania | {s.get('duration_s', 0.0):.2f} s |",
        "",
    ]

    failures = [t for t in payload.get("tests", []) if t.get("status") in ("fail", "error")]
    if failures:
        lines.extend(
            [
                "#### Testy zakończone niepowodzeniem",
                "",
                "| Status | Test ID | Komunikat |",
                "|---|---|---|",
            ]
        )
        for f in failures:
            msg = (f.get("failure_message") or "").replace("\n", " ").replace("|", "\\|")[:120]
            lines.append(f"| `{f.get('status', '').upper()}` | `{f.get('test_id')}` | {msg} |")
        lines.append("")

    skipped = [t for t in payload.get("tests", []) if t.get("status") == "skip"]
    if skipped:
        lines.extend(
            [
                "#### Testy pominięte (skipped)",
                "",
                "| Test ID | Powód |",
                "|---|---|",
            ]
        )
        for sk in skipped:
            reason = (sk.get("skip_reason") or "brak powodu").replace("\n", " ").replace("|", "\\|")[:120]
            lines.append(f"| `{sk.get('test_id')}` | {reason} |")
        lines.append("")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Punkt wejścia CLI dla flaky_report.py."""
    parser = argparse.ArgumentParser(
        prog="flaky_report.py",
        description="Normalizator raportów JUnit XML (etap 4 i etap 5) dla WLB CI (#349)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser("parse", help="Parsuje pliki JUnit XML i generuje znormalizowany JSON")
    parse_cmd.add_argument("xml_files", nargs="+", type=Path, help="Ścieżki do plików XML (pytest / acceptance)")
    parse_cmd.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("build/ci-logs/flaky-raw.json"),
        help="Ścieżka zapisu znormalizowanego pliku JSON (domyślnie: build/ci-logs/flaky-raw.json)",
    )

    collect_cmd = subparsers.add_parser(
        "collect", help="Zbiera raporty z katalogu i generuje ustrukturyzowany flaky.json"
    )
    collect_cmd.add_argument("--reports", required=True, type=Path, help="Katalog lub plik raportów XML")
    collect_cmd.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Ścieżka do pliku wynikowego flaky.json (np. build/ci-logs/flaky.json)",
    )
    collect_cmd.add_argument("--job", default="4. Testy jednostkowe + pokrycie", help="Nazwa joba CI")
    collect_cmd.add_argument("--commit", default="", help="SHA commita")
    collect_cmd.add_argument("--run-id", default="", help="ID przebiegu GitHub Actions")
    collect_cmd.add_argument("--attempt", type=int, default=1, help="Numer próby (attempt)")
    collect_cmd.add_argument("--summary", action="store_true", help="Wypisz podsumowanie Markdown na stdout")

    summary_cmd = subparsers.add_parser("summary", help="Generuje podsumowanie Markdown ze wskazanego pliku flaky.json")
    summary_cmd.add_argument("json_file", type=Path, help="Ścieżka do pliku flaky.json")

    args = parser.parse_args(argv)

    if args.command == "parse":
        all_results: list[TestResult] = []
        try:
            for xml_file in args.xml_files:
                parsed = parse_junit(xml_file)
                all_results.extend(parsed)
        except (FlakyReportError, FileNotFoundError) as exc:
            print(f"BŁĄD parsowania JUnit XML: {exc}", file=sys.stderr)
            return 1

        payload = [asdict(r) for r in all_results]
        out_json = json.dumps(payload, indent=2, ensure_ascii=False)

        print(out_json)

        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(out_json + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"BŁĄD zapisu {args.output}: {exc}", file=sys.stderr)
            return 1

    elif args.command == "collect":
        collected_payload = collect_reports(
            reports_path=args.reports,
            job=args.job,
            commit_sha=args.commit,
            run_id=args.run_id,
            attempt=args.attempt,
        )

        out_json = json.dumps(collected_payload, indent=2, ensure_ascii=False)
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(out_json + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"BŁĄD zapisu {args.out}: {exc}", file=sys.stderr)
            return 1

        md_summary = render_step_summary(collected_payload)
        step_summary_env = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary_env:
            try:
                with open(step_summary_env, "a", encoding="utf-8") as f:
                    f.write(md_summary + "\n")
            except OSError as exc:
                print(f"Ostrzeżenie: nie udało się zapisać do GITHUB_STEP_SUMMARY: {exc}", file=sys.stderr)

        if args.summary:
            print(md_summary)
        else:
            print(f"Zebrano {collected_payload['summary']['total']} testów -> {args.out}")

    elif args.command == "summary":
        if not args.json_file.exists():
            print(f"BŁĄD: plik {args.json_file} nie istnieje", file=sys.stderr)
            return 1
        try:
            loaded_payload = json.loads(args.json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"BŁĄD odczytu {args.json_file}: {exc}", file=sys.stderr)
            return 1

        md_summary = render_step_summary(loaded_payload)
        print(md_summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
