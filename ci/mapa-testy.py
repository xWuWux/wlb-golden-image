#!/usr/bin/env python3
"""Generuje docs/mapa-testy-zgloszenia.md — mapę „zgłoszenie → test”.

Skanuje drzewo tests/ w poszukiwaniu znaczników #NN w tytułach testów
(@test, expect_ok/expect_fail/skip, def test_) i nagłówkach sekcji, i wiąże
każdy znacznik z nadrzędną jednostką testu. Tytuły i stan zgłoszeń pobiera z
GitHuba przez `gh` (jeśli dostępny; bez niego degraduje się łagodnie).

Uruchom z katalogu repozytorium:  python3 ci/mapa-testy.py
"""

from __future__ import annotations

import collections
import datetime
import glob
import json
import os
import re
import subprocess

DOC = "docs/mapa-testy-zgloszenia.md"

UNIT_PATTERNS = [
    re.compile(r'^\s*@test\s+"(.*?)"'),  # bats
    re.compile(r'^\s*(?:expect_ok|expect_fail)\s+"(.*?)"'),  # akceptacja/migracja
    re.compile(r'^\s*skip\s+"(.*?)"'),
    re.compile(r"^\s*def\s+(test_\w+)"),  # pytest
]
SECTION_PATTERNS = [
    re.compile(r"^\s*#\s*-{2,}\s*(.*?)\s*-{2,}\s*$"),
    re.compile(r'^\s*echo\s+"==\s*(.*?)\s*=="'),
    re.compile(r"^\s*#\s*={2,}\s*(.*?)\s*={2,}\s*$"),
]
TAG = re.compile(r"#(\d{1,3})\b")


def scan(root: str = "tests") -> dict[int, dict[str, set[str]]]:
    files = [
        f
        for f in glob.glob(f"{root}/**/*", recursive=True)
        if os.path.isfile(f) and "__pycache__" not in f and f.rsplit(".", 1)[-1] in ("sh", "bats", "py")
    ]
    out: dict[int, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))
    for f in files:
        current = None
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                unit = None
                for p in UNIT_PATTERNS:
                    m = p.match(line)
                    if m:
                        unit = m.group(1)
                        break
                if unit is None:
                    for p in SECTION_PATTERNS:
                        m = p.match(line)
                        if m:
                            unit = "§ " + m.group(1)
                            break
                if unit is not None:
                    current = unit
                for tag in TAG.findall(line):
                    if current is not None:  # pomijamy wzmianki spoza jednostki testu
                        out[int(tag)][f].add(current)
    return out


def gh_issues() -> tuple[dict[int, str], dict[int, str]]:
    try:
        rows = json.loads(
            subprocess.run(
                ["gh", "issue", "list", "--state", "all", "--limit", "200", "--json", "number,title,state"],  # noqa: S607 - gh z PATH, bez wejścia użytkownika
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
    except Exception:
        return {}, {}
    return ({r["number"]: r["title"] for r in rows}, {r["number"]: r["state"] for r in rows})


def main() -> None:
    data = scan()
    titles, states = gh_issues()
    badge = {"OPEN": "otwarte", "CLOSED": "scalone"}

    def fmt(u: str) -> str:
        return f"*{u[2:]}*" if u.startswith("§ ") else f"`{u}`"

    lines = [
        "# Mapa: zgłoszenie → test",
        "",
        "Dokument śledzi, które testy pilnują rozwiązania z poszczególnych zgłoszeń, "
        "żeby po każdym PR było widać, że **stare i nowe funkcjonalności nadal działają** "
        "(wymóg regresji dla Tier 4, DoD #46/#52). Zasada: patrz "
        "[CONTRIBUTING.md](../CONTRIBUTING.md) — „każda poprawka = test regresji”.",
        "",
        f"_Wygenerowano skryptem `ci/mapa-testy.py` z drzewa `tests/` "
        f"({datetime.date.today().isoformat()}). Odśwież: `python3 ci/mapa-testy.py`._",
        "",
        "## Pokrycie wg zgłoszeń",
        "",
    ]
    for issue in sorted(data):
        # pomijamy numery, które nie są zgłoszeniami (np. numery PR bez tytułu)
        if titles and issue not in titles:
            continue
        title = titles.get(issue, "")
        state = badge.get(states.get(issue), "—")
        lines.append(f"### #{issue} — {title}  ·  _{state}_")
        for f in sorted(data[issue]):
            units = sorted(data[issue][f])
            if not units:
                continue
            lines.append(f"- `{f}` — " + ", ".join(fmt(u) for u in units))
        lines.append("")
    lines += [
        "## Uwagi",
        "",
        "- **Mapa pokazuje testy z jawnym znacznikiem `#NN`.** Wiele zachowań jest "
        "pokrytych testami bez odwołania do zgłoszenia (pełny zestaw jednostkowy "
        "bats/pytest w `tests/unit/`, akceptacja e2e w `tests/acceptance-remote.sh`, "
        "migracja w `tests/migration-remote.sh`). Brak wiersza nie znaczy „brak testu”, "
        "lecz „brak znacznika” — przy nowych poprawkach dodawaj `#NN` w tytule/sekcji "
        "testu, aby trafił do mapy.",
        "- **Dryf zamrożonych wersji** (np. `markupsafe`) pilnuje test dryfu w etapie 5 "
        "oraz nocny pełny build (harmonogram `CI`) — to również forma regresji, łapiąca "
        "zmiany spoza repozytorium, zanim uderzą w PR.",
        "",
    ]
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"zapisano {DOC}: {len([i for i in data if not titles or i in titles])} zgłoszeń")


if __name__ == "__main__":
    main()
