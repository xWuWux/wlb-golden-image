#!/usr/bin/env python3
"""Parsuje maszynowy raport Lynis (lynis-report.dat) i składa podsumowanie Markdown do etapu 5 (#11).

Raport Lynis to linie klucz=wartość, m.in.:
    hardening_index=67
    warning[]=opis|TEST-ID|szczegóły|rozwiązanie
    suggestion[]=opis|TEST-ID|szczegóły|rozwiązanie

Domyślnie to RAPORT: utwardzenie audytu walidują osobne testy akceptacyjne (auditctl/ausearch),
a wiele „sugestii" Lynis to świadome odstępstwa opisane w #11. Z flagą --gate skrypt staje się
bramką REGRESJI (#288): błąd, gdy hardening_index spadnie poniżej baseline (domyślnie 72) albo
pojawi się dowolne warning[]. Nie wymagamy absolutnego 100 — pilnujemy tylko, żeby nie było gorzej.
W etapie 5 bramkę włącza WLB_LYNIS_GATING=1; bez niej wynik pozostaje raportem.
"""

from __future__ import annotations

import contextlib
import re
import sys

TEST_ID = re.compile(r"^[A-Z]{2,5}-[0-9]{3,4}$")
DEFAULT_BASELINE = 72  # bieżący hardening_index obrazu; poniżej = regresja (#288)


def _entry(value: str) -> dict[str, str]:
    """Rozbija wartość warning[]/suggestion[] na komunikat i (jeśli jest) identyfikator testu Lynis."""
    fields = [f.strip() for f in value.split("|")]
    msg = next((f for f in fields if f), value.strip())
    test = next((f for f in fields if TEST_ID.match(f)), "")
    return {"msg": msg, "test": test}


def parse_report(text: str) -> dict:
    """Zwraca {hardening_index: int|None, warnings: [...], suggestions: [...]} z treści lynis-report.dat."""
    hardening: int | None = None
    warnings: list[dict[str, str]] = []
    suggestions: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "hardening_index":
            with contextlib.suppress(ValueError):
                hardening = int(value.strip())
        elif key == "warning[]":
            warnings.append(_entry(value))
        elif key == "suggestion[]":
            suggestions.append(_entry(value))
    return {"hardening_index": hardening, "warnings": warnings, "suggestions": suggestions}


def gate_failures(data: dict, baseline: int = DEFAULT_BASELINE) -> list[str]:
    """Powody oblania bramki regresji: spadek poniżej baseline albo dowolne ostrzeżenie Lynis."""
    failures: list[str] = []
    hi = data["hardening_index"]
    if hi is None:
        failures.append("brak hardening_index w raporcie (raport niekompletny)")
    elif hi < baseline:
        failures.append(f"hardening index {hi} < baseline {baseline}")
    for warning in data["warnings"]:
        test = f" [{warning['test']}]" if warning["test"] else ""
        failures.append(f"ostrzeżenie Lynis: {warning['msg']}{test}")
    return failures


def _item(e: dict[str, str]) -> str:
    return f"- {e['msg']}" + (f" [{e['test']}]" if e["test"] else "")


def render_markdown(data: dict, max_suggestions: int = 25, *, gating: bool = False) -> str:
    """Składa sekcję podsumowania przebiegu (GITHUB_STEP_SUMMARY)."""
    hi = data["hardening_index"]
    warns = data["warnings"]
    sugg = data["suggestions"]
    hi_txt = f"**{hi} / 100**" if hi is not None else "**brak** (raport niekompletny)"
    mode = (
        "Bramka regresji: spadek poniżej baseline lub nowe ostrzeżenie = błąd (#288)."
        if gating
        else "Raport przeglądowy (nie bramka). Audyt walidują osobne testy akceptacyjne; "
        "świadome odstępstwa opisane w #11."
    )
    out = [
        "### Utwardzenie systemu — Lynis",
        "",
        f"Hardening index: {hi_txt} · ostrzeżenia: **{len(warns)}** · sugestie: **{len(sugg)}**",
        "",
        mode,
        "",
    ]
    if warns:
        out += [f"<details><summary>Ostrzeżenia ({len(warns)})</summary>", ""]
        out += [_item(e) for e in warns]
        out += ["", "</details>"]
    shown = sugg[:max_suggestions]
    if sugg:
        more = f" — pokazano {len(shown)} z {len(sugg)}" if len(sugg) > len(shown) else ""
        out += ["", f"<details><summary>Sugestie ({len(sugg)}){more}</summary>", ""]
        out += [_item(e) for e in shown]
        out += ["", "</details>"]
    out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    gate = False
    baseline = DEFAULT_BASELINE
    path: str | None = None
    args = argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--gate":
            gate = True
        elif arg == "--baseline":
            if i + 1 >= len(args):
                print("--baseline wymaga liczby", file=sys.stderr)
                return 2
            i += 1
            try:
                baseline = int(args[i])
            except ValueError:
                print(f"nieprawidłowy baseline: {args[i]}", file=sys.stderr)
                return 2
        elif arg.startswith("-"):
            print(f"nieznana opcja: {arg}", file=sys.stderr)
            return 2
        elif path is None:
            path = arg
        else:
            print("użycie: lynis_report.py [--gate] [--baseline N] <lynis-report.dat>", file=sys.stderr)
            return 2
        i += 1
    if path is None:
        print("użycie: lynis_report.py [--gate] [--baseline N] <lynis-report.dat>", file=sys.stderr)
        return 2
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        if gate:
            # przy włączonej bramce brak raportu = fail-closed (nie da się potwierdzić baseline)
            print(
                f"### Utwardzenie systemu — Lynis\n\nBrak raportu Lynis ({exc.strerror}) — "
                "bramka WLB_LYNIS_GATING=1 (fail-closed)."
            )
            return 1
        # bez bramki brak raportu to nie błąd kroku — Lynis mógł się nie wykonać (krok opcjonalny)
        print(f"### Utwardzenie systemu — Lynis\n\nBrak raportu Lynis ({exc.strerror}) — pomijam.")
        return 0
    data = parse_report(text)
    print(render_markdown(data, gating=gate))
    if not gate:
        return 0
    failures = gate_failures(data, baseline)
    if failures:
        print("\n### Bramka utwardzenia Lynis — FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"\n### Bramka utwardzenia Lynis — PASS (baseline {baseline})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
