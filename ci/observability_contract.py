#!/usr/bin/env python3
"""Kontrakt obserwowalności VM (observability/contract.yml) — sprawdzenie statyczne i dynamiczne.

python3 ci/observability_contract.py static
    stage 3.5: kontrakt jest spójny, każde źródło logów w obrazie jest w nim opisane,
    kod emituje dokładnie te pola, które deklaruje kontrakt, klucze audytu i prefiksy
    logów zapory zgadzają się z kodem (w obie strony)

python3 ci/observability_contract.py verify-log build/ci-logs/siem.log [--expect-untrusted ZDARZENIE]
    stage 5: w logu odebranym przez testowy odbiornik SIEM są wszystkie zdarzenia
    oznaczone "acceptance: true", z poprawnymi wartościami pól i zaufanym pochodzeniem
    (pola [wlb@32473 ...] zgodne z regułą "trusted"); --expect-untrusted: test podszycia —
    wpis o treści zdarzenia wysłany przez badacza musi zostać rozpoznany jako niezaufany (#44)
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

# rsyslog wstawia przed treścią dwie spacje, logger(1) jedną — stąd \s*. Structured data to ciąg
# elementów [id param="wartość" ...] bez spacji między nimi; tekst po spacji należy już do treści,
# więc "[wlb@32473 uid=\"0\"]" wpisane przez nadawcę w treść nie jest polem zaufanym.
SD = r'(?:\[[^\s\]"]+(?:\s+[^\s=\]"]+="(?:[^"\\]|\\.)*")*\])+'
RFC5424 = re.compile(rf"^<\d+>1 \S+ (?P<host>\S+) (?P<app>\S+) \S+ \S+ (?P<sd>-|{SD})\s*(?P<msg>.*)$")
SD_ELEMENT = re.compile(r'\[(?P<id>[^\s\]"]+)(?P<params>(?:\s+[^\s=\]"]+="(?:[^"\\]|\\.)*")*)\]')
SD_PARAM = re.compile(r'([^\s=\]"]+)="((?:[^"\\]|\\.)*)"')
TRUST_KEYS = {"input", "uid", "uid_field"}
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
        errors += [f"{where}: {e}" for e in check_trust_rule(ev.get("trusted"), ev.get("fields", {}))]

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

    errors += [f"audyt: {e}" for e in check_trust_rule(audit.get("trusted"), {})]

    siem = contract.get("siem", {})
    forwarder = (root / siem["forwarder_file"]).read_text()
    if siem.get("forward_all") not in forwarder:
        errors.append(f"SIEM: {siem['forwarder_file']} nie przekazuje wszystkich zdarzeń ({siem.get('forward_all')})")
    # pola zaufane (#44): szablon przekazywania z elementem trusted_sd_id i włączone ParseTrusted w rsyslog
    sd_id, template = contract.get("trusted_sd_id", ""), siem.get("template", "")
    if f'template="{template}"' not in forwarder or f'template(name="{template}"' not in forwarder:
        errors.append(f"SIEM: {siem['forwarder_file']} nie przekazuje zdarzeń szablonem {template!r}")
    elif not re.search(rf"\[{re.escape(sd_id)} " + r'input=\\"%inputname%\\" uid=\\"%\\\$!uid%\\"', forwarder):
        errors.append(f"SIEM: szablon {template!r} nie dopisuje pól zaufanych [{sd_id} input=... uid=...]")
    trusted_input = siem.get("trusted_input", {})
    if not trusted_input or trusted_input["marker"] not in (root / trusted_input["file"]).read_text():
        errors.append(
            f"SIEM: rsyslog bez pól zaufanych nadawcy ({trusted_input.get('marker')!r} w {trusted_input.get('file')})"
        )
    return errors


def check_trust_rule(rule, fields: dict) -> list[str]:
    """Reguła pochodzenia zdarzenia (#44): input wymagany, uid — wyrażenie, uid_field — pole z treści."""
    if not isinstance(rule, dict) or "input" not in rule:
        return ["brak reguły trusted (od kogo musi pochodzić zdarzenie)"]
    errors = [f"nieznany klucz reguły trusted: {k}" for k in sorted(set(rule) - TRUST_KEYS)]
    if "uid" in rule:
        try:
            re.compile(rule["uid"])
        except re.error as e:
            errors.append(f"trusted.uid: błędne wyrażenie ({e})")
    if "uid_field" in rule and rule["uid_field"] not in fields:
        errors.append(f"trusted.uid_field: pola {rule['uid_field']!r} nie ma w polach zdarzenia")
    return errors


# --- sprawdzenie dynamiczne (log z odbiornika SIEM) -------------------------------------


def parse_syslog(lines: list[str]) -> list[dict]:
    records = []
    for line in lines:
        line = line.rstrip("\n")
        m = RFC5424.match(line) or RFC3164.match(line)
        if m:
            rec = m.groupdict()
            rec["sd"] = parse_sd(rec.get("sd") or "-")
            records.append(rec)
    return records


def parse_sd(sd: str) -> dict[str, dict[str, str]]:
    """Structured data RFC 5424 -> {id: {parametr: wartość}}."""
    if sd == "-":
        return {}
    return {
        m["id"]: {k: re.sub(r"\\(.)", r"\1", v) for k, v in SD_PARAM.findall(m["params"])}
        for m in SD_ELEMENT.finditer(sd)
    }


def untrusted_reason(rule: dict, rec: dict, values: dict, sd_id: str) -> str:
    """Pusty napis, gdy pochodzenie wpisu zgadza się z regułą; inaczej opis niezgodności."""
    trusted = rec.get("sd", {}).get(sd_id)
    if trusted is None:
        return f"brak pól zaufanych [{sd_id}]"
    if trusted.get("input") != rule["input"]:
        return f"input={trusted.get('input')!r}"
    uid = trusted.get("uid", "")
    if "uid" in rule and not re.search(rule["uid"], uid):
        return f"uid={uid!r}"
    if (field := rule.get("uid_field")) and values.get(field) != uid:
        return f"{field}={values.get(field)!r} w treści, uid nadawcy={uid!r}"
    return ""


def parse_kv(msg: str) -> dict[str, str]:
    """key=value oddzielone spacjami; wartość sięga do następnego " klucz=" (cmd może mieć spacje)."""
    parts = re.split(r"\s(?=[a-z_][a-z0-9_]*=)", msg.strip())
    return dict(p.split("=", 1) for p in parts if "=" in p)


def event_matches(ev: dict, rec: dict, sd_id: str = "") -> tuple[bool, str, str]:
    """(czy rekord ma treść tego zdarzenia, problem z wartościami, powód braku zaufania) — puste, gdy OK."""
    src, msg = ev["source"], rec["msg"]
    if "tag" in src and rec["app"] != src["tag"]:
        return False, "", ""
    values: dict[str, str] = {}
    problem = ""
    if ev["format"] == "kernel":
        if src["kernel_log_prefix"] not in msg:
            return False, "", ""
    elif ev["format"] == "text":
        if re.search(ev["pattern"], msg) is None:
            return False, "", ""
    else:
        marker = src.get("marker")
        if marker:
            if not msg.startswith(marker + " "):
                return False, "", ""
            msg = msg[len(marker) + 1 :]
        values = parse_kv(msg)
        if not set(ev["fields"]) & set(values):
            return False, "", ""
        bad = [f"{f}={values.get(f)!r}" for f, rx in ev["fields"].items() if not re.search(rx, values.get(f, ""))]
        problem = ", ".join(bad)
    return True, problem, untrusted_reason(ev["trusted"], rec, values, sd_id)


def verify_log(
    contract: dict, lines: list[str], expect_untrusted: tuple[str, ...] = ()
) -> tuple[list[tuple[str, str, str]], int]:
    records = parse_syslog(lines)
    sd_id = contract["trusted_sd_id"]
    rows, failures = [], 0
    for ev in contract["events"]:
        if not ev["acceptance"] and ev["name"] not in expect_untrusted:
            continue
        found, untrusted, invalid, why = 0, 0, "", ""
        for rec in records:
            matched, problem, reason = event_matches(ev, rec, sd_id)
            if not matched:
                continue
            if reason:  # treść zdarzenia, ale nadawca inny niż w regule — podszycie, nie zdarzenie
                untrusted += 1
                why = why or reason
            elif problem:
                invalid = invalid or problem
            else:
                found += 1
        note = f"; niezaufane (odrzucone): {untrusted}, np. {why}" if untrusted else ""
        if ev["acceptance"]:
            if found:
                rows.append((ev["name"], "OK", f"{found} zdarzeń{note}"))
            else:
                failures += 1
                detail = f"niepoprawne wartości: {invalid}" if invalid else "nie dotarło do SIEM"
                rows.append((ev["name"], "BRAK", detail + note))
        if ev["name"] in expect_untrusted:
            failures += untrusted == 0
            rows.append(
                (
                    f"{ev['name']} (podrobione)",
                    "OK" if untrusted else "BRAK",
                    f"rozpoznane jako niezaufane: {untrusted}, np. {why}"
                    if untrusted
                    else "wpis podrobiony w teście nie został rozpoznany jako niezaufany",
                )
            )
    rule = contract["audit"]["trusted"]
    for key in (k for k in contract["audit"]["keys"] if k["acceptance"]):
        recs = [r for r in records if f'key="{key["key"]}"' in r["msg"]]
        n = sum(not untrusted_reason(rule, r, {}, sd_id) for r in recs)
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
    verify.add_argument("--expect-untrusted", action="append", default=[], metavar="ZDARZENIE")
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

    rows, failures = verify_log(
        contract, args.log.read_text(errors="replace").splitlines(), tuple(args.expect_untrusted)
    )
    table = ["## Zdarzenia w logu centralnym (SIEM)", "", "| Zdarzenie | Status | Szczegóły |", "|---|---|---|"]
    table += [f"| {name} | {status} | {detail} |" for name, status, detail in rows]
    write_summary("\n".join(table) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
