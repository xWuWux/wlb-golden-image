#!/usr/bin/env python3
"""Sprawdzenie licencji oprogramowania w obrazie WLB względem ci/license-policy.yml.

Źródła metadanych (bez instalowania pakietów):
  R       — PACKAGES ze snapshotu Posit Package Managera (z zależnościami rekurencyjnie),
            DESCRIPTION z GitHuba dla pakietów spoza CRAN
  conda   — api.anaconda.org (conda-forge)
  PyPI    — pypi.org JSON API

Jeśli istnieją pliki lock (envs/python/environment.lock.yml, envs/r/renv.lock z pakietami),
sprawdzane są dokładnie zamrożone pakiety; w przeciwnym razie pakiety z plików intencji
(environment.yml, hades-packages.txt) i ich zależności CRAN.

    python3 ci/license_check.py [--repo-root .]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

# Pakiety wchodzące w skład R (licencja R: GPL-2 | GPL-3) — nie ma ich w PACKAGES
R_BASE_PACKAGES = {
    "base", "compiler", "datasets", "graphics", "grDevices", "grid", "methods", "parallel",
    "splines", "stats", "stats4", "tcltk", "tools", "utils", "R",
}  # fmt: skip

# Kolejność ma znaczenie: bardziej szczegółowe wzorce najpierw (AGPL/LGPL przed GPL).
LICENSE_PATTERNS = [
    (r"^(agpl|gnu affero|affero)", "AGPL-3.0"),
    (r"^(lgpl|gnu lesser|gnu library)", "LGPL"),
    (r"^(gpl|gnu general public)", "GPL"),
    (r"^apache", "Apache-2.0"),
    (r"^(bsd[ _-]?2|bsd 2-clause|simplified bsd|freebsd)", "BSD-2-Clause"),
    (r"^(bsd[ _-]?3|bsd 3-clause|new bsd|modified bsd|revised bsd|bsd$|bsd license)", "BSD-3-Clause"),
    (r"^(mit|expat)", "MIT"),
    (r"^(mpl|mozilla public)", "MPL-2.0"),
    (r"^isc", "ISC"),
    (r"^(psf|python software foundation|python-2\.0|python license)", "PSF-2.0"),
    (r"^artistic", "Artistic-2.0"),
    (r"^(zlib|libpng)", "Zlib"),
    (r"^(cc0|public domain|unlicense|licenseref-public-domain)", "CC0-1.0"),
    (r"^cc[ -]by[ -]nc", "CC-BY-NC"),
    (r"^cc[ -]by", "CC-BY"),
    (r"^(bsl|boost)", "BSL-1.0"),
    (r"^sspl", "SSPL"),
    (r"^(busl|business source)", "BUSL"),
    (r"^(epl|eclipse public)", "EPL-2.0"),
    (r"^cecill", "CeCILL"),
    (r"^(ofl|sil open font)", "OFL-1.1"),
    (r"^hpnd", "HPND"),
    (r"^(unicode|ucd)", "Unicode"),
    (r"^curl", "curl"),
    (r"^openssl", "OpenSSL"),
]


@dataclass
class Package:
    ecosystem: str  # cran | conda | pypi
    name: str
    version: str
    license: str | None = None
    verdict: str = "unknown"  # allowed | review | denied | unknown | exception
    note: str = ""


# --- ocena wyrażeń licencyjnych --------------------------------------------------


def canonical(term: str) -> str | None:
    """Mapuje pojedynczy identyfikator licencji (SPDX, R, tekst PyPI) na rodzinę z polityki."""
    t = re.sub(r"\s+", " ", term.strip().strip("()").strip()).lower()
    t = re.sub(r"\s+with\s+.*$", "", t)  # SPDX "WITH wyjątek" — ocena licencji bazowej
    t = t.removeprefix("license :: osi approved :: ").removeprefix("the ")
    if not t or t in {"file license", "file licence", "unknown", "none", "other"}:
        return None
    for pattern, family in LICENSE_PATTERNS:
        if re.match(pattern, t):
            return family
    return None


def split_expression(expr: str) -> list[list[str]]:
    """Wyrażenie -> alternatywy (OR / |), każda jako lista składników (AND).

    R: "MIT + file LICENSE" = MIT z dodatkowymi warunkami w pliku — ocena po MIT.
    """
    expr = expr.replace("\n", " ")
    alternatives = re.split(r"\s+OR\s+|\s*\|\s*", expr, flags=re.IGNORECASE)
    result = []
    for alt in alternatives:
        alt = re.sub(r"\s*\+\s*file\s+licen[cs]e", "", alt, flags=re.IGNORECASE).strip()
        terms = [t for t in re.split(r"\s+AND\s+", alt.strip("() "), flags=re.IGNORECASE) if t.strip()]
        if terms:
            result.append(terms)
    return result


def evaluate(expr: str | None, policy: dict) -> tuple[str, str]:
    """Zwraca (werdykt, rodzina/uzasadnienie) dla wyrażenia licencyjnego."""
    if not expr or not expr.strip():
        return "unknown", "brak informacji o licencji"
    allowed, review, denied = (set(policy.get(k, [])) for k in ("allowed", "review", "denied"))
    verdicts = []
    for terms in split_expression(expr):
        families = [canonical(t) for t in terms]
        if any(f is None for f in families):
            verdicts.append(("unknown", "nierozpoznany składnik"))
        elif any(f in denied for f in families):
            verdicts.append(("denied", ", ".join(f for f in families if f in denied)))
        elif any(f in review for f in families):
            verdicts.append(("review", ", ".join(f for f in families if f in review)))
        elif all(f in allowed for f in families):
            verdicts.append(("allowed", " AND ".join(families)))
        else:
            verdicts.append(("unknown", "poza polityką: " + ", ".join(f for f in families if f not in allowed)))
    if not verdicts:
        return "unknown", "puste wyrażenie"
    # alternatywy: wystarczy jedna dozwolona; najgorszy wynik tylko gdy żadna nie przechodzi
    for rank in ("allowed", "review", "unknown", "denied"):
        for verdict, why in verdicts:
            if verdict == rank:
                return verdict, why
    raise AssertionError("unreachable")  # pragma: no cover


def apply_policy(packages: list[Package], policy: dict) -> None:
    exceptions = {(e["ecosystem"], e["package"].lower()): e for e in policy.get("exceptions", [])}
    for pkg in packages:
        verdict, why = evaluate(pkg.license, policy)
        exc = exceptions.get((pkg.ecosystem, pkg.name.lower()))
        if verdict != "allowed" and exc:
            pkg.verdict, pkg.note = "exception", exc.get("note", "")
        else:
            pkg.verdict, pkg.note = verdict, why


# --- zbieranie pakietów ---------------------------------------------------------------


def fetch(url: str) -> bytes:  # pragma: no cover - sieć
    if not url.startswith("https://"):
        raise ValueError(f"dozwolone tylko https: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "wlb-license-check"})  # noqa: S310 - sprawdzone wyżej
    for attempt in range(3):
        try:
            # schemat sprawdzony wyżej (tylko https), adresy budowane w kodzie z nazw pakietów
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310  # nosec B310
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
        except urllib.error.URLError:
            if attempt == 2:
                raise
    raise RuntimeError(url)


def parse_dcf(text: str) -> list[dict[str, str]]:
    """Parser formatu DCF (PACKAGES, DESCRIPTION)."""
    records, current, key = [], {}, None
    for line in text.splitlines():
        if not line.strip():
            if current:
                records.append(current)
            current, key = {}, None
        elif line[0].isspace() and key:
            current[key] += " " + line.strip()
        else:
            key, _, value = line.partition(":")
            current[key] = value.strip()
    if current:
        records.append(current)
    return records


def dependency_names(field: str) -> list[str]:
    return [re.split(r"[\s(]", d.strip())[0] for d in field.split(",") if d.strip()]


def r_packages(repo_root: Path, cran_repo: str, fetcher=fetch) -> list[Package]:
    lock = json.loads((repo_root / "envs/r/renv.lock").read_text())
    index = {r["Package"]: r for r in parse_dcf(fetcher(cran_repo.rstrip("/") + "/src/contrib/PACKAGES").decode())}
    wanted: dict[str, dict] = {}
    if lock.get("Packages"):
        for name, entry in lock["Packages"].items():
            wanted[name] = entry
    else:
        fallbacks = {}
        for line in (repo_root / "envs/r/hades-packages.txt").read_text().splitlines():
            parts = line.split("#", 1)[0].split()
            if parts:
                wanted[parts[0]] = {}
                if len(parts) > 1:
                    fallbacks[parts[0]] = parts[1]
        queue = list(wanted)
        while queue:  # zależności rekurencyjnie (Depends, Imports, LinkingTo)
            record = index.get(queue.pop())
            if not record:
                continue
            for field in ("Depends", "Imports", "LinkingTo"):
                for dep in dependency_names(record.get(field, "")):
                    if dep not in R_BASE_PACKAGES and dep not in wanted:
                        wanted[dep] = {}
                        queue.append(dep)
        for name, ref in fallbacks.items():
            if name not in index:
                owner, _, repo = ref.partition("@")[0].partition("/")
                wanted[name] = {"RemoteType": "github", "RemoteUsername": owner, "RemoteRepo": repo}

    packages = []
    for name, entry in sorted(wanted.items()):
        if name in R_BASE_PACKAGES:
            continue
        if entry.get("RemoteType") == "github":
            ref = entry.get("RemoteSha", "HEAD")
            url = f"https://raw.githubusercontent.com/{entry['RemoteUsername']}/{entry['RemoteRepo']}/{ref}/DESCRIPTION"
            desc = parse_dcf(fetcher(url).decode())[0]
            packages.append(Package("cran", name, desc.get("Version", "?"), desc.get("License")))
        else:
            record = index.get(name, {})
            version = entry.get("Version") or record.get("Version", "?")
            packages.append(Package("cran", name, version, record.get("License")))
    return packages


def python_packages(repo_root: Path, fetcher=fetch) -> list[Package]:
    lock = repo_root / "envs/python/environment.lock.yml"
    env = yaml.safe_load((lock if lock.exists() else repo_root / "envs/python/environment.yml").read_text())
    conda: list[str] = []
    pip: list[tuple[str, str]] = []
    for dep in env.get("dependencies", []):
        if isinstance(dep, dict):
            for spec in dep.get("pip", []):
                name, _, version = spec.partition("==")
                pip.append((re.split(r"[<>=!~ \[]", name, maxsplit=1)[0], version.strip()))
        else:
            conda.append(dep)

    def conda_pkg(spec: str) -> Package:
        name, _, rest = spec.partition("=")
        version = rest.split("=")[0] or "?"
        if name == "pip":
            return Package("conda", name, version, "MIT")
        meta = json.loads(fetcher(f"https://api.anaconda.org/package/conda-forge/{name}"))
        return Package("conda", name, version, meta.get("license"))

    def pypi_pkg(spec: tuple[str, str]) -> Package:
        name, version = spec
        url = f"https://pypi.org/pypi/{name}/{version}/json" if version else f"https://pypi.org/pypi/{name}/json"
        info = json.loads(fetcher(url))["info"]
        lic = info.get("license_expression")
        if not lic:
            prefix = "License :: OSI Approved ::"
            osi = [c.removeprefix(prefix).strip() for c in info.get("classifiers", []) if c.startswith(prefix)]
            lic = " OR ".join(osi) if osi else ((info.get("license") or "").strip().splitlines() or [None])[0]
        return Package("pypi", name, version or info.get("version", "?"), lic)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(conda_pkg, conda)) + list(pool.map(pypi_pkg, pip))
    return results


# --- raport ------------------------------------------------------------------------------


def report(packages: list[Package], locked: bool) -> tuple[str, int]:
    bad = [p for p in packages if p.verdict in ("denied", "review", "unknown")]
    exc = [p for p in packages if p.verdict == "exception"]
    lines = [
        "## Licencje",
        "",
        f"Sprawdzono {len(packages)} pakietów ("
        + ("pliki lock" if locked else "pliki intencji + zależności CRAN — brak locków")
        + ").",
        f"Naruszenia: **{len(bad)}**, wyjątki zatwierdzone w polityce: {len(exc)}.",
        "",
    ]
    if bad or exc:
        lines += ["| Ekosystem | Pakiet | Wersja | Licencja | Werdykt | Uwagi |", "|---|---|---|---|---|---|"]
        for p in sorted(bad + exc, key=lambda p: (p.verdict != "denied", p.verdict, p.ecosystem, p.name)):
            lic = (p.license or "—").replace("|", "\\|")[:80]
            lines.append(f"| {p.ecosystem} | {p.name} | {p.version} | {lic} | {p.verdict} | {p.note} |")
    return "\n".join(lines) + "\n", len(bad)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    root = args.repo_root

    policy = yaml.safe_load((root / "ci/license-policy.yml").read_text())
    group_vars = yaml.safe_load((root / "ansible/group_vars/all.yml").read_text())
    cran_repo = f"https://packagemanager.posit.co/cran/{group_vars['r_cran_snapshot_date']}"
    locked = (root / "envs/python/environment.lock.yml").exists()

    packages = r_packages(root, cran_repo) + python_packages(root)
    apply_policy(packages, policy)
    text, violations = report(packages, locked)
    print(text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):  # pragma: no cover
        with open(summary, "a") as f:
            f.write(text)
    return 1 if violations else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
