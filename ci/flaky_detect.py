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
import json
import os
import subprocess
import sys
from collections.abc import Sequence
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


def _local_tag(elem_tag: str) -> str:
    """Zwraca lokalną nazwę znacznika bez przestrzeni nazw (np. '{ns}failure' -> 'failure')."""
    return elem_tag.rsplit("}", 1)[-1]


def parse_junit(path: str | Path) -> dict[str, str]:
    """Parsuje jeden raport JUnit XML i zwraca mapę test_id -> status.

    test_id = f"{classname}::{name}" (spójnie z ci/flaky_report.py) albo samo name, gdy brak classname.
    Przy duplikacie test_id (np. pytest-repeat) status „zły" ma pierwszeństwo: fail/error > skip > pass,
    żeby jedno niepowodzenie w serii powtórzeń nie zniknęło za późniejszym pass.
    """
    file_path = Path(path)
    root = ElementTree.parse(str(file_path)).getroot()
    results: dict[str, str] = {}
    for testcase in root.iter("testcase"):
        name = testcase.get("name") or ""
        classname = testcase.get("classname") or ""
        test_id = f"{classname}::{name}" if classname else name
        if not test_id:
            continue
        status = STATUS_PASS
        for child in testcase:
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


def classify(runs: Sequence[dict[str, str]]) -> dict[str, str]:
    """Klasyfikuje każdy test_id na podstawie wyników wielu przebiegów.

    Brak test_id w części przebiegów jest IGNOROWANY (różnice selekcji/kolekcji nie są same w sobie
    dowodem flaky) — liczą się tylko faktycznie zaobserwowane statusy. Decyduje zbiór statusów ≠ skip:
    pass i (fail|error) razem -> flaky; same fail|error -> broken; same pass -> stable_pass.
    """
    all_ids: set[str] = set()
    for run in runs:
        all_ids.update(run)

    verdicts: dict[str, str] = {}
    for test_id in all_ids:
        observed = [run[test_id] for run in runs if test_id in run]
        non_skip = [s for s in observed if s != STATUS_SKIP]
        if not non_skip:
            verdicts[test_id] = VERDICT_SKIPPED
            continue
        has_pass = STATUS_PASS in non_skip
        has_fail = any(s in FAILING for s in non_skip)
        if has_pass and has_fail:
            verdicts[test_id] = VERDICT_FLAKY
        elif has_fail:
            verdicts[test_id] = VERDICT_BROKEN
        else:
            verdicts[test_id] = VERDICT_STABLE
    return verdicts


def build_payload(verdicts: dict[str, str], seeds: Sequence[int], target: str) -> dict:
    """Buduje znormalizowany ładunek JSON (kontrakt danych lane'u detekcji)."""
    flaky = sorted(t for t, v in verdicts.items() if v == VERDICT_FLAKY)
    broken = sorted(t for t, v in verdicts.items() if v == VERDICT_BROKEN)
    return {
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


def render_summary(payload: dict) -> str:
    """Podsumowanie Markdown do $GITHUB_STEP_SUMMARY."""
    counts = payload["counts"]
    seeds = ", ".join(str(s) for s in payload["seeds"])
    lines = [
        "### Detekcja niestabilności (losowa kolejność, #349)",
        "",
        f"Cel: `{payload['target']}` — {payload['runs']} przebiegi, ziarna: {seeds}.",
        "",
        "| kategoria | liczba |",
        "| --- | --- |",
        f"| stabilne (pass) | {counts[VERDICT_STABLE]} |",
        f"| **niestabilne (flaky)** | **{counts[VERDICT_FLAKY]}** |",
        f"| zepsute (broken, realna porażka) | {counts[VERDICT_BROKEN]} |",
        f"| pominięte (skip) | {counts[VERDICT_SKIPPED]} |",
        "",
    ]
    if payload["flaky"]:
        lines.append("**Niestabilne (różny wynik między ziarnami — prawdopodobnie zależność od kolejności):**")
        lines += [f"- `{t}`" for t in payload["flaky"]]
        seed0 = payload["seeds"][0]
        lines.append("")
        lines.append(f"Odtworzenie: `PYTEST_RANDOMLY_SEED={seed0} pytest -p randomly {payload['target']}`")
        lines.append("")
    if payload["broken"]:
        lines.append("**Zepsute (padły we WSZYSTKICH przebiegach — realna porażka, nie flaky; nie kwarantannować):**")
        lines += [f"- `{t}`" for t in payload["broken"]]
        lines.append("")
    if not payload["flaky"] and not payload["broken"]:
        lines.append("Brak niestabilnych i zepsutych testów w tym przebiegu.")
        lines.append("")
    return "\n".join(lines)


def run_suite(target: str, seed: int, reports_dir: Path, repeat: int = 0) -> Path:
    """Uruchamia pytest raz z danym ziarnem kolejności; zwraca ścieżkę raportu JUnit.

    Celowo NIE sprawdzamy kodu wyjścia pytest — porażka jest oczekiwanym SYGNAŁEM, który czytamy
    z JUnit. To klasyfikacja, nie retry-do-zielonego; sam job CI jest nieblokujący.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    xml = reports_dir / f"flaky-detect-seed{seed}.xml"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target, f"--junitxml={xml}"]
    if repeat and repeat > 1:
        cmd.append(f"--count={repeat}")
    env = dict(os.environ, PYTEST_RANDOMLY_SEED=str(seed))
    subprocess.run(cmd, env=env, check=False)  # noqa: S603 — argumenty kontrolowane, nie wejście użytkownika
    return xml


def main(argv: Sequence[str] | None = None) -> int:
    """Punkt wejścia CLI lane'u detekcji niestabilności."""
    parser = argparse.ArgumentParser(description="Detekcja niestabilności przez losową kolejność i powtórzenia (#349).")
    parser.add_argument("--target", default="tests/unit", help="Zakres testów pytest (domyślnie tests/unit).")
    parser.add_argument("--runs", type=int, default=5, help="Liczba przebiegów z różnymi ziarnami (domyślnie 5).")
    parser.add_argument("--seed-base", type=int, default=1000, help="Ziarno bazowe; kolejne przebiegi: base, base+1, …")
    parser.add_argument(
        "--repeat", type=int, default=0, help="Powtórzenia w sesji (pytest-repeat --count); 0 = wyłączone."
    )
    parser.add_argument("--reports", default="build/test-reports/flaky-detect", help="Katalog raportów JUnit.")
    parser.add_argument("--out", default="build/ci-logs/flaky-detect.json", help="Plik wyjściowy JSON.")
    parser.add_argument("--gate", action="store_true", help="Niezerowy kod przy flaky/broken (lokalnie, NIE w CI).")
    args = parser.parse_args(argv)

    if args.runs < 2:
        print("BŁĄD: --runs musi być >= 2 (detekcja wymaga porównania przebiegów).", file=sys.stderr)
        return 2

    reports_dir = Path(args.reports)
    seeds = [args.seed_base + i for i in range(args.runs)]
    runs: list[dict[str, str]] = []
    for seed in seeds:
        xml = run_suite(args.target, seed, reports_dir, repeat=args.repeat)
        if not xml.exists():
            print(f"BŁĄD: brak raportu JUnit dla ziarna {seed} ({xml}) — przebieg nie wystartował.", file=sys.stderr)
            return 2
        runs.append(parse_junit(xml))

    verdicts = classify(runs)
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
        if payload["flaky"]:
            return 2
        if payload["broken"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
