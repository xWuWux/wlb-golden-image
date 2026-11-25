#!/usr/bin/env python3
"""Oceń wyniki etapu 6a względem budżetów i zapisz raport Markdown.

Wejścia produkuje `ci/perf.sh`:
  results.txt  — `<metryka> <wartość> <jednostka>`, `ERROR ...`, `RAW ...`, `DETAIL ...`
  samples.txt  — `SAMPLE <metryka> <liczba>...`

Kontrakt jest celowo ścisły: nieznana linia, duplikat, brak surowych próbek dla
zmierzonej metryki albo nieznany kierunek progu to błąd pomiaru/konfiguracji
(kod 2), a nie „brak regresji”. `PERF_ENFORCE=0` wyłącza wyłącznie bramkę
przekroczenia budżetu; błędy pomiaru zawsze kończą się kodem 2.

Kody wyjścia:
  0 — komplet pomiarów w budżecie (albo przekroczenia w trybie report-only)
  1 — przekroczenie budżetu przy PERF_ENFORCE=1
  2 — błąd pomiaru lub konfiguracji
"""

from __future__ import annotations

import argparse
import math
import re
import statistics
import sys
from pathlib import Path

METRIC_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VALUE_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
UNIT_RE = re.compile(r"^[A-Za-z%/._-]+$")

# Jawny kierunek progu. Sufiks nazwy nie jest wystarczający: `_mbps` bywa
# mylone z megabitami, a nowe metryki (`_iops`, `_rps`) nie mogą przypadkiem
# dostać porównania „mniejsze jest lepsze”.
DIRECTIONS = {
    "boot_to_ready_s": "max",
    "hub_login_ms": "max",
    "spawn_first_ms": "max",
    "python_import_pandas_ms": "max",
    "pandas_groupby_5m_ms": "max",
    "r_load_hades_ms": "max",
    "workspace_write_mbps": "min",
    "workspace_read_mbps": "min",
}
UNITS = {
    "boot_to_ready_s": "s",
    "hub_login_ms": "ms",
    "spawn_first_ms": "ms",
    "python_import_pandas_ms": "ms",
    "pandas_groupby_5m_ms": "ms",
    "r_load_hades_ms": "ms",
    "workspace_write_mbps": "MiB/s",
    "workspace_read_mbps": "MiB/s",
}


class PerfError(ValueError):
    """Nieprawidłowe wejście albo niespójny artefakt pomiarowy."""


def parse_bool(raw: str, name: str = "wartość") -> bool:
    """Przyjmij 1/true/yes/on i 0/false/no/off; każdą inną wartość odrzuć."""
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise PerfError(f"{name}={raw!r}: oczekiwano 0/1, true/false, yes/no albo on/off")


def parse_status(raw: str) -> int:
    try:
        status = int(raw)
    except ValueError as exc:
        raise PerfError(f"remote_status={raw!r}: oczekiwano kodu 0..255") from exc
    if not 0 <= status <= 255:
        raise PerfError(f"remote_status={raw}: oczekiwano kodu 0..255")
    return status


def parse_budget(path: Path) -> dict[str, float]:
    budget: dict[str, float] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise PerfError(f"{path}:{number}: oczekiwano klucz=wartość")
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not METRIC_RE.fullmatch(key):
            raise PerfError(f"{path}:{number}: nieprawidłowa nazwa metryki {key!r}")
        if key in budget:
            raise PerfError(f"{path}:{number}: duplikat metryki {key}")
        if key not in DIRECTIONS:
            raise PerfError(f"{path}:{number}: brak jawnego kierunku progu dla {key}")
        if not VALUE_RE.fullmatch(raw_value):
            raise PerfError(f"{path}:{number}: nieprawidłowy próg {raw_value!r}")
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0:
            raise PerfError(f"{path}:{number}: próg musi być dodatni i skończony")
        budget[key] = value
    if not budget:
        raise PerfError(f"{path}: pusty budżet")
    return budget


def parse_results(path: Path) -> tuple[dict[str, tuple[float, str]], list[str]]:
    measured: dict[str, tuple[float, str]] = {}
    errors: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] in {"DETAIL", "RAW"}:
            continue
        if parts[0] == "ERROR":
            if len(parts) < 2:
                raise PerfError(f"{path}:{number}: ERROR bez nazwy metryki")
            if not METRIC_RE.fullmatch(parts[1]):
                raise PerfError(f"{path}:{number}: ERROR bez poprawnej nazwy metryki")
            errors.append(line)
            continue
        if len(parts) != 3:
            raise PerfError(f"{path}:{number}: oczekiwano '<metryka> <wartość> <jednostka>'")
        metric, raw_value, unit = parts
        if not METRIC_RE.fullmatch(metric):
            raise PerfError(f"{path}:{number}: nieprawidłowa nazwa metryki {metric!r}")
        if metric in measured:
            raise PerfError(f"{path}:{number}: duplikat metryki {metric}")
        if not VALUE_RE.fullmatch(raw_value):
            raise PerfError(f"{path}:{number}: nieprawidłowa wartość {raw_value!r}")
        if not UNIT_RE.fullmatch(unit):
            raise PerfError(f"{path}:{number}: nieprawidłowa jednostka {unit!r}")
        expected_unit = UNITS.get(metric)
        if expected_unit is not None and unit != expected_unit:
            raise PerfError(f"{path}:{number}: {metric}: oczekiwano jednostki {expected_unit}, jest {unit}")
        measured[metric] = (float(raw_value), unit)
    return measured, errors


def parse_samples(path: Path) -> dict[str, tuple[int, ...]]:
    samples: dict[str, tuple[int, ...]] = {}
    if not path.exists():
        return samples
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2 or parts[0] != "SAMPLE":
            raise PerfError(f"{path}:{number}: oczekiwano 'SAMPLE <metryka> <próbki...>'")
        metric = parts[1]
        if not METRIC_RE.fullmatch(metric):
            raise PerfError(f"{path}:{number}: nieprawidłowa nazwa metryki {metric!r}")
        if metric in samples:
            raise PerfError(f"{path}:{number}: duplikat serii {metric}")
        values = parts[2:]
        if not values or any(not value.isdigit() for value in values):
            raise PerfError(f"{path}:{number}: próbki muszą być nieujemnymi liczbami całkowitymi")
        samples[metric] = tuple(int(value) for value in values)
    return samples


def _error_metric(line: str) -> str:
    return line.split()[1]


def render(
    budget: dict[str, float],
    measured: dict[str, tuple[float, str]],
    samples: dict[str, tuple[int, ...]],
    errors: list[str],
    remote_status: int,
    enforce: bool,
) -> tuple[str, int]:
    rows: list[str] = []
    over = 0
    missing = 0
    invalid = 0

    for key, limit in budget.items():
        direction = DIRECTIONS[key]
        symbol = "≤" if direction == "max" else "≥"
        if key not in measured:
            rows.append(f"| {key} | — | {symbol} {limit:g} | 0 | BŁĄD POMIARU |")
            missing += 1
            continue
        value, unit = measured[key]
        series = samples.get(key, ())
        count = len(series)
        if count == 0:
            rows.append(f"| {key} | {value:g} {unit} | {symbol} {limit:g} | 0 | BŁĄD POMIARU (brak próbek) |")
            invalid += 1
            continue
        ok = value <= limit if direction == "max" else value >= limit
        over += not ok
        note = "OK" if ok else "PRZEKROCZONY"
        if count < 3:
            note += " (n<3 — za mało do kalibracji)"
        rows.append(f"| {key} | {value:g} {unit} | {symbol} {limit:g} | {count} | {note} |")

    if errors or missing or invalid or remote_status:
        status = "BŁĄD POMIARU"
    elif over and enforce:
        status = "PRZEKROCZENIE BUDŻETU"
    elif over:
        status = "PRZEKROCZENIE BUDŻETU (tylko raport)"
    else:
        status = "PASS"

    lines = [
        "### Benchmarki wydajności",
        "",
        f"**Wynik:** {status}",
        "",
        "| Metryka | Wynik | Budżet | n | Status |",
        "|---|---|---|---|---|",
        *rows,
        "",
    ]
    if errors:
        lines += [
            "#### Błędy pomiaru",
            "",
            "| Metryka | Szczegóły |",
            "|---|---|",
            *[f"| {_error_metric(error)} | `{error}` |" for error in errors],
            "",
        ]
    notes: list[str] = []
    if remote_status:
        notes.append(f"Skrypt zdalny zakończył się kodem {remote_status}; wynik nie jest kompletny.")
    if not enforce and over:
        notes.append("PERF_ENFORCE=0: przekroczenia budżetu są raportowane, ale nie blokują joba.")
    if any(len(samples.get(key, ())) < 3 for key in budget):
        notes.append("n<3: pojedyncze przebiegi nie wystarczają do kalibracji progu; to tylko smoke test.")
    if notes:
        lines += [f"- {note}" for note in notes]
        lines.append("")

    exit_code = 0
    if errors or missing or invalid or remote_status:
        exit_code = 2
    elif over and enforce:
        exit_code = 1
    return "\n".join(lines), exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--remote-status", default="0")
    parser.add_argument("--enforce", default="1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        enforce = parse_bool(args.enforce, "PERF_ENFORCE")
        remote_status = parse_status(args.remote_status)
        budget = parse_budget(args.budget)
        measured, errors = parse_results(args.results)
        samples = parse_samples(args.samples)
        unknown = (set(measured) | set(samples)) - set(budget)
        if unknown:
            raise PerfError(f"metryki bez progu w budżecie: {', '.join(sorted(unknown))}")
        for metric, (value, _) in measured.items():
            series = samples.get(metric)
            if series is None:
                continue
            if not math.isclose(value, statistics.median(series), rel_tol=0, abs_tol=1e-6):
                raise PerfError(f"{metric}: wartość {value:g} nie jest medianą próbek {list(series)}")
        text, exit_code = render(budget, measured, samples, errors, remote_status, enforce)
    except (OSError, PerfError) as exc:
        text = (
            "### Benchmarki wydajności\n\n"
            f"**BŁĄD POMIARU/KONFIGURACJI:** {exc}\n\n"
            "Nie oceniano budżetów; szczegóły w logu joba.\n"
        )
        exit_code = 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
