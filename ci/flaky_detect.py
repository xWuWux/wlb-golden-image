#!/usr/bin/env python3
"""Detekcja niestabilności przez losową kolejność i powtórzenia (#349, lane NIEBRAMKUJĄCY).

Ten lane celowo NIE zamienia porażki na sukces — żadnego retry-do-zielonego. Uruchamia wskazany
zestaw testów kilka razy z RÓŻNYMI ziarnami `pytest-randomly` (losowa kolejność) i opcjonalnie
powtórzeniami w sesji (`pytest-repeat`), zbiera JUnit XML z każdego przebiegu i klasyfikuje każdy
test:

  stable_pass — przeszedł (poza SKIP) we WSZYSTKICH przebiegach,
  broken      — upadł we WSZYSTKICH przebiegach: to NIE jest flaky, lecz realna porażka,
                której nie wolno kwarantannować ani ukrywać — sygnalizujemy ją osobno,
  flaky       — wynik RÓŻNI się między przebiegami (nondeterminizm / zależność od kolejności).

Uzasadnienie kolejności: w Pythonie dominującą przyczyną flaky jest zależność od kolejności testów
(Gruber i in., ICST 2021 — ~59%), niewidoczna dla ponawiania w tej samej kolejności. Dlatego mierzymy
przez tasowanie kolejności, nie przez rerun do zielonego.

Każdy przebieg zapisuje użyte ziarno (PYTEST_RANDOMLY_SEED), żeby porażkę dało się odtworzyć:
`PYTEST_RANDOMLY_SEED=<seed> pytest -p randomly <target>`.

Wyjście: `build/ci-logs/flaky-detect.json` + podsumowanie Markdown (dla $GITHUB_STEP_SUMMARY).
Domyślnie report-only (kod 0). `--gate` zmienia TYLKO lokalny kod wyjścia dla ręcznego użycia
(flaky → 2, broken → 1); w CI job jest `continue-on-error` i nigdy nie blokuje bramki.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree  # bezpieczny parser lokalnych raportów JUnit (jak w etapie 4b)

# Statusy testu z JUnit; „pass" to brak dziecka failure/error/skipped.
STATUS_PASS = "pass"  # noqa: S105 — to status testu z JUnit, nie hasło
STATUS_FAIL = "fail"
STATUS_ERROR = "error"
STATUS_SKIP = "skip"
FAILING = frozenset({STATUS_FAIL, STATUS_ERROR})

VERDICT_STABLE = "stable_pass"
VERDICT_BROKEN = "broken"
VERDICT_FLAKY = "flaky"
VERDICT_SKIPPED = "skipped"


@dataclass(frozen=True)
class RunResult:
    """Wynik pojedynczego przebiegu zestawu testów pod danym ziarnem."""

    seed: int
    xml: Path
    exit_code: int
    tests: int
    duration_s: float
    timed_out: bool = False


class ClassificationResult(dict[str, str]):
    """Słownik mapujący test_id na werdykt, z rozszerzonymi szczegółami per-test."""

    def __init__(self, verdicts: dict[str, str], details: dict[str, dict]):
        super().__init__(verdicts)
        self.details = details


def _local_tag(elem_tag: str) -> str:
    """Zwraca lokalną nazwę znacznika bez przestrzeni nazw (np. '{ns}failure' -> 'failure')."""
    return elem_tag.rsplit("}", 1)[-1]


def parse_junit(path: str | Path) -> dict[str, str]:
    """Parsuje jeden raport JUnit XML i zwraca mapę test_id -> status.

    test_id = f"{classname}::{name}" (spójnie z ci/flaky_report.py) albo samo name, gdy brak classname.
    Przy duplikacie test_id (np. pytest-repeat) status „zły" ma pierwszeństwo: fail/error > skip > pass,
    żeby jedno niepowodzenie w serii powtórzeń nie zniknęło za późniejszym pass.
    Obsługuje poprawnie raporty z przestrzenią nazw XML (xmlns).
    """
    file_path = Path(path)
    try:
        root = ElementTree.parse(str(file_path)).getroot()
    except (OSError, ElementTree.ParseError) as exc:
        raise ValueError(f"Niepoprawny lub nieczytelny plik JUnit XML '{file_path}': {exc}") from exc

    results: dict[str, str] = {}
    for elem in root.iter():
        if _local_tag(elem.tag) != "testcase":
            continue
        name = elem.get("name") or ""
        classname = elem.get("classname") or ""
        test_id = f"{classname}::{name}" if classname else name
        if not test_id:
            continue
        status = STATUS_PASS
        for child in elem:
            tag = _local_tag(child.tag)
            if tag == "failure":
                status = STATUS_FAIL
                break
            if tag == "error":
                status = STATUS_ERROR
                break
            if tag == "skipped":
                status = STATUS_SKIP
                break
        results[test_id] = _worse_status(results.get(test_id), status)
    return results


def _worse_status(current: str | None, new: str) -> str:
    """Łączy statusy tego samego test_id (duplikaty z pytest-repeat): najgorszy wygrywa."""
    order = {STATUS_ERROR: 3, STATUS_FAIL: 3, STATUS_SKIP: 1, STATUS_PASS: 0}
    if current is None:
        return new
    return new if order.get(new, 0) > order.get(current, 0) else current


def classify(
    runs: Sequence[dict[str, str]],
    seeds: Sequence[int] | None = None,
) -> ClassificationResult:
    """Klasyfikuje każdy test_id na podstawie wyników wielu przebiegów.

    Śledzi obserwowane statusy, ziarna niepowodzeń i ewentualne braki testów w części przebiegów.
    Brak test_id w części przebiegów oznacza niespójność kolekcji/wykonania i jest klasyfikowany jako flaky.
    """
    actual_seeds = list(seeds) if seeds is not None else list(range(len(runs)))
    all_ids: set[str] = set()
    for run in runs:
        all_ids.update(run)

    verdicts: dict[str, str] = {}
    details: dict[str, dict] = {}

    for test_id in all_ids:
        fail_seeds: list[int] = []
        pass_seeds: list[int] = []
        skip_seeds: list[int] = []
        missing_seeds: list[int] = []

        for idx, run in enumerate(runs):
            seed = actual_seeds[idx] if idx < len(actual_seeds) else idx
            if test_id not in run:
                missing_seeds.append(seed)
                continue
            st = run[test_id]
            if st in FAILING:
                fail_seeds.append(seed)
            elif st == STATUS_PASS:
                pass_seeds.append(seed)
            elif st == STATUS_SKIP:
                skip_seeds.append(seed)

        if not fail_seeds and not pass_seeds:
            verdict = VERDICT_SKIPPED
        elif fail_seeds and not pass_seeds and not missing_seeds:
            verdict = VERDICT_BROKEN
        elif fail_seeds and pass_seeds:
            verdict = VERDICT_FLAKY
        elif missing_seeds and (fail_seeds or pass_seeds):
            # Brak testu w części przebiegów oznacza niespójność wykonania (kolekcja/wyścig)
            verdict = VERDICT_FLAKY
        elif pass_seeds and not fail_seeds and not missing_seeds:
            verdict = VERDICT_STABLE
        else:
            verdict = VERDICT_FLAKY

        verdicts[test_id] = verdict
        details[test_id] = {
            "verdict": verdict,
            "fail_seeds": fail_seeds,
            "pass_seeds": pass_seeds,
            "skip_seeds": skip_seeds,
            "missing_seeds": missing_seeds,
        }

    return ClassificationResult(verdicts, details)


def build_payload(
    verdicts: dict[str, str] | ClassificationResult,
    seeds: Sequence[int],
    target: str,
    details: dict[str, dict] | None = None,
) -> dict:
    """Buduje znormalizowany ładunek JSON (kontrakt danych lane'u detekcji)."""
    flaky = sorted(t for t, v in verdicts.items() if v == VERDICT_FLAKY)
    broken = sorted(t for t, v in verdicts.items() if v == VERDICT_BROKEN)
    if details is None and isinstance(verdicts, ClassificationResult):
        details = verdicts.details

    payload: dict = {
        "schema_version": 1,
        "target": target,
        "seeds": list(seeds),
        "runs": len(seeds),
        "counts": {
            VERDICT_STABLE: sum(1 for v in verdicts.values() if v == VERDICT_STABLE),
            VERDICT_FLAKY: len(flaky),
            VERDICT_BROKEN: len(broken),
            VERDICT_SKIPPED: sum(1 for v in verdicts.values() if v == VERDICT_SKIPPED),
        },
        "flaky": flaky,
        "broken": broken,
    }
    if details:
        payload["details"] = details
    return payload


def render_summary(payload: dict) -> str:
    """Podsumowanie Markdown do $GITHUB_STEP_SUMMARY z precyzyjnym wskazaniem ziarna awarii."""
    counts = payload.get("counts", {})
    seeds_list = payload.get("seeds", [])
    seeds_str = ", ".join(str(s) for s in seeds_list) if seeds_list else "brak"
    target = payload.get("target", "tests/unit")
    runs_count = payload.get("runs", len(seeds_list))
    details = payload.get("details", {})

    lines = [
        "### Detekcja niestabilności (losowa kolejność, #349)",
        "",
        f"Cel: `{target}` — {runs_count} przebiegi, ziarna: {seeds_str}.",
        "",
        "| kategoria | liczba |",
        "| --- | --- |",
        f"| stabilne (pass) | {counts.get(VERDICT_STABLE, 0)} |",
        f"| **niestabilne (flaky)** | **{counts.get(VERDICT_FLAKY, 0)}** |",
        f"| zepsute (broken, realna porażka) | {counts.get(VERDICT_BROKEN, 0)} |",
        f"| pominięte (skip) | {counts.get(VERDICT_SKIPPED, 0)} |",
        "",
    ]
    if payload.get("flaky"):
        lines.append("**Niestabilne (różny wynik między ziarnami — prawdopodobnie zależność od kolejności):**")
        for t in payload["flaky"]:
            t_det = details.get(t, {})
            fail_seeds = t_det.get("fail_seeds", [])
            if fail_seeds:
                fail_seed = fail_seeds[0]
                fail_info = f" (padł przy ziarnie: {fail_seed})"
                reproduce_seed = fail_seed
            else:
                missing_seeds = t_det.get("missing_seeds", [])
                fail_info = f" (brak w ziarnach: {missing_seeds})" if missing_seeds else ""
                reproduce_seed = seeds_list[0] if seeds_list else 1000
            lines.append(f"- `{t}`{fail_info}")
            short_name = t.split("::")[-1]
            lines.append(
                f"  Odtworzenie: `PYTEST_RANDOMLY_SEED={reproduce_seed} pytest -p randomly {target} -k '{short_name}'`"
            )
        lines.append("")
    if payload.get("broken"):
        lines.append("**Zepsute (padły we WSZYSTKICH przebiegach — realna porażka, nie flaky; nie kwarantannować):**")
        for t in payload["broken"]:
            lines.append(f"- `{t}`")
        lines.append("")
    if not payload.get("flaky") and not payload.get("broken"):
        lines.append("Brak niestabilnych i zepsutych testów w tym przebiegu.")
        lines.append("")
    return "\n".join(lines)


def run_suite(
    target: str,
    seed: int,
    reports_dir: Path,
    repeat: int = 0,
    timeout: int = 600,
    cwd: Path | None = None,
) -> RunResult:
    """Uruchamia pytest raz z danym ziarnem kolejności; zwraca RunResult.

    Usuwa stary raport przed uruchomieniem, pilnuje limitu czasu, izoluje grupę procesów
    i zlicza wykonane testy.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    xml = reports_dir / f"flaky-detect-seed{seed}.xml"
    xml.unlink(missing_ok=True)

    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target, f"--junitxml={xml}"]
    if repeat and repeat > 1:
        cmd.append(f"--count={repeat}")

    env = dict(os.environ, PYTEST_RANDOMLY_SEED=str(seed))
    work_dir = cwd or Path.cwd()

    t0 = time.monotonic()
    timed_out = False
    proc = subprocess.Popen(cmd, env=env, cwd=str(work_dir), start_new_session=True)  # noqa: S603
    try:
        proc.communicate(timeout=timeout)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        exit_code = -signal.SIGKILL
    duration_s = time.monotonic() - t0

    test_count = 0
    if xml.exists() and not timed_out:
        try:
            parsed = parse_junit(xml)
            test_count = len(parsed)
        except Exception:
            test_count = 0

    return RunResult(
        seed=seed,
        xml=xml,
        exit_code=exit_code,
        tests=test_count,
        duration_s=duration_s,
        timed_out=timed_out,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Punkt wejścia CLI lane'u detekcji niestabilności."""
    parser = argparse.ArgumentParser(description="Detekcja niestabilności przez losową kolejność i powtórzenia (#349).")
    parser.add_argument("--target", default="tests/unit", help="Zakres testów pytest (domyślnie tests/unit).")
    parser.add_argument("--runs", type=int, default=5, help="Liczba przebiegów z różnymi ziarnami (domyślnie 5).")
    parser.add_argument("--seed-base", type=int, default=1000, help="Ziarno bazowe; kolejne przebiegi: base, base+1, …")
    parser.add_argument(
        "--repeat", type=int, default=0, help="Powtórzenia w sesji (pytest-repeat --count); 0 = wyłączone."
    )
    parser.add_argument("--timeout", type=int, default=600, help="Limit czasu w sekundach na jeden przebieg pytest.")
    parser.add_argument(
        "--min-tests", type=int, default=1, help="Wymagana minimalna liczba zebranych testów w przebiegu."
    )
    parser.add_argument("--cwd", default=None, help="Katalog roboczy dla uruchomienia pytest.")
    parser.add_argument("--reports", default="build/test-reports/flaky-detect", help="Katalog raportów JUnit.")
    parser.add_argument("--out", default="build/ci-logs/flaky-detect.json", help="Plik wyjściowy JSON.")
    parser.add_argument("--gate", action="store_true", help="Niezerowy kod przy flaky/broken (lokalnie, NIE w CI).")
    args = parser.parse_args(argv)

    if args.runs < 2:
        print("BŁĄD: --runs musi być >= 2 (detekcja wymaga porównania przebiegów).", file=sys.stderr)
        return 2

    if args.repeat < 0:
        print("BŁĄD: --repeat musi być >= 0.", file=sys.stderr)
        return 2

    if args.timeout <= 0:
        print("BŁĄD: --timeout musi być > 0.", file=sys.stderr)
        return 2

    if args.min_tests < 1:
        print("BŁĄD: --min-tests musi być >= 1.", file=sys.stderr)
        return 2

    work_cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    reports_dir = Path(args.reports)
    seeds = [args.seed_base + i for i in range(args.runs)]
    runs: list[dict[str, str]] = []

    for seed in seeds:
        res = run_suite(
            args.target,
            seed,
            reports_dir,
            repeat=args.repeat,
            timeout=args.timeout,
            cwd=work_cwd,
        )
        if isinstance(res, RunResult):
            timed_out = res.timed_out
            exit_code = res.exit_code
            xml = res.xml
            tests_count = res.tests
        else:
            xml = Path(res)
            timed_out = False
            exit_code = 0
            try:
                tests_count = len(parse_junit(xml))
            except Exception:
                tests_count = 0

        if timed_out:
            print(
                f"BŁĄD: Przebieg dla ziarna {seed} przekroczył limit czasu {args.timeout}s.",
                file=sys.stderr,
            )
            return 2
        if exit_code not in (0, 1):
            print(
                f"BŁĄD: pytest zakończył się kodem błędu {exit_code} dla ziarna {seed} (błąd wykonania/kolekcji).",
                file=sys.stderr,
            )
            return 2
        if not xml.exists():
            print(
                f"BŁĄD: brak raportu JUnit dla ziarna {seed} ({xml}) — raport nie został wygenerowany.",
                file=sys.stderr,
            )
            return 2
        if tests_count < args.min_tests:
            print(
                f"BŁĄD: Przebieg dla ziarna {seed} zebrał {tests_count} testów "
                f"(wymagane minimum: {args.min_tests}). Pusty raport nie może udawać braku problemów.",
                file=sys.stderr,
            )
            return 2

        try:
            parsed = parse_junit(xml)
        except ValueError as exc:
            print(f"BŁĄD: nie udało się sparsować raportu JUnit: {exc}", file=sys.stderr)
            return 2
        runs.append(parsed)

    verdicts = classify(runs, seeds)
    payload = build_payload(verdicts, seeds, args.target)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = render_summary(payload)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")

    if args.gate:
        if payload["broken"]:
            return 1
        if payload["flaky"]:
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
