#!/usr/bin/env python3
"""Deterministyczna weryfikacja istnienia ZADEKLAROWANYCH pakietów w oficjalnych rejestrach.

Łapie zmyślone (wyhalucynowane przez LLM) nazwy pakietów w manifestach obrazu WLB, ZANIM
trafią do budowy (etap 5) albo code review. Część kodu/manifestów powstaje z pomocą LLM, a te
potrafią podać nieistniejącą nazwę pakietu — deterministyczne odpytanie rejestru to wychwytuje.

Zasady:
- BRAK zapytań do LLM. Tylko HTTPS do oficjalnych rejestrów. Powtarzalne i bezstanowe (HEAD/GET,
  bez instalacji). fail-closed: nierozwiązany błąd rejestru po ponowieniach = błąd (exit 1).
- Zakres WLB: Python (conda-forge + PyPI z envs/python/environment.yml), R (CRAN wg snapshotu
  Posit + fallback GitHub z envs/r/hades-packages.txt), apt/OS (zadania ansible.builtin.apt/apt
  w ansible/roles/**/tasks/*.yml i ansible/*.yml). Ansible Galaxy NIE jest w WLB używany (brak
  requirements.yml, role lokalne) -> poza zakresem. Pakiety spoza archiwum (PPA/.deb, np.
  DBeaver #271) wyciszamy allowlistą ci/linux-package-allowlist.txt z uzasadnieniem — bez
  fałszywych braków. Sprawdzamy MANIFESTY INTENCJI (pisane ręcznie/LLM), nie wygenerowane locki
  (environment.lock.yml/renv.lock) — tam halucynacja i tak wywaliłaby build.

APT: oracle to oficjalny indeks `Packages.xz` Ubuntu noble (pockets noble/updates/security,
wszystkie komponenty, amd64). Sprawdzamy zbiór nazw — także wirtualnych z pola `Provides:`
(np. mail-transport-agent) — zamiast pojedynczych stron Launchpada, bo przy ~80 pakietach na
PR Launchpad zaczyna ograniczać ruch i pojedyncze zapytania timeoutują. Jednorazowe pobranie
indeksu (~25 MB, dekompresja w pamięci) jest deterministyczne, szybkie i odporne na limity.
URL w raporcie nadal wskazuje stronę Launchpada: człowiek może zweryfikować pakiet klikiem.

CRAN: istnienie sprawdzamy w crandb.r-pkg.org (indeks CRAN, ~0,2 s/pakiet). Strona
packagemanager.posit.co/.../web/packages/{name}/ zwraca 404 dla wszystkich pakietów (także
ggplot2/dplyr), a snapshotowy indeks PACKAGES jest zbyt duży, by pobierać go na każdym PR.
Snapshot z r_cran_snapshot_date pozostaje w raporcie — pokazuje, co realnie instaluje obraz.
"""

from __future__ import annotations

import argparse
import lzma
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

import yaml

_UA = {"User-Agent": "wlb-package-existence-check"}
_TRANSIENT = {0, 429, 500, 502, 503, 504}  # 0 = błąd transportu/timeout
_PRESENT = {200, 301, 302}
_ABSENT = {404, 410}

# URL = Callable przyjmujący adres i zwracający kod HTTP; wstrzykiwany w testach (offline).
Fetch = Callable[[str], int]

PYPI = "https://pypi.org/pypi/{name}/json"
CONDA = "https://api.anaconda.org/package/conda-forge/{name}"
CRAN_WEB = "https://crandb.r-pkg.org/{name}"
GITHUB = "https://api.github.com/repos/{repo}"
# URL w raporcie (człowiek weryfikuje pakiet klikiem). Samo istnienie sprawdzamy wobec
# indeksu Packages (LINUX_INDEXES) — Launchpad przy ~80 pakietach na PR rate-limituje zapytania.
LINUX = "https://launchpad.net/ubuntu/noble/amd64/{name}"
_LINUX_PREFIX = "https://launchpad.net/ubuntu/noble/amd64/"
_LINUX_ARCHIVE = "https://archive.ubuntu.com/ubuntu"
_LINUX_SECURITY = "https://security.ubuntu.com/ubuntu"
LINUX_INDEXES = tuple(
    f"{base}/dists/{pocket}/{component}/binary-amd64/Packages.xz"
    for pocket, base in (
        ("noble", _LINUX_ARCHIVE),
        ("noble-updates", _LINUX_ARCHIVE),
        ("noble-security", _LINUX_SECURITY),
    )
    for component in ("main", "universe", "restricted", "multiverse")
)

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*")
_APT_MODULES = ("apt", "ansible.builtin.apt")
_TASK_LISTS = ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks", "handlers")
_APT_NAME = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9+.-]*)(?::[A-Za-z0-9-]+)?(?:=.*)?$")
_JINJA_ITEM = re.compile(r"^\s*\{\{\s*item(?:\.([A-Za-z_][A-Za-z0-9_]*))?\s*\}\}\s*$")


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
    # API Anaconda dla dużych pakietów (np. pyarrow) odpowiada 20-30 s. Krótszy timeout dawał
    # fałszywe "rejestr nieosiągalny" (fail-closed); reszta rejestrów odpowiada < 2 s.
    if "api.anaconda.org" in url:
        timeout = max(timeout, 45.0)
    req = urllib.request.Request(url, method="HEAD", headers=_UA)
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return resp.status
    except urllib.error.HTTPError as err:
        if err.code == 405:  # rejestr nie wspiera HEAD -> spróbuj GET
            try:
                get = urllib.request.Request(url, method="GET", headers=_UA)
                # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
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


def parse_r(root: Path, _snapshot: str) -> list[Pkg]:
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
        url = CRAN_WEB.format(name=name)
        out.append(Pkg("CRAN", name, src, url, fallback))
    return out


def _iter_tasks(node: object) -> Iterator[dict[str, object]]:
    """Rekurencyjnie zwraca dict-y zadań (tasks/handlers/block/rescue/always) z playbooka/roli."""
    if isinstance(node, list):
        for item in node:
            yield from _iter_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in _TASK_LISTS:
            child = node.get(key)
            if child is not None:
                yield from _iter_tasks(child)


def _expand_item(spec: str, loop_items: list[object] | None) -> list[str] | None:
    """Rozwiń wyłącznie literalną pętlę `{{ item }}` / `{{ item.pole }}`; inaczej None (skip)."""
    match = _JINJA_ITEM.fullmatch(spec)
    if match is None or loop_items is None:
        return None
    field = match.group(1)
    values: list[str] = []
    for item in loop_items:
        value: object
        if field is None:
            value = item
        elif isinstance(item, dict) and field in item:
            value = item[field]
        else:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
        text = str(value).strip()
        if not text or "{{" in text or "{%" in text:
            return None
        values.append(text)
    return values


def _apt_name(spec: str) -> str:
    """Nazwa pakietu bez pinu wersji i architektury ('pkg:amd64=1.2' -> 'pkg')."""
    match = _APT_NAME.fullmatch(spec.strip())
    return match.group("name") if match else ""


def _read_linux_allowlist(root: Path) -> set[str]:
    """Nazwy z ci/linux-package-allowlist.txt (po jednej w linii, `#` = uzasadnienie)."""
    path = root / "ci/linux-package-allowlist.txt"
    if not path.is_file():
        return set()
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            names.add(line.split()[0].lower())
    return names


class LinuxIndexError(Exception):
    """Nie udało się pobrać/odczytać indeksu Ubuntu — fail-closed."""


def _default_bytes(url: str, timeout: float = 30.0) -> bytes:
    """GET całego zasobu (indeks Packages.xz); tylko HTTPS do archive/security.ubuntu.com."""
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return resp.read()


def _add_provides(names: set[str], value: str) -> None:
    for item in value.split(","):
        token = item.strip().split("(", 1)[0].split()
        if token:
            names.add(token[0].lower())


def parse_packages_index(text: str) -> set[str]:
    """Nazwy z indeksu Packages: pola Package i Provides (także zawijane kontynuacją)."""
    names: set[str] = set()
    field = ""
    for line in text.splitlines():
        if line.startswith((" ", "\t")):
            if field == "provides":
                _add_provides(names, line.strip())
            continue
        key, sep, value = line.partition(":")
        field = ""
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "package" and value:
            names.add(value.lower())
        elif key == "provides":
            field = key
            _add_provides(names, value)
    return names


def load_linux_index(fetch_bytes: Callable[[str], bytes] = _default_bytes) -> set[str]:
    """Pobiera i scala indeksy Packages dla noble/updates/security (fail-closed)."""
    names: set[str] = set()
    for url in LINUX_INDEXES:
        try:
            raw = fetch_bytes(url)
            text = lzma.decompress(raw).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError, lzma.LZMAError) as exc:
            raise LinuxIndexError(f"{url}: {exc}") from exc
        names |= parse_packages_index(text)
    return names


def linux_fetch(index: set[str], fallback: Fetch) -> Fetch:
    """Fetch dla Pkg apt: 200/404 z indeksu; pozostałe URL-e deleguje do rejestru."""

    def fetch(url: str) -> int:
        if url.startswith(_LINUX_PREFIX):
            return 200 if unquote(url[len(_LINUX_PREFIX) :]).lower() in index else 404
        return fallback(url)

    return fetch


def parse_linux(root: Path, skipped: list[str] | None = None) -> list[Pkg]:
    """Pakiety apt zadeklarowane w Ansible (`name:` jako string/lista/loop).

    Obsługiwane są wyłącznie nazwy deterministyczne. Jinja bez literalnej pętli (np.
    `{{ apt_packages }}`) jest pomijana i raportowana w `skipped` — nie zgadujemy. Pakiety
    spoza archiwum Ubuntu (PPA/.deb) wycisza `ci/linux-package-allowlist.txt`.
    """
    paths = sorted(root.glob("ansible/roles/**/tasks/*.yml"))
    paths += sorted(root.glob("ansible/*.yml"))
    allow = _read_linux_allowlist(root)
    out: list[Pkg] = []
    seen: set[str] = set()
    for path in paths:
        source = path.relative_to(root).as_posix()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"{source}: niepoprawny YAML: {exc}") from exc
        for task in _iter_tasks(data):
            module = next((task[key] for key in _APT_MODULES if key in task), None)
            if not isinstance(module, dict):
                continue
            raw = module.get("name")
            if raw is None:  # apt: deb/upgrade bez listy pakietów
                continue
            specs = raw if isinstance(raw, list) else [raw]
            loop_raw = task.get("loop", task.get("with_items", task.get("with_list")))
            loop_items = loop_raw if isinstance(loop_raw, list) else None
            for spec in specs:
                if not isinstance(spec, str):
                    if skipped is not None:
                        skipped.append(f"{source}: {spec!r} (nie-string)")
                    continue
                spec = spec.strip()
                if not spec:
                    continue
                if "{{" in spec or "{%" in spec:
                    expanded = _expand_item(spec, loop_items)
                    if expanded is None:
                        if skipped is not None:
                            detail = f"Jinja; loop={loop_raw}" if loop_raw is not None else "Jinja"
                            skipped.append(f"{source}: {spec} ({detail})")
                        continue
                else:
                    expanded = [spec]
                for value in expanded:
                    name = _apt_name(value)
                    if not name:
                        if skipped is not None:
                            skipped.append(f"{source}: {value!r} (nieprawidłowa nazwa)")
                        continue
                    if name.lower() in allow:
                        if skipped is not None:
                            skipped.append(f"{source}: {name} (allowlista)")
                        continue
                    if name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    out.append(Pkg("apt", name, source, LINUX.format(name=quote(name, safe=""))))
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


def collect(root: Path, ecosystems: set[str], snapshot: str, skipped: list[str] | None = None) -> list[Pkg]:
    pkgs: list[Pkg] = []
    if "python" in ecosystems:
        pkgs += parse_python(root)
    if "r" in ecosystems:
        pkgs += parse_r(root, snapshot)
    if "linux" in ecosystems:
        pkgs += parse_linux(root, skipped)
    return pkgs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anty-halucynacja: istnienie pakietów w rejestrach.")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--ecosystems", default="python,r,linux", help="rozdzielone przecinkami: python,r,linux")
    parser.add_argument("--snapshot-date", default=None, help="data snapshotu CRAN (domyślnie z group_vars)")
    args = parser.parse_args(argv)

    ecosystems = {e.strip() for e in args.ecosystems.split(",") if e.strip()}
    snapshot = args.snapshot_date or read_snapshot(args.root)
    skipped: list[str] = []
    try:
        pkgs = collect(args.root, ecosystems, snapshot, skipped)
    except ValueError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1
    if skipped:
        print(f"Pominięto {len(skipped)} nazw (Jinja/allowlista/nieprawidłowe):", file=sys.stderr)
        for item in skipped[:20]:
            print(f"  - {item}", file=sys.stderr)
        if len(skipped) > 20:
            print(f"  ... i {len(skipped) - 20} więcej", file=sys.stderr)
    if not pkgs:
        print("Brak zadeklarowanych pakietów do sprawdzenia (sprawdź --root/--ecosystems).", file=sys.stderr)
        return 1
    fetch: Fetch = default_fetch
    if any(pkg.ecosystem == "apt" for pkg in pkgs):
        try:
            index = load_linux_index()
        except LinuxIndexError as exc:
            print(f"BŁĄD: nie udało się pobrać indeksu Ubuntu: {exc}", file=sys.stderr)
            return 1
        fetch = linux_fetch(index, default_fetch)
    findings = verify(pkgs, fetch)

    eco_str = ", ".join(sorted(ecosystems))
    crans = f"; snapshot CRAN={snapshot}" if "r" in ecosystems else ""
    print(f"Sprawdzono {len(pkgs)} zadeklarowanych pakietów ({eco_str}){crans}")
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
