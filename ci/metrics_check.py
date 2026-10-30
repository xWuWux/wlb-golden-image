#!/usr/bin/env python3
"""Weryfikacja kontraktu metryk WLB na odpowiedzi node_exportera."""

import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


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
        if len(parts) != 2 or not parts[0].startswith(("wlb_health_", "wlb_export_queue_", "wlb_siem_spool_")):
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
