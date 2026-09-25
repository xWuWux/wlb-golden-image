#!/usr/bin/env python3
"""Eksport zamrożonego środowiska Pythona (environment.lock.yml) do requirements.txt dla osv-scannera.

Pakiety conda-forge sprawdzamy pod nazwami PyPI — dla bibliotek Pythona to ten sam projekt.
Biblioteki natywne (openssl, libgcc…) nie mają swojego odpowiednika w PyPI, więc osv ich nie ocenia;
ich podatności pokrywa skan pakietów systemowych obrazu (stage 5).

    python3 ci/sca_requirements.py envs/python/environment.lock.yml build/sca/requirements.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def requirements(lock: dict) -> list[str]:
    reqs = set()
    for dep in lock.get("dependencies", []):
        if isinstance(dep, dict):
            reqs.update(p.strip() for p in dep.get("pip", []) if "==" in p)
        else:
            name, _, rest = dep.partition("=")
            version = rest.split("=")[0]
            if version and re.fullmatch(r"[A-Za-z0-9._-]+", name):
                reqs.add(f"{name}=={version}")
    return sorted(reqs, key=str.lower)


def main(argv: list[str]) -> int:
    lock, out = Path(argv[0]), Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    reqs = requirements(yaml.safe_load(lock.read_text()))
    out.write_text("".join(r + "\n" for r in reqs))
    print(f"{len(reqs)} pakietów -> {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
