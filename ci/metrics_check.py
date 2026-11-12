#!/usr/bin/env python3
"""Weryfikacja kontraktu metryk WLB na odpowiedzi node_exportera."""

import math
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Odpowiedź eksportera jest wystawiana do sieci monitoringu po HTTP bez uwierzytelnienia (#22),
# więc w CAŁEJ odpowiedzi (także node_*, nie tylko wlb_*) nie może być identyfikatorów badaczy:
# kont systemowych i stanowiskowych, katalogów domowych ani ścieżek wewnątrz udziałów §10
# (punkty montowania samych udziałów — "/workspace", "/sluza-out" — są dozwolone), ani sesji
# logind w zakresie UID badaczy. To kontrola regresji, nie dowód braku innych metadanych systemu.
PRIVACY_PATTERNS = {
    "konto systemowe badacza (jupyter-<login>)": re.compile(r"jupyter-"),
    "konto stanowiskowe badacza (uNN)": re.compile(r'="u(0[1-9]|[1-9][0-9])"'),
    "ścieżka wewnątrz udziału badaczy": re.compile(r'="/(workspace|sluza-in|sluza-out|data-mart|projekt)/[^"]'),
    "sesja logind w zakresie UID badaczy": re.compile(r"/run/user/(1[0-9]{4}|[2-5][0-9]{4})\b"),
}


def check_privacy(data: str) -> list[str]:
    """Identyfikatory badaczy w dowolnej metryce wystawianej na sieć (#22)."""
    errors = []
    for number, line in enumerate(data.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        for description, pattern in PRIVACY_PATTERNS.items():
            if pattern.search(line):
                errors.append(f"wiersz {number}: {description} w odpowiedzi eksportera: {line.split(' ', 1)[0][:120]}")
    return errors


def check(data: str, contract: dict) -> list[str]:
    selectors = contract["metrics"]["selectors"]
    errors = []
    if not selectors or len(set(selectors)) != len(selectors):
        errors.append("kontrakt ma puste lub powtórzone selektory")
    found = {}
    for line in data.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # Każda metryka wlb_* należy do kontraktu — nieznany prefiks (np. przyszłe wlb_hub_*) jest
        # zgłaszany jako nieznana metryka, a nie cicho pomijany.
        if len(parts) != 2 or not parts[0].startswith("wlb_"):
            continue
        if parts[0] in found:
            errors.append(f"duplikat metryki {parts[0]}")
        found[parts[0]] = parts[1]
    for selector in selectors:
        value = found.pop(selector, None)
        try:
            numeric = float(value) if value is not None else math.nan
        except ValueError:
            numeric = math.nan
        if not math.isfinite(numeric) or numeric < 0:
            errors.append(f"brak lub nieprawidłowa wartość {selector}")
        elif "_collect_success" in selector and numeric != 1:
            errors.append(f"nieudany pomiar {selector}")
        elif selector in ("wlb_health_auditd_active", "wlb_health_chrony_synchronised") and numeric not in (0, 1):
            errors.append(f"nieprawidłowy stan {selector}")
    if found:
        errors.append("nieznane metryki WLB: " + ", ".join(sorted(found)))
    errors.extend(check_privacy(data))
    return errors


def check_static(contract: dict, root: Path = ROOT) -> list[str]:
    metrics = contract["metrics"]
    selectors = metrics["selectors"]
    source = (root / metrics["source"]).read_text()
    errors = []
    if not selectors or len(set(selectors)) != len(selectors):
        errors.append("kontrakt ma puste lub powtórzone selektory")
    for selector in selectors:
        if selector.split("{", 1)[0] not in source:
            errors.append(f"metryka {selector} nie występuje w źródle")
    if metrics["endpoint"] != "http://127.0.0.1:9100/metrics":
        errors.append("nieoczekiwany lokalny endpoint metryk")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("użycie: metrics_check.py --static|plik-odpowiedzi-node-exporter", file=sys.stderr)
        return 2
    contract = yaml.safe_load((ROOT / "observability/contract.yml").read_text())
    errors = check_static(contract) if sys.argv[1] == "--static" else check(Path(sys.argv[1]).read_text(), contract)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f"Metryki WLB: {len(contract['metrics']['selectors'])} selektorów zgodnych z kontraktem")
    return 0


if __name__ == "__main__":
    sys.exit(main())
