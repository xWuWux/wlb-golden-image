#!/usr/bin/env python3
"""Kontrakt obserwowalności VM (observability/contract.yml) — sprawdzenie statyczne i dynamiczne.

python3 ci/observability_contract.py static
    stage 3.5: kontrakt jest spójny, każde źródło logów w obrazie jest w nim opisane,
    kod emituje dokładnie te pola, które deklaruje kontrakt, klucze audytu i prefiksy
    logów zapory zgadzają się z kodem (w obie strony)

python3 ci/observability_contract.py verify-log build/ci-logs/siem.log
    stage 5: w logu odebranym przez testowy odbiornik SIEM są wszystkie zdarzenia
    oznaczone "acceptance: true", z poprawnymi wartościami pól
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIRS = ["ansible"]  # zawartość obrazu — tu szukamy źródeł logów

LOGGER_TAG = re.compile(r"\blogger\b.*?\s-t\s+([A-Za-z0-9_.-]+)")
NFT_PREFIX = re.compile(r'log prefix "([^"]+)"')
AUDIT_KEY = re.compile(r"\s-k\s+(\S+)")
KV_FIELD = re.compile(r"(?<![A-Za-z0-9_])([a-z_][a-z0-9_]*)=")

# rsyslog (RSYSLOG_SyslogProtocol23Format) wstawia przed treścią dwie spacje, logger(1) jedną — stąd \s*
RFC5424 = re.compile(r"^<\d+>1 \S+ (?P<host>\S+) (?P<app>\S+) \S+ \S+ (?:-|\[.*?\])\s*(?P<msg>.*)$")
RFC3164 = re.compile(r"^(?:<\d+>)?\w{3} [ \d]\d [\d:]{8} (?P<host>\S+) (?P<app>[^:\[\s]+)(?:\[\d+\])?: ?(?P<msg>.*)$")


def load_contract(root: Path) -> dict:
    return yaml.safe_load((root / "observability/contract.yml").read_text())


# --- sprawdzenie statyczne ------------------------------------------------------------


def image_files(root: Path) -> list[Path]:
    return sorted(p for d in IMAGE_DIRS for p in (root / d).rglob("*") if p.is_file())


def quoted(line: str) -> str:
    """Treść komunikatu: od pierwszego do ostatniego cudzysłowu w linii."""
    first, last = line.find('"'), line.rfind('"')
    return line[first + 1 : last] if last > first else line


def emitting_lines(text: str, source: dict) -> list[str]:
    marker, tag = source.get("marker"), source.get("tag")
    if marker:
        return [line for line in text.splitlines() if f'"{marker} ' in line or f'"{marker}"' in line]
    return [line for line in text.splitlines() if "logger" in line and f"-t {tag}" in line]


def check_static(root: Path, contract: dict) -> list[str]:
    errors: list[str] = []
    conv = {k: re.compile(v) for k, v in contract["conventions"].items()}
    events = contract.get("events", [])

    names = [e["name"] for e in events]
    errors += [f"zdarzenie {n}: zduplikowana nazwa" for n in sorted({n for n in names if names.count(n) > 1})]

    declared_tags: set[str] = set()
    declared_prefixes: set[str] = set()
    for ev in events:
        name, src, fmt = ev["name"], ev.get("source", {}), ev.get("format")
        where = f"zdarzenie {name}"
        if not conv["event_name"].match(name):
            errors.append(f"{where}: nazwa niezgodna z konwencją {conv['event_name'].pattern}")
        if not isinstance(ev.get("acceptance"), bool):
            errors.append(f"{where}: brak pola acceptance (true/false)")
        if fmt not in ("kv", "text", "kernel"):
            errors.append(f"{where}: nieznany format {fmt!r}")
            continue
        if fmt == "kv" and not ev.get("fields"):
            errors.append(f"{where}: format kv wymaga listy pól")
        if fmt == "text" and not ev.get("pattern"):
            errors.append(f"{where}: format text wymaga wzorca")
        for field in ev.get("fields", {}):
            if not conv["field_name"].match(field):
                errors.append(f"{where}: pole {field!r} niezgodne z konwencją")

        if "tag" in src:
            declared_tags.add(src["tag"])
            if not conv["syslog_tag"].match(src["tag"]):
                errors.append(f"{where}: tag {src['tag']!r} niezgodny z konwencją")
        if "kernel_log_prefix" in src:
            declared_prefixes.add(src["kernel_log_prefix"])
        if "file" not in src:
            continue
        path = root / src["file"]
        if not path.is_file():
            errors.append(f"{where}: plik {src['file']} nie istnieje")
            continue
        text = path.read_text()
        if "tag" in src and not re.search(rf"\blogger\b.*\s-t\s+{re.escape(src['tag'])}\b", text):
            errors.append(f"{where}: {src['file']} nie loguje z tagiem {src['tag']}")
        if fmt == "kv":
            lines = emitting_lines(text, src)
            if not lines:
                errors.append(f"{where}: nie znaleziono miejsca emisji w {src['file']}")
            for line in lines:
                emitted = set(KV_FIELD.findall(quoted(line)))
                declared = set(ev["fields"])
                if missing := sorted(declared - emitted):
                    errors.append(f"{where}: kod nie emituje pól {', '.join(missing)}")
                if extra := sorted(emitted - declared):
                    errors.append(f"{where}: kod emituje pola spoza kontraktu: {', '.join(extra)}")
        elif fmt == "text" and src.get("marker") and src["marker"] not in text:
            errors.append(f"{where}: brak komunikatu z {src['marker']!r} w {src['file']}")

    # źródła w kodzie obrazu, których nie ma w kontrakcie (i odwrotnie)
    code_tags: dict[str, str] = {}
    code_prefixes: dict[str, str] = {}
    for path in image_files(root):
        for line in path.read_text(errors="replace").splitlines():
            if m := LOGGER_TAG.search(line):
                code_tags.setdefault(m.group(1), str(path.relative_to(root)))
            for prefix in NFT_PREFIX.findall(line):
                code_prefixes.setdefault(prefix, str(path.relative_to(root)))
    errors += [
        f"tag syslog {t!r} ({f}) nie jest opisany w kontrakcie"
        for t, f in sorted(code_tags.items())
        if t not in declared_tags
    ]
    errors += [
        f"prefiks logu zapory {p!r} ({f}) nie jest opisany w kontrakcie"
        for p, f in sorted(code_prefixes.items())
        if p not in declared_prefixes
    ]
    errors += [
        f"prefiks logu zapory {p!r} z kontraktu nie występuje w kodzie"
        for p in sorted(declared_prefixes - set(code_prefixes))
    ]

    audit = contract.get("audit", {})
    rules = (root / audit["rules_file"]).read_text()
    code_keys = {k for line in rules.splitlines() if not line.lstrip().startswith("#") for k in AUDIT_KEY.findall(line)}
    contract_keys = {k["key"] for k in audit.get("keys", [])}
    errors += [f"klucz audytu {k} (reguły) nie jest opisany w kontrakcie" for k in sorted(code_keys - contract_keys)]
    errors += [f"klucz audytu {k} z kontraktu nie występuje w regułach" for k in sorted(contract_keys - code_keys)]
    errors += [
        f"klucz audytu {k} niezgodny z konwencją" for k in sorted(contract_keys) if not conv["audit_key"].match(k)
    ]

    siem = contract.get("siem", {})
    if siem.get("forward_all") not in (root / siem["forwarder_file"]).read_text():
        errors.append(f"SIEM: {siem['forwarder_file']} nie przekazuje wszystkich zdarzeń ({siem.get('forward_all')})")
    return errors


# --- sprawdzenie dynamiczne (log z odbiornika SIEM) -------------------------------------


def parse_syslog(lines: list[str]) -> list[dict]:
    records = []
    for line in lines:
        line = line.rstrip("\n")
        m = RFC5424.match(line) or RFC3164.match(line)
        if m:
            records.append(m.groupdict())
    return records


def parse_kv(msg: str) -> dict[str, str]:
    """key=value oddzielone spacjami; wartość sięga do następnego " klucz=" (cmd może mieć spacje)."""
    parts = re.split(r"\s(?=[a-z_][a-z0-9_]*=)", msg.strip())
    return dict(p.split("=", 1) for p in parts if "=" in p)


def event_matches(ev: dict, rec: dict) -> tuple[bool, str]:
    """(czy rekord jest tym zdarzeniem, opis problemu z wartościami — pusty, gdy poprawny)."""
    src, msg = ev["source"], rec["msg"]
    if "tag" in src and rec["app"] != src["tag"]:
        return False, ""
    if ev["format"] == "kernel":
        return src["kernel_log_prefix"] in msg, ""
    if ev["format"] == "text":
        return re.search(ev["pattern"], msg) is not None, ""
    marker = src.get("marker")
    if marker:
        if not msg.startswith(marker + " "):
            return False, ""
        msg = msg[len(marker) + 1 :]
    values = parse_kv(msg)
    if not set(ev["fields"]) & set(values):
        return False, ""
    bad = [f"{f}={values.get(f)!r}" for f, rx in ev["fields"].items() if not re.search(rx, values.get(f, ""))]
    return True, ", ".join(bad)


def verify_log(contract: dict, lines: list[str]) -> tuple[list[tuple[str, str, str]], int]:
    records = parse_syslog(lines)
    rows, failures = [], 0
    for ev in (e for e in contract["events"] if e["acceptance"]):
        found, invalid = 0, ""
        for rec in records:
            matched, problem = event_matches(ev, rec)
            if matched and not problem:
                found += 1
            elif matched and not invalid:
                invalid = problem
        if found:
            rows.append((ev["name"], "OK", f"{found} zdarzeń"))
        else:
            failures += 1
            rows.append((ev["name"], "BRAK", f"niepoprawne wartości: {invalid}" if invalid else "nie dotarło do SIEM"))
    for key in (k for k in contract["audit"]["keys"] if k["acceptance"]):
        n = sum(f'key="{key["key"]}"' in r["msg"] for r in records)
        failures += n == 0
        rows.append((f"audit:{key['key']}", "OK" if n else "BRAK", f"{n} zdarzeń" if n else "nie dotarło do SIEM"))
    return rows, failures


# --- CLI -------------------------------------------------------------------------------------


def write_summary(text: str) -> None:
    print(text)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):  # pragma: no cover
        with open(path, "a") as f:
            f.write(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("static")
    verify = sub.add_parser("verify-log")
    verify.add_argument("log", type=Path)
    args = parser.parse_args(argv)
    contract = load_contract(args.repo_root)

    if args.command == "static":
        errors = check_static(args.repo_root, contract)
        n_events, n_keys = len(contract["events"]), len(contract["audit"]["keys"])
        lines = ["## Kontrakt obserwowalności", "", f"Zdarzenia: {n_events}, klucze audytu: {n_keys}."]
        lines += (
            ["", "**Wszystko zgodne z kodem.**"] if not errors else ["", "Niezgodności:", *[f"- {e}" for e in errors]]
        )
        write_summary("\n".join(lines) + "\n")
        return 1 if errors else 0

    rows, failures = verify_log(contract, args.log.read_text(errors="replace").splitlines())
    table = ["## Zdarzenia w logu centralnym (SIEM)", "", "| Zdarzenie | Status | Szczegóły |", "|---|---|---|"]
    table += [f"| {name} | {status} | {detail} |" for name, status, detail in rows]
    write_summary("\n".join(table) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
