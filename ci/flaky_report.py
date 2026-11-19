"""Parser i normalizator raportów JUnit XML (etap 4 pytest + etap 5 akceptacja).

Zgodny ze specyfikacją PR A2 dla issue #349.
Obsługuje dwa źródła raportów:
1. Pytest JUnit XML (etap 4) — test_id = f"{classname}::{name}" (lub name, gdy brak classname).
2. Acceptance JUnit XML (etap 5: acceptance-stage5) — test_id = name.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


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

    return 0


if __name__ == "__main__":
    sys.exit(main())
