#!/usr/bin/env python3
"""Kontrakt zmiennych wdrożeniowych: `/etc/wlb/lab.env` ↔ `wlb-firstboot` ↔ przykłady.

Obraz jest budowany raz i stawiany wiele razy — wszystko, co zależy od Laboratorium,
przekazuje się przy wdrożeniu przez `/etc/wlb/lab.env` (cloud-init `write_files`, prawa
0600), a `wlb-firstboot` czyta te zmienne i waliduje je PRZED zmianą zapory. Zmienna,
która istnieje w jednym miejscu, a nie w drugim, jest cichym błędem wdrożenia:

- w `wlb-firstboot`, ale nie w `lab.env.example` — administrator Laboratorium nie wie,
  że może ją ustawić; zostaje domyślna wartość na wszystkich VM;
- w `wlb-firstboot`, ale nie w `lab-user-data.example.yaml` — brak działającego przykładu
  `write_files` dla nowej zmiennej per-Lab;
- w `lab.env.example`, ale nie w `wlb-firstboot` — dokumentacja obiecuje parametr,
  którego obraz nie czyta (np. została po usuniętej funkcji);
- inna wartość domyślna w dokumentacji i w kodzie — administrator widzi jedno, VM robi drugie.

Dlatego ten moduł jest bramką CI (etap 3.5, `ci/observability.sh`), a nie konwencją.
Zmienne obrazu wspólne dla wszystkich Laboratoriów (`WLB_*` w `/etc/wlb/image.conf`,
nadpisania w `WLB_*` dla testów) świadomie nie należą do tego kontraktu i są pomijane.

Wypisuje błędy (jeden na wiersz) i kończy się kodem 1, jeśli są.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FIRSTBOOT = "ansible/roles/lab_config/files/wlb-firstboot"
ENV_EXAMPLE = "cloud-init/lab.env.example"
USERDATA_EXAMPLE = "cloud-init/lab-user-data.example.yaml"
LAB_ENV_PATH = "/etc/wlb/lab.env"

# Nazwy czytane z lab.env, które nie podlegają kontraktowi: wspólne dla obrazu (image.conf)
# albo nadpisania na potrzeby testów jednostkowych (`WLB_ENV_FILE`, `WLB_HUB_URL`, ...).
_EXEMPT_PREFIX = "WLB_"

# `: "${LAB_NAME:?komunikat}"` — zmienna wymagana, brak wartości przerywa firstboot (fail-secure).
_REQUIRED = re.compile(r'^[ \t]*:[ \t]*"\$\{(?P<name>[A-Z][A-Z0-9_]*):\?', re.MULTILINE)
# `SIEM_PORT=${SIEM_PORT:-514}` — zmienna opcjonalna z wartością domyślną (tylko samoodwołanie;
# `HUB_URL=${WLB_HUB_URL:-...}` to zmienna lokalna skryptu, nie parametr wdrożenia).
_OPTIONAL = re.compile(r"^(?P<name>[A-Z][A-Z0-9_]*)=\$\{(?P=name):-(?P<default>[^}]*)\}(?:[ \t]+#.*)?$", re.MULTILINE)

# Wpis w pliku typu lab.env: `KLUCZ=wartość`, także zakomentowany wzór (`#KLUCZ=...`).
_ENV_LINE = re.compile(r"^[ \t]*(?P<comment>#[ \t]*)?(?P<name>[A-Z][A-Z0-9_]*)=(?P<value>.*)$", re.MULTILINE)

# Placeholder w przykładzie (`<id aplikacji>`, `...`) — nie jest wartością domyślną, nie porównujemy.
_PLACEHOLDER = re.compile(r"[<>]|\.\.\.")


def _strip_comment(value: str) -> str:
    """Obcina komentarz na końcu wartości (`6514   # opis`) i otaczające cudzysłowy."""
    match = re.search(r"[ \t]+#", value)
    if match:
        value = value[: match.start()]
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


@dataclass(frozen=True)
class Entry:
    """Wpis `KLUCZ=wartość` z pliku konfiguracji wdrożenia.

    `commented` odróżnia wzór opcjonalny (`#RESEARCHER_MEM_LIMIT=16G` — dokumentuje wartość
    domyślną) od wartości faktycznie przekazywanej (`HUB_TLS=1` — to, co ląduje na VM).
    """

    value: str
    commented: bool


def parse_env(text: str) -> dict[str, Entry]:
    """Zmienne z pliku wzoru/wdrożenia: nazwa -> wpis (także zakomentowane wzory).

    Pierwszy wpis danej nazwy wygrywa — w `lab.env.example` wzór jest jeden na zmienną,
    a powtórzenia w komentarzach (np. alternatywne warianty) nie zmieniają kontraktu.
    """
    found: dict[str, Entry] = {}
    for match in _ENV_LINE.finditer(text):
        entry = Entry(_strip_comment(match["value"]), bool(match["comment"]))
        known = found.get(match["name"])
        # Wpis aktywny wygrywa z zakomentowanym: komentarz bywa prozą opisującą wyjątek
        # ("# SIEM_TLS=0 wyłącznie na jawną decyzję…"), a wartością dokumentacji jest ten,
        # który realnie ląduje na VM.
        if known is None or (known.commented and not entry.commented):
            found[match["name"]] = entry
    return found


def firstboot_vars(text: str) -> dict[str, str | None]:
    """Zmienne czytane przez `wlb-firstboot`: nazwa -> domyślna wartość (None = wymagana)."""
    found: dict[str, str | None] = {}
    for match in _OPTIONAL.finditer(text):
        found[match["name"]] = match["default"].strip()
    for match in _REQUIRED.finditer(text):
        found[match["name"]] = None  # wymagana wygrywa z ewentualnym `${X:-}` (karygodne, ale nie ciche)
    return {name: default for name, default in found.items() if not name.startswith(_EXEMPT_PREFIX)}


def userdata_labenv(root: Path) -> dict[str, Entry]:
    """Wartości, które przykład cloud-init realnie wpisuje do `/etc/wlb/lab.env`.

    Zbierane z dwóch miejsc, bo przykłady są rozdzielone świadomie: `lab-user-data.example.yaml`
    pokazuje wdrożenie podstawowe (mounty, SIEM, TLS huba), a `cloud-init/examples/*.yaml` —
    warianty opcjonalne (OIDC). Zmienna wdrożeniowa musi mieć DZIAŁAJĄCY przykład w którymś z nich.
    """
    import yaml  # lokalnie: moduł jest wołany także tam, gdzie yaml nie jest potrzebny

    files = [root / USERDATA_EXAMPLE]
    examples = root / "cloud-init/examples"
    if examples.is_dir():
        files += sorted(examples.glob("*.yaml"))
    found: dict[str, str] = {}
    for path in files:
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in data.get("write_files") or []:
            if entry.get("path") == LAB_ENV_PATH:
                found.update(parse_env(str(entry.get("content") or "")))
    return {name: entry for name, entry in found.items() if not entry.commented}


def _simple(default: str | None) -> bool:
    """Czy domyślna wartość nadaje się do porównania (literał, nie wyrażenie powłoki)."""
    return bool(default) and not set("$()\"'`") & set(default)


def check(root: Path) -> list[str]:
    """Rozbieżności między kodem obrazu a dokumentacją parametrów wdrożenia."""
    firstboot = firstboot_vars((root / FIRSTBOOT).read_text(encoding="utf-8"))
    documented = parse_env((root / ENV_EXAMPLE).read_text(encoding="utf-8"))
    userdata = userdata_labenv(root)
    errors: list[str] = []

    for name, default in sorted(firstboot.items()):
        if name not in documented:
            how = "wymagana" if default is None else f"domyślnie '{default}'"
            errors.append(
                f"{name}: czytana przez wlb-firstboot ({how}), brak we {ENV_EXAMPLE} — "
                "administrator Laboratorium nie ma jak jej ustawić"
            )
            continue
        # Wzór zakomentowany w przykładzie dokumentuje wartość domyślną, więc musi się zgadzać
        # z kodem. Wpis aktywny to wartość przekazywana na VM — porównywanie jej z domyślną
        # zgłaszałoby fałszywy alarm przy każdym świadomym odejściu od wartości domyślnej.
        entry = documented.get(name)
        if (
            _simple(default)
            and entry is not None
            and entry.commented
            and not _PLACEHOLDER.search(entry.value)
            and entry.value != default
        ):
            errors.append(
                f"{name}: inna wartość domyślna w kodzie i w dokumentacji "
                f"(wlb-firstboot: '{default}', {ENV_EXAMPLE}: '{entry.value}')"
            )

    for name in sorted(documented):
        if name not in firstboot and not name.startswith(_EXEMPT_PREFIX):
            errors.append(
                f"{name}: opisana we {ENV_EXAMPLE}, ale wlb-firstboot nigdy jej nie czyta — "
                "dokumentacja obiecuje parametr wdrożenia, którego nie ma"
            )

    for name in sorted(userdata):
        if name not in documented and not name.startswith(_EXEMPT_PREFIX):
            errors.append(
                f"{name}: użyta w {USERDATA_EXAMPLE}, nieznana we {ENV_EXAMPLE} — "
                "przykład wdrożenia musi korzystać tylko z udokumentowanych parametrów"
            )

    # Zmienna, którą obraz realnie czyta, nie może być wzorem zakomentowanym w przykładzie: kto
    # kopiuje przykład, dostaje wartość domyślną, mimo że dokumentacja opisuje parametr (#18, #30).
    for name in sorted(documented):
        entry = documented[name]
        if entry.commented or name.startswith(_EXEMPT_PREFIX):
            continue
        if name in firstboot and name not in userdata:
            errors.append(
                f"{name}: przekazywana we {ENV_EXAMPLE}, ale brak w przykładzie {LAB_ENV_PATH} "
                f"({USERDATA_EXAMPLE}) — administrator kopiujący przykład nie ustawi tej zmiennej"
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kontrakt zmiennych wdrożeniowych (lab.env).")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    errors = check(args.root)
    if errors:
        print("Rozbieżności w kontrakcie zmiennych wdrożeniowych (/etc/wlb/lab.env):")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Zmienne wdrożeniowe: lab.env.example, lab-user-data.example.yaml i wlb-firstboot zgodne.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
