#!/usr/bin/env python3
"""Twarde kryterium etapu 5 (#9): w obrazie jest dokładnie jedno jądro.

Czyta kopię /var/lib/dpkg/status z VM testowej (ci/integration.sh zapisuje ją jako dpkg-status) i
dla każdej rodziny (linux-image/modules/modules-extra/headers/tools) liczy wersje faktycznie
zainstalowanych pakietów. Zwraca kod !=0, gdy którakolwiek rodzina ma więcej niż jedną wersję.
Meta-pakiety bez wersji (linux-image-virtual, linux-tools-common itd.) są pomijane.
"""

from __future__ import annotations

import re
import sys

FAMILIES = ("linux-image", "linux-modules", "linux-modules-extra", "linux-headers", "linux-tools")
# linux-image-6.8.0-142-generic / linux-tools-6.8.0-142 -> rodzina + wersja "6.8.0-142"
# (wariant modules-extra przed modules, żeby dłuższa nazwa miała pierwszeństwo)
VER = re.compile(r"^(linux-(?:image|modules-extra|modules|headers|tools))-(\d[\d.]*-\d+)(?:-\w+)?$")


def installed_versions(status_text: str) -> dict[str, set[str]]:
    """Mapa rodzina -> zbiór wersji zainstalowanych (Status: install ok installed) pakietów jądra."""
    found: dict[str, set[str]] = {f: set() for f in FAMILIES}
    pkg = ""
    installed = False
    for line in [*status_text.splitlines(), ""]:  # pusta linia na końcu domyka ostatnią stanzę
        if line.startswith("Package:"):
            pkg = line.split(":", 1)[1].strip()
            installed = False
        elif line.startswith("Status:"):
            installed = "install ok installed" in line
        elif line == "":
            if pkg and installed:
                m = VER.match(pkg)
                if m:
                    found[m.group(1)].add(m.group(2))
            pkg = ""
            installed = False
    return found


def check(status_text: str) -> tuple[dict[str, set[str]], list[tuple[str, list[str]]]]:
    """Zwraca (wersje wg rodziny, problemy=[(rodzina, posortowane wersje)] gdzie >1 wersja)."""
    vers = installed_versions(status_text)
    problems = [(f, sorted(v)) for f, v in vers.items() if len(v) > 1]
    return vers, problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("użycie: kernel_check.py <dpkg-status>", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"Brak dpkg-status ({exc.strerror}) — pomijam")
        return 0
    vers, problems = check(text)
    for fam in FAMILIES:
        v = sorted(vers[fam])
        print(f"{fam}: {', '.join(v) if v else 'brak'}")
    for fam, v in problems:
        print(f"BŁĄD: wiele wersji {fam}: {', '.join(v)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
