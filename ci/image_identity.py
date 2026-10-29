#!/usr/bin/env python3
"""Walidacja tozsamosci systemu skanowanego obrazu (#129).

Uwaga jezykowa: komentarze w tym pliku sa celowo bez diekrytykow -- kompilator tekstu
generator tekstu je gubi; plik z blednymi diekrytykami bylby gorszy niz ASCII.

osv-scanner wnosi ekosystem pakietow deb z /etc/os-release PROCESU skanujacego, nie z
obrazu, ktorego dotyczy dpkg-status. Bez pary tozsamosci raport SCA/SBOM moze opisywac
pakiety wydania, ktorego nikt nie budowal -- i robic to po cichu.

Stad dwie twarde zasady:
  1. tozsamosc obrazu pochodzi z os-release zebranego z TEJ SAMEJ VM co dpkg-status;
  2. srodowisko skanera musi dac te sama pare ID/VERSION_ID co obraz -- nie "ten sam
     VERSION_ID przy innej dystrybucji", tylko rownosc obu pol.

Nie ma tutaj przelacznika omijajacego walidacje: plik docelowy jest artefaktem (katalog
jako argument), a strona skanera to zawsze /etc/os-release biezacego procesu. Testy
podmieniaja sciezke przez atrybut modulu, nie przez produkcyjne zmienne srodowiska.
"""

import re
import sys
from dataclasses import dataclass

# Jedyne wspierane wydanie obrazu; poszerzenie = swiadoma decyzja + testy regresji.
SUPPORTED = frozenset({("ubuntu", "24.04")})
HOST_OS_RELEASE = "/etc/os-release"


# Uwaga: BEZ slots=True i bez "from __future__ import annotations" -- dataclasses
# z tym duetem wymaga modulu obecnego w sys.modules, a ladowanie testowe (SourceFileLoader)
# rejestruje modul poza sys.modules. frozen wystarczy do immutabilnosci kontraktowej.


class IdentityError(ValueError):
    """Tozsamosc niekompletna, uszkodzona lub niekompatybilna -- skan niedostateczny."""


@dataclass(frozen=True)
class OsIdentity:
    id: str
    version_id: str

    @property
    def is_supported(self) -> bool:
        return (self.id, self.version_id) in SUPPORTED

    def label(self) -> str:
        return f"{self.id} {self.version_id}"


def _unquote(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_os_identity(path: str) -> OsIdentity:
    """Parser podzbioru skladni os-release (KEY=VALUE, opcjonalne cudzyslowy) BEZ
    wykonywania powloki: wartoscia pozostaje literal, nawet jesli wyglada jak polecenie."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise IdentityError(f"nie da sie odczytac {path}: {exc}") from exc

    values: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        key, sep, raw = text.partition("=")
        if not sep:
            raise IdentityError(f"{path}:{number}: wiersz bez '=': {text!r}")
        key = key.strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            raise IdentityError(f"{path}:{number}: nieprawidlowa nazwa klucza: {key!r}")
        if key in ("ID", "VERSION_ID") and key in values:
            raise IdentityError(f"{path}:{number}: duplikat wymaganego klucza {key}")
        values[key] = _unquote(raw)

    missing = [key for key in ("ID", "VERSION_ID") if not values.get(key)]
    if missing:
        raise IdentityError(f"{path}: brak wartosci dla {', '.join(missing)}")
    return OsIdentity(id=values["ID"].casefold(), version_id=values["VERSION_ID"].casefold())


def validate_scan_identity(target: OsIdentity, scanner: OsIdentity) -> None:
    if not target.is_supported:
        supported = ", ".join(sorted(" ".join(pair) for pair in SUPPORTED))
        raise IdentityError(
            f"obraz {target.label()} poza wspieranym zestawem ({supported}); nowe wydanie "
            "wymaga swiadomej decyzji i testow, nie cichego skanowania"
        )
    if target != scanner:
        raise IdentityError(
            f"srodowisko skanera ({scanner.label()}) rozni sie od obrazu ({target.label()}); "
            "OSV opisalby pakiety w zlym ekosystemie (#129)"
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uzycie: image_identity.py <katalog-artefaktow>", file=sys.stderr)
        return 2
    try:
        target = read_os_identity(f"{argv[1].rstrip('/')}/os-release")
        scanner = read_os_identity(HOST_OS_RELEASE)
        validate_scan_identity(target, scanner)
    except IdentityError as exc:
        print(f"image-identity: {exc}", file=sys.stderr)
        return 2
    print(f"image-identity: OK ({target.label()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
