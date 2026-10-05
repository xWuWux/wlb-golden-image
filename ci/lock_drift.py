#!/usr/bin/env python3
"""Porównanie zamrożonego środowiska Pythona z eksportem z gotowego obrazu (test dryfu, etap 5).

    python3 ci/lock_drift.py envs/python/environment.lock.yml build/artifacts/<wersja>/environment.lock.yml

`conda env export` podaje też przynależność pakietu do menedżera: dział conda albo podlistę pip.
Ten sam pakiet bywa obsługiwany przez oba menedżery — `markupsafe` chcą zarówno zależności conda
(`jinja2`), jak i zależności pip (stos Jupyter/TLJH). Jeżeli lock wskazuje starszą wersję niż
upstream, pip podnosi ją z PyPI i przy okazji usuwa record condy: pakiet zmienia dział, a wersja
pozostaje jedna i ta sama. To migracja menedżera, a nie dryf wersji — raportujemy ją jedną linią
jako uwagę i nie failujemy. Failujemy, gdy wersja się nie zgadza albo gdy pakiet znika z obrazu
lub się w nim pojawia.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# pip: "nazwa==wersja" (pomijamy znaczniki środowiska i zakresy); conda: "nazwa=wersja=budowanie"
_PIP_ENTRY = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)\s*==\s*(?P<version>[^,\s;]+)")


def name_key(name: str) -> str:
    """Klucz porównania nazw: PEP 503 — `MarkupSafe`, `markupsafe` i `foo_bar` to ta sama nazwa."""
    return name.strip().lower().replace("_", "-")


def sections(lock: dict) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    """Rozbiera lock na dwie tablice `{klucz: (nazwa, wersja)}`: dział conda i podlistę pip."""
    conda: dict[str, tuple[str, str]] = {}
    pip: dict[str, tuple[str, str]] = {}
    for dep in lock.get("dependencies", []):
        if isinstance(dep, dict):
            for entry in dep.get("pip", []):
                match = _PIP_ENTRY.match(entry.strip())
                if match:
                    pip[name_key(match["name"])] = (match["name"], match["version"])
        elif isinstance(dep, str):
            name, _, rest = dep.partition("=")
            conda[name_key(name)] = (name.strip(), rest.split("=")[0].strip())
    return conda, pip


def _side(lock: dict) -> dict[str, dict[str, tuple[str, str]]]:
    """`{klucz: {menedżer: (nazwa, wersja)}}` — wpis conda jest dokładany pierwszy."""
    conda, pip = sections(lock)
    side: dict[str, dict[str, tuple[str, str]]] = {}
    for manager, table in (("conda", conda), ("pip", pip)):
        for key, entry in table.items():
            side.setdefault(key, {})[manager] = entry
    return side


def compare(repo: dict, image: dict) -> tuple[list[str], list[str]]:
    """Zwraca `(problemy, uwagi)`: lock z repozytorium wobec eksportu z obrazu."""
    problems: list[str] = []
    notes: list[str] = []
    left, right = _side(repo), _side(image)

    for key in sorted(set(left) | set(right)):
        want, got = left.get(key), right.get(key)
        if want is None:
            manager = next(iter(got))
            name, version = got[manager]
            problems.append(f"Python: {name} {version} tylko w obrazie ({manager})")
            continue
        if got is None:
            manager = next(iter(want))
            name, version = want[manager]
            problems.append(f"Python: {name} {version} tylko w locku ({manager})")
            continue

        want_manager, got_manager = next(iter(want)), next(iter(got))
        name = got[got_manager][0]
        want_version, got_version = want[want_manager][1], got[got_manager][1]

        if len(want) > 1 or len(got) > 1:
            problems.append(f"Python: {name} — ten sam pakiet w działach {' i '.join(sorted(set(want) | set(got)))}")
        if not want_version or not got_version:
            notes.append(f"Python: {name} — wersja nieokreślona w locku albo w obrazie")
        elif want_version != got_version:
            zmiana = "" if want_manager == got_manager else f" ({want_manager} → {got_manager})"
            problems.append(f"Python: {name} — lock {want_version}, obraz {got_version}{zmiana}")
        elif want_manager != got_manager and len(want) == len(got) == 1:
            notes.append(
                f"Python: {name} {got_version} — zmienił menedżera {want_manager} → {got_manager}, wersja bez zmian"
            )

    return problems, notes


def main(argv: list[str]) -> int:
    """`main([lock_repozytorium, lock_z_obrazu])`: 0 gdy zgodne, 1 gdy dryf. Komunikaty na stdout."""
    repo = yaml.safe_load(Path(argv[0]).read_text()) or {}
    image = yaml.safe_load(Path(argv[1]).read_text()) or {}
    problems, notes = compare(repo, image)
    for note in notes:
        print("uwaga:", note)
    for problem in problems:
        print("DRYF:", problem)
    if not problems:
        print(f"Zamrożone wersje Pythona zgodne z obrazem ({len(_side(image))} pakietów)")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
