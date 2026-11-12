#!/usr/bin/env python3
"""Deterministyczna weryfikacja istnienia ZADEKLAROWANYCH pakietów w oficjalnych rejestrach.

Łapie zmyślone (wyhalucynowane przez LLM) nazwy pakietów w manifestach obrazu WLB, ZANIM
trafią do budowy (etap 5) albo code review. Część kodu/manifestów powstaje z pomocą LLM, a te
potrafią podać nieistniejącą nazwę pakietu — deterministyczne odpytanie rejestru to wychwytuje.

Zasady:
- BRAK zapytań do LLM. Tylko HTTPS do oficjalnych rejestrów. Powtarzalne i bezstanowe (HEAD/GET,
  bez instalacji). fail-closed: nierozwiązany błąd rejestru po ponowieniach = błąd (exit 1).
- Zakres WLB: Python (conda-forge + PyPI z envs/python/environment.yml), R (CRAN wg snapshotu
  Posit + fallback GitHub z envs/r/hades-packages.txt). Ansible Galaxy NIE jest w WLB używany
  (brak requirements.yml, role lokalne) -> poza zakresem. Pakiety apt/OS -> poza zakresem
  (weryfikowane przy budowaniu obrazu). Sprawdzamy MANIFESTY INTENCJI (pisane ręcznie/LLM), nie
  wygenerowane locki (environment.lock.yml/renv.lock) — tam halucynacja i tak wywaliłaby build.

CRAN: istnienie sprawdzamy wobec snapshotu Posit Package Managera (r_cran_snapshot_date), zgodnie
z tym, co realnie instaluje obraz. Jeśli endpoint snapshotu okaże się zawodny, łatwo podmienić
CRAN_WEB na crandb.r-pkg.org (istnienie bez wersji) — logika i testy są od tego niezależne.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

_UA = {"User-Agent": "wlb-package-existence-check"}
_TRANSIENT = {0, 429, 500, 502, 503, 504}  # 0 = błąd transportu/timeout
_PRESENT = {200, 301, 302}
_ABSENT = {404, 410}

# URL = Callable przyjmujący adres i zwracający kod HTTP; wstrzykiwany w testach (offline).
Fetch = Callable[[str], int]

PYPI = "https://pypi.org/pypi/{name}/json"
CONDA = "https://api.anaconda.org/package/conda-forge/{name}"
CRAN_WEB = "https://packagemanager.posit.co/cran/{snapshot}/web/packages/{name}/"
GITHUB = "https://api.github.com/repos/{repo}"

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*")


@dataclass(frozen=True)
class Pkg:
    ecosystem: str  # "PyPI" | "conda-forge" | "CRAN"
    name: str
    source: str  # plik manifestu
    url: str  # endpoint istnienia w rejestrze głównym
    fallback_url: str | None = None  # np. repo GitHub dla pakietów OHDSI/HADES


@dataclass(frozen=True)
class Finding:
    pkg: Pkg
    reason: str


def default_fetch(url: str, timeout: float = 10.0) -> int:
    """Zwraca kod HTTP (0 = błąd transportu/timeout). Nie czyta treści — tylko istnienie."""
    req = urllib.request.Request(url, method="HEAD", headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return resp.status
    except urllib.error.HTTPError as err:
        if err.code == 405:  # rejestr nie wspiera HEAD -> spróbuj GET
            try:
                get = urllib.request.Request(url, method="GET", headers=_UA)
                with urllib.request.urlopen(get, timeout=timeout) as resp:  # nosec B310
                    return resp.status
            except urllib.error.HTTPError as gerr:
                return gerr.code
            except (urllib.error.URLError, TimeoutError, OSError):
                return 0
        return err.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def exists(url: str, fetch: Fetch, retries: int = 3, backoff: float = 0.5) -> bool | None:
    """True = istnieje; False = 404/410 (brak); None = nierozwiązane po ponowieniach (fail-closed)."""
    for attempt in range(retries):
        code = fetch(url)
        if code in _PRESENT:
            return True
        if code in _ABSENT:
            return False
        if code not in _TRANSIENT:  # nieoczekiwany kod (np. 401/403) — nie zgadujemy, fail-closed
            return None
        if attempt < retries - 1:
            time.sleep(backoff * (2**attempt))
    return None


def _bare(spec: str) -> str:
    """Nazwa pakietu bez ograniczeń wersji/markerów ('urllib3>=2.7.0' -> 'urllib3')."""
    match = _NAME.match(spec.strip())
    return match.group(0) if match else ""


def parse_python(root: Path) -> list[Pkg]:
    manifest = root / "envs/python/environment.yml"
    if not manifest.is_file():
        return []
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    src = "envs/python/environment.yml"
    out: list[Pkg] = []
    seen: set[tuple[str, str]] = set()
    for dep in data.get("dependencies", []) or []:
        if isinstance(dep, str):
            name = _bare(dep)
            if not name or name == "pip":  # 'pip' to meta-pakiet conda, nie sprawdzamy
                continue
            if ("conda", name.lower()) in seen:
                continue
            seen.add(("conda", name.lower()))
            out.append(Pkg("conda-forge", name, src, CONDA.format(name=name)))
        elif isinstance(dep, dict) and "pip" in dep:
            for item in dep.get("pip") or []:
                name = _bare(item)
                if not name or ("pypi", name.lower()) in seen:
                    continue
                seen.add(("pypi", name.lower()))
                out.append(Pkg("PyPI", name, src, PYPI.format(name=name)))
    return out


def parse_r(root: Path, snapshot: str) -> list[Pkg]:
    manifest = root / "envs/r/hades-packages.txt"
    if not manifest.is_file():
        return []
    src = "envs/r/hades-packages.txt"
    out: list[Pkg] = []
    seen: set[str] = set()
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        name = tokens[0]
        if name in seen:
            continue
        seen.add(name)
        fallback = None
        for tok in tokens[1:]:  # ref zapasowy GitHub: owner/repo@ref
            if "/" in tok:
                repo = tok.split("@", 1)[0]
                fallback = GITHUB.format(repo=repo)
                break
        url = CRAN_WEB.format(snapshot=snapshot, name=name)
        out.append(Pkg("CRAN", name, src, url, fallback))
    return out


def verify(pkgs: list[Pkg], fetch: Fetch) -> list[Finding]:
    findings: list[Finding] = []
    for pkg in pkgs:
        result = exists(pkg.url, fetch)
        if result is True:
            continue
        if result is None:
            findings.append(Finding(pkg, "rejestr nieosiągalny po ponowieniach (fail-closed)"))
            continue
        # Brak w rejestrze głównym — zanim uznamy za halucynację, sprawdź fallback (GitHub dla HADES).
        if pkg.fallback_url is not None:
            fb = exists(pkg.fallback_url, fetch)
            if fb is True:
                continue
            if fb is None:
                findings.append(Finding(pkg, "fallback (GitHub) nieosiągalny (fail-closed)"))
                continue
        findings.append(Finding(pkg, "nie istnieje w rejestrze — możliwa halucynacja LLM"))
    return findings


def read_snapshot(root: Path) -> str:
    group_vars = root / "ansible/group_vars/all.yml"
    if group_vars.is_file():
        match = re.search(
            r'^r_cran_snapshot_date:\s*"?(\d{4}-\d{2}-\d{2})"?',
            group_vars.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
    return "latest"


def collect(root: Path, ecosystems: set[str], snapshot: str) -> list[Pkg]:
    pkgs: list[Pkg] = []
    if "python" in ecosystems:
        pkgs += parse_python(root)
    if "r" in ecosystems:
        pkgs += parse_r(root, snapshot)
    return pkgs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anty-halucynacja: istnienie pakietów w rejestrach.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--ecosystems", default="python,r", help="rozdzielone przecinkami: python,r")
    parser.add_argument("--snapshot-date", default=None, help="data snapshotu CRAN (domyślnie z group_vars)")
    args = parser.parse_args(argv)

    ecosystems = {e.strip() for e in args.ecosystems.split(",") if e.strip()}
    snapshot = args.snapshot_date or read_snapshot(args.root)
    pkgs = collect(args.root, ecosystems, snapshot)
    if not pkgs:
        print("Brak zadeklarowanych pakietów do sprawdzenia (sprawdź --root/--ecosystems).", file=sys.stderr)
        return 1
    findings = verify(pkgs, default_fetch)

    eco_str = ", ".join(sorted(ecosystems))
    print(f"Sprawdzono {len(pkgs)} zadeklarowanych pakietów ({eco_str}); snapshot CRAN={snapshot}")
    for finding in findings:
        print(
            f"  BŁĄD [{finding.pkg.ecosystem}] {finding.pkg.name} ({finding.pkg.source}): {finding.reason}",
            file=sys.stderr,
        )
    if findings:
        print(f"Nieistniejące/nierozwiązane: {len(findings)} — blokuję (fail-closed).", file=sys.stderr)
        return 1
    print("Wszystkie zadeklarowane pakiety istnieją w rejestrach.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
