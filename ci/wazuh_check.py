#!/usr/bin/env python3
"""Wynik wazuh-logtest zgodny z kontraktem obserwowalności (#17).

    python3 ci/wazuh_check.py build/wazuh/siem.jsonl [--require-all] [--expect-untrusted ZDARZENIE]...

Wejście: JSON Lines z ci/wazuh_logtest_client.py ({"line": ..., "output": ...}).
Dla każdego wiersza oczekiwanie wyznacza ta sama logika co verify-log (event_matches z
ci/observability_contract.py), więc „co jest zdarzeniem” jest zdefiniowane w jednym miejscu:

- wiersz z treścią zdarzenia od zaufanego nadawcy -> reguła z grupą wlb_ev_<zdarzenie>
  i nazwane pola: dla kv pola z kontraktu, dla text grupy nazwane wzorca (wlb.<pole>);
  wiersz pasujący do kilku zdarzeń (firstboot.done jest też firstboot.message) — do któregokolwiek;
- ta sama treść od niezaufanego nadawcy (#44) -> reguła z grupą wlb_spoof, nigdy wlb_ev_*;
- SYSCALL audytu z kluczem wlb_* od audisp-syslog -> grupa wlb_audit i wlb.audit_key = klucz.

Każde zdarzenie z acceptance: true i każdy klucz audytu z acceptance: true musi wystąpić co
najmniej raz; --require-all rozszerza to na cały kontrakt (próbka w etapie 3.5).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import observability_contract as oc

AUDIT_KEY = re.compile(r'\bkey="(wlb_[a-z_]+)"')
SPOOF_GROUP = "wlb_spoof"
AUDIT_GROUP = "wlb_audit"


def group_for(event: str) -> str:
    return f"wlb_ev_{event}"


def expected_fields(ev: dict) -> list[str]:
    if ev["format"] == "kv":
        return list(ev["fields"])
    if ev["format"] == "text":
        return list(re.compile(ev["pattern"]).groupindex)
    return []


def load_results(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Tally:
    def __init__(self) -> None:
        self.ok: dict[str, int] = defaultdict(int)
        self.untrusted: dict[str, int] = defaultdict(int)
        self.errors: dict[str, list[str]] = defaultdict(list)

    def fail(self, name: str, message: str) -> None:
        self.errors[name].append(message)


def check(contract: dict, results: list[dict]) -> tuple[Tally, int, int]:
    sd_id = contract["trusted_sd_id"]
    audit_rule = contract["audit"]["trusted"]
    tally = Tally()
    ours = decoded = 0
    for res in results:
        line, out = res["line"], res.get("output") or {}
        rule = out.get("rule") or {}
        groups = set(rule.get("groups") or [])
        fields = (out.get("data") or {}).get("wlb") or {}
        where = f"reguła {rule.get('id', '-')}: {line[:160]}"
        recs = oc.parse_syslog([line])
        if not recs or sd_id not in recs[0]["sd"]:
            continue
        rec = recs[0]
        ours += 1
        decoded += (out.get("decoder") or {}).get("name") == "wlb"

        candidates = []
        for ev in contract["events"]:
            matched, problem, reason = oc.event_matches(ev, rec, sd_id)
            if not matched:
                continue
            name = ev["name"]
            if reason:
                tally.untrusted[name] += 1
                if SPOOF_GROUP not in groups or any(g.startswith("wlb_ev_") for g in groups):
                    tally.fail(name, f"podrobiony wpis ({reason}) nie trafił w regułę podszycia — {where}")
            elif not problem:  # niepoprawne wartości zgłasza verify-log; tu nie oczekujemy reguły
                candidates.append(ev)
        hits = [ev for ev in candidates if group_for(ev["name"]) in groups]
        if candidates and not hits:
            names = ", ".join(group_for(ev["name"]) for ev in candidates)
            tally.fail(candidates[0]["name"], f"brak grupy {names} — {where}")
        for ev in hits:
            missing = [f for f in expected_fields(ev) if f not in fields]
            if missing:
                tally.fail(ev["name"], f"brak pól wlb.{', wlb.'.join(missing)} — {where}")
            else:
                tally.ok[ev["name"]] += 1

        if rec["app"] == "audisp-syslog" and "type=SYSCALL " in rec["msg"] and (m := AUDIT_KEY.search(rec["msg"])):
            name = f"audit:{m.group(1)}"
            if oc.untrusted_reason(audit_rule, rec, {}, sd_id):
                continue
            if AUDIT_GROUP not in groups or fields.get("audit_key") != m.group(1):
                tally.fail(name, f"brak grupy {AUDIT_GROUP} albo wlb.audit_key — {where}")
            else:
                tally.ok[name] += 1
    return tally, ours, decoded


def report(contract: dict, tally: Tally, ours: int, decoded: int, require_all: bool, untrusted: tuple[str, ...]):
    rows, failures = [], 0
    required = [(e["name"], require_all or e["acceptance"]) for e in contract["events"]]
    required += [(f"audit:{k['key']}", require_all or k["acceptance"]) for k in contract["audit"]["keys"]]
    for name, needed in required:
        errs = tally.errors.get(name, [])
        ok = tally.ok.get(name, 0)
        if errs:
            failures += 1
            rows.append((name, "BŁĄD", f"{len(errs)} niezgodnych, np. {errs[0]}"))
        elif ok:
            rows.append((name, "OK", f"{ok} zdekodowanych"))
        elif needed:
            failures += 1
            rows.append((name, "BRAK", "brak zdarzenia w logu — nie sprawdzono dekodera"))
    for name in untrusted:
        if not tally.untrusted.get(name) or tally.errors.get(name):
            failures += 1
            rows.append((f"{name} (podrobione)", "BRAK", "podrobiony wpis nie trafił w regułę podszycia"))
        else:
            rows.append((f"{name} (podrobione)", "OK", f"{tally.untrusted[name]} w regule podszycia"))
    if ours and decoded != ours:
        failures += 1
        rows.append(("dekoder wlb", "BŁĄD", f"zdekodowano {decoded} z {ours} wierszy z nagłówkiem WLB"))
    else:
        rows.append(("dekoder wlb", "OK", f"zdekodowano {decoded} z {ours} wierszy z nagłówkiem WLB"))
    return rows, failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--repo-root", type=Path, default=oc.REPO_ROOT)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--expect-untrusted", action="append", default=[], metavar="ZDARZENIE")
    args = parser.parse_args(argv)
    contract = oc.load_contract(args.repo_root)
    tally, ours, decoded = check(contract, load_results(args.results))
    rows, failures = report(contract, tally, ours, decoded, args.require_all, tuple(args.expect_untrusted))
    table = ["## Wazuh: dekodery i reguły WLB", "", "| Zdarzenie | Status | Szczegóły |", "|---|---|---|"]
    table += [f"| {n} | {s} | {d} |" for n, s, d in rows]
    oc.write_summary("\n".join(table) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
