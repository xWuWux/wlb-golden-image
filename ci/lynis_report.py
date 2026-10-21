#!/usr/bin/env python3
"""Parsuje maszynowy raport Lynis (lynis-report.dat) i składa podsumowanie Markdown do etapu 5 (#11).

Raport Lynis to linie klucz=wartość, m.in.:
    hardening_index=67
    warning[]=opis|TEST-ID|szczegóły|rozwiązanie
    suggestion[]=opis|TEST-ID|szczegóły|rozwiązanie

To RAPORT, nie bramka: utwardzenie audytu walidują osobne testy akceptacyjne (auditctl/ausearch),
a wiele „sugestii" Lynis to świadome odstępstwa opisane w #11. Skrypt nigdy nie zwraca błędu z powodu
treści raportu — służy wyłącznie do czytelnego zestawienia (hardening index + ostrzeżenia/sugestie).
"""

from __future__ import annotations

import contextlib
import re
import sys

TEST_ID = re.compile(r"^[A-Z]{2,5}-[0-9]{3,4}$")


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


def _item(e: dict[str, str]) -> str:
    return f"- {e['msg']}" + (f" [{e['test']}]" if e["test"] else "")


def render_markdown(data: dict, max_suggestions: int = 25) -> str:
    """Składa sekcję podsumowania przebiegu (GITHUB_STEP_SUMMARY)."""
    hi = data["hardening_index"]
    warns = data["warnings"]
    sugg = data["suggestions"]
    hi_txt = f"**{hi} / 100**" if hi is not None else "**brak** (raport niekompletny)"
    out = [
        "### Utwardzenie systemu — Lynis",
        "",
        f"Hardening index: {hi_txt} · ostrzeżenia: **{len(warns)}** · sugestie: **{len(sugg)}**",
        "",
        "Raport przeglądowy (nie bramka). Audyt walidują osobne testy akceptacyjne; świadome odstępstwa opisane w #11.",
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
    if len(argv) != 2:
        print("użycie: lynis_report.py <lynis-report.dat>", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        # brak raportu to nie błąd kroku — Lynis mógł się nie wykonać (krok opcjonalny)
        print(f"### Utwardzenie systemu — Lynis\n\nBrak raportu Lynis ({exc.strerror}) — pomijam.")
        return 0
    print(render_markdown(parse_report(text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
