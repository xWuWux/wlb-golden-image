#!/usr/bin/env python3
"""Wykrywa nierozwiązane znaczniki konfliktu scalenia w plikach śledzonych przez gita.

Znaczniki pisze sam git (`<<<<<<<`/`=======`/`>>>>>>>`, a przy merge.conflictStyle=diff3
także sekcję przodka `|||||||`). Dotąd łapał je wyłącznie shellcheck — czyli tylko tam,
gdzie znał składnię (pliki .sh). Znacznik w .md, .txt albo YAML-u prześlizgiwał się
przez cały pipeline (pozostałości diff3 usunięte w f0b4b5a). Logika w module jak w
lock_drift.py — testowalna bez CI (#123).

Domyślnie skanuje drzewo robocze (bramka CI, etap 1 w ci/lint.sh).
--staged skanuje indeks (`git show :sciezka`) — do .githooks/pre-commit, żeby sprawdzić
dokładnie to, co zostanie zacommitowane, nie to, co leży na dysku.

Wypisuje "sciezka:linia:wiersz" i kończy się kodem 1 przy co najmniej jednym trafieniu.

Znany kompromis: linia >=7 znaków `=` to też podkreślenie nagłówka Setext/RST. Git
używa dokładnie 7 `=` (szerzej tylko przy merge.conflictSize), repozytorium trzyma
nagłówki bez podkreśleń — fałszywy alarm jest głośny i trywialny do poprawienia,
ciche przepuszczenie konfliktu — nie.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# 7 lub wiecej < | > (opcjonalnie etykieta galęzi po spacji/tabulatorze) albo = bez reszty.
_MARKER = re.compile(r"^([<|>])\1{6,}(?:[ \t].*)?$|^={7,}$")


def marker_lines(text: str) -> list[tuple[int, str]]:
    """Wiersze znaczników konfliktu w tekscie: (numer_wiersza, tresc)."""
    return [(n, line) for n, line in enumerate(text.splitlines(), 1) if _MARKER.match(line)]


def _is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]


def _nul(cmd: list[str]) -> list[str]:
    # Wszystkie wywolania budowane z stalych argumentow, bez wejscia uzytkownika (jak mapa-testy.py).
    done = subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - stale arg, patrz wyzej
    return [f for f in done.stdout.decode(errors="replace").split("\0") if f]


def _show(git: list[str], file: str) -> bytes | None:
    done = subprocess.run([*git, "show", f":{file}"], capture_output=True)  # noqa: S603 - stale arg
    return None if done.returncode else done.stdout


def scan(root: Path, staged: bool = False) -> list[str]:
    """Trafienia "plik:linia:wiersz" w repo pod `root`.

    staged=True czyta zawartość z indeksu gita, nie z dysku.
    """
    git = ["git", "-C", str(root)]
    if staged:
        files = _nul([*git, "diff", "--cached", "--name-only", "-z"])

        def read(file: str) -> bytes | None:
            return _show(git, file)
    else:
        files = _nul([*git, "ls-files", "-z"])

        def read(file: str) -> bytes | None:
            return (root / file).read_bytes()

    hits: list[str] = []
    for file in files:
        data = read(file)
        if data is None or _is_binary(data):
            continue  # skasowany w indeksie (D) albo plik binarny
        for line_no, line in marker_lines(data.decode("utf-8", errors="replace")):
            hits.append(f"{file}:{line_no}:{line}")
    return hits


def main(argv: list[str]) -> int:
    # stale arg, git z PATH bez wejscia uzytkownika (jak mapa-testy.py)
    cmd = ["git", "rev-parse", "--show-toplevel"]
    done = subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    root = Path(done.stdout.decode().strip())
    hits = scan(root, staged="--staged" in argv)
    for hit in hits:
        print(hit)
    if hits:
        print(f"BŁĄD: nierozwiązane znaczniki konfliktu w {len(hits)} wierszach")
    return 1 if hits else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
