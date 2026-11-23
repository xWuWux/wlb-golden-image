"""Bramka wydania: obraz i artefakt nie mogą zawierać fixture E2E pulpitu (#277-S3).

Kontrakt czterech ścieżek, których obraz produkcyjny nie może zawierać:

  /opt/wlb/e2e/
  /etc/xdg/autostart/wlb-e2e-target.desktop
  /usr/share/applications/wlb-e2e-mouse.desktop
  /etc/tmpfiles.d/wlb-e2e.conf

Dwa tryby:
  --tree DIR   sprawdza drzewo artefaktów (np. rozpakowany rootfs) — tanie i testowalne;
  --image IMG  sprawdza zawartość qcow2 przez virt-ls z libguestfs (release CI).
               virt-ls montuje rootfs przez inspekcję systemu (bez opcji -i, której
               virt-ls nie ma — to składnia guestfish). Format qcow2 jest jawny,
               żeby nie zgadywać formatu obrazu.

Bramka jest fail-closed: brak możliwości sprawdzenia obrazu to błąd, nie „czysto”.
Kody wyjścia (stabilne, używane przez ci/release.sh):
  0 — brak artefaktów E2E,
  2 — nie można zweryfikować (brak argumentów, obrazu albo virt-ls),
  3 — znaleziono artefakt E2E; wydanie przerwane.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_E2E_FOUND = 3

CONTRACT_PATHS = (
    "/opt/wlb/e2e",
    "/etc/xdg/autostart/wlb-e2e-target.desktop",
    "/usr/share/applications/wlb-e2e-mouse.desktop",
    "/etc/tmpfiles.d/wlb-e2e.conf",
)


class GateError(RuntimeError):
    """Bramka nie może rozstrzygnąć, czy artefakt jest czysty (fail-closed)."""


def normalize_listing_path(line: str) -> str:
    """Ujednolica wpis listingu do postaci bezwzględnej (virt-ls -R zwraca ścieżki względne)."""
    text = line.strip()
    if not text:
        return ""
    return "/" + text.lstrip("/")


def find_in_listing(listing: list[str]) -> list[str]:
    """Zwraca ścieżki kontraktu obecne na liście.

    Dopasowanie jest dokładne albo po katalogu: wpis `opt/wlb/e2e/target.json`
    dowodzi istnienia `/opt/wlb/e2e`, nawet jeśli samego katalogu nie ma na liście.
    Podciągi w rodzaju `/opt/wlb/e2e2` nie pasują.
    """
    present = [normalize_listing_path(line) for line in listing if line.strip()]
    return [
        path
        for path in CONTRACT_PATHS
        if any(candidate == path or candidate.startswith(path + "/") for candidate in present)
    ]


def check_tree(root: Path) -> list[str]:
    """Sprawdza drzewo artefaktów; symlink (nawet zerwany) też jest artefaktem."""
    try:
        is_dir = root.is_dir()
    except OSError as exc:
        raise GateError(f"nie można odczytać katalogu {root}: {exc}") from exc
    if not is_dir:
        raise GateError(f"katalog artefaktów nie istnieje: {root}")

    found = []
    for contract in CONTRACT_PATHS:
        candidate = root / contract.lstrip("/")
        try:
            if os.path.lexists(candidate):
                found.append(contract)
        except OSError as exc:
            raise GateError(f"nie można sprawdzić {candidate}: {exc}") from exc
    return found


def list_image_paths(image: Path) -> list[str]:
    """Listuje rekurencyjnie rootfs obrazu qcow2 (bez montowania przez człowieka)."""
    if not image.is_file():
        raise GateError(f"obraz nie istnieje: {image}")
    try:
        done = subprocess.run(  # noqa: S603 - stała lista argumentów, brak powłoki
            # virt-ls nie ma opcji -i (to guestfish); rootfs wybiera inspekcja libguestfs.
            ["virt-ls", "--format=qcow2", "-a", str(image), "-R", "/"],  # noqa: S607 - virt-ls z PATH CI
            capture_output=True,
            check=False,
            text=True,
            timeout=600,
        )
    except FileNotFoundError as exc:
        raise GateError(
            "brak virt-ls (libguestfs-tools) — nie można sprawdzić obrazu; zainstaluj libguestfs-tools albo użyj --tree"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"virt-ls przekroczył 600 s dla {image}") from exc
    except OSError as exc:
        raise GateError(f"nie można uruchomić virt-ls dla {image}: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        raise GateError(f"virt-ls nie odczytał {image}: {detail or 'brak komunikatu'}")
    return done.stdout.splitlines()


def check_image(image: Path) -> list[str]:
    return find_in_listing(list_image_paths(image))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bramka E2E wydania obrazu (#277-S3)")
    parser.add_argument("--tree", action="append", default=[], metavar="DIR", help="drzewo artefaktów")
    parser.add_argument("--image", action="append", default=[], metavar="IMG", help="obraz qcow2")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    trees = [Path(path) for path in args.tree]
    images = [Path(path) for path in args.image]
    if not trees and not images:
        print("BŁĄD: bramka E2E: podaj --tree i/lub --image (#277)", file=sys.stderr)
        return EXIT_ERROR

    try:
        found: list[str] = []
        for root in trees:
            found.extend(f"{path} (drzewo {root})" for path in check_tree(root))
        for image in images:
            found.extend(f"{path} (obraz {image})" for path in check_image(image))
    except GateError as exc:
        print(f"BŁĄD: bramka E2E: {exc} (#277)", file=sys.stderr)
        return EXIT_ERROR

    if found:
        print("BŁĄD: obraz/artefakt zawiera fixture E2E pulpitu (#277):", file=sys.stderr)
        for item in found:
            print(f"  - {item}", file=sys.stderr)
        print(
            "Wydanie przerwane — artefakty E2E nie mogą opuścić buildów testowych "
            "(profil production wymusza wlb_enable_e2e_target=false).",
            file=sys.stderr,
        )
        return EXIT_E2E_FOUND

    print(f"Bramka E2E: czysto — brak {len(CONTRACT_PATHS)} ścieżek kontraktu (#277)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
