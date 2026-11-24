#!/usr/bin/env python3
"""Walidator halucynacji identyfikatorów i symboli w dokumentacji (#367).

Weryfikuje odwołania do symboli (funkcje bash, zmienne HCL Packera, zmienne Ansible,
ścieżki plików) w dokumentacji Markdown (zakres docs/architektura/*.md).
Wykrywa nieistniejące symbole opisane jako istniejące w repozytorium (przypadek #366:
verify_audit_ready, wlb_build_profile).

Zasady:
- Deterministyczny, offline, bez zapytań do sieci i LLM.
- per-kind detekcja DEFINICJI (komentarz / string / heredoc != definicja).
- Symbole ze znacznikiem planu ((#NNN), propozycja, niezrealizowane) -> status planned (PASS).
- Jawna allowlista nie-symboli (true/false, adresy IP, narzędzia systemowe, ścieżki VM).
- Domyślnie tryb raportowy (exit 0; bramkuje kodem 1 przy --gate lub WLB_SYMBOL_REFS_GATING=1).
- Błąd konfiguracji / parsera -> kod 2.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

# --- Allowlista jawnych nie-symboli i standardowych pojęć --------------------

ALLOWLIST_BOOLEANS = {
    "true",
    "false",
    "yes",
    "no",
    "null",
    "none",
    "nil",
}

ALLOWLIST_NETWORKING = {
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104  # nosec B104
    "::1",
    "localhost",
    "5432",
    "8000",
    "8080",
    "22",
    "80",
    "443",
    "HUB_ALLOWED_CIDR",
    "RESEARCHERS_PER_VM",
}

ALLOWLIST_PERMISSIONS = {
    "0600",
    "0640",
    "0644",
    "0700",
    "0711",
    "0750",
    "0755",
    "1730",
    "2770",
}

ALLOWLIST_SYSTEM_TOOLS = {
    "actionlint",
    "ansible",
    "ansible-lint",
    "ansible-playbook",
    "auditctl",
    "augenrules",
    "ausearch",
    "awk",
    "bandit",
    "bash",
    "bats",
    "cat",
    "checkov",
    "chmod",
    "chown",
    "cp",
    "curl",
    "cut",
    "find",
    "fuser",
    "git",
    "gitleaks",
    "grep",
    "gzip",
    "initdb",
    "inotify",
    "iptables",
    "journalctl",
    "kcov",
    "kill",
    "ln",
    "ls",
    "lynis",
    "make",
    "mermaid-cli",
    "mkdir",
    "mktemp",
    "mutmut",
    "mv",
    "nft",
    "nftables",
    "osv-scanner",
    "packer",
    "pg_createcluster",
    "pip",
    "psql",
    "pytest",
    "python",
    "python3",
    "rm",
    "ruff",
    "sed",
    "semgrep",
    "sh",
    "shellcheck",
    "shfmt",
    "sqlite3",
    "ssh",
    "sshd",
    "su",
    "sudo",
    "systemctl",
    "tar",
    "terraform",
    "test",
    "trap",
    "uuidgen",
    "wget",
    "yamllint",
}

# Ścieżki w środowisku uruchomieniowym VM (nie w repozytorium git)
ALLOWLIST_VM_PATHS = {
    "/data-mart",
    "/dev/null",
    "/docs",
    "/etc/audit/rules.d/50-wlb.rules",
    "/etc/wlb/image-release",
    "/etc/wlb/lab.env",
    "/projekt",
    "/run",
    "/sluza-in",
    "/sluza-odrzucone",
    "/sluza-out",
    "/sluza-potwierdzenia",
    "/tmp",  # noqa: S108  # nosec B108
    "/usr/local/bin/dbeaver",
    "/usr/local/sbin/wlb-sluza-out-mover",
    "/var/log",
    "/workspace",
    "/workspace/.wlb-export-queue",
    "/workspace/.wlb-hub",
    "/workspace/pgdata",
    "~/.local/share/DBeaverData",
    "~/.pgpass",
}

ALLOWLIST_GENERIC = {
    ".incoming",
    "A",
    "AU",
    "B",
    "FB",
    "HEAD",
    "HUB",
    "JSON",
    "K",
    "M",
    "MD5",
    "NFT",
    "OP",
    "Q",
    "SCRAM",
    "SHA-256",
    "SHA256",
    "SN",
    "SO",
    "UUID",
    "UUID v4",
    "YAML",
    "a01",
    "attrib",
    "bool",
    "classDiagram",
    "close_write",
    "create",
    "delete",
    "dev",
    "dict",
    "die",
    "erDiagram",
    "exit 0",
    "exit 1",
    "flowchart",
    "int",
    "json",
    "jupyter",
    "jupyterhub-users",
    "list",
    "main",
    "master",
    "md5",
    "moved_to",
    "nobody",
    "origin",
    "pending_review",
    "pie",
    "production",
    "receipt_notice",
    "reject_notice",
    "rename",
    "request_id",
    "return 0",
    "return 1",
    "root",
    "scram-sha-256",
    "sequenceDiagram",
    "sha256",
    "stateDiagram",
    "status",
    "string",
    "sync",
    "u01",
    "u02",
    "ubuntu",
    "uid",
    "uuid",
    "verify",
    "wlb-sluza-out",
    "yaml",
}

ALLOWLIST_SYSTEMD_SERVICES = {
    "auditd.service",
    "jupyterhub.service",
    "postgresql@16-main.service",
    "rsyslog.service",
    "traefik.service",
    "wlb-audit-rules.service",
    "wlb-firstboot.service",
    "wlb-monitoring.service",
    "wlb-postgres-provision.service",
    "wlb-postgres-setup.service",
    "wlb-sluza-out.service",
}

ALLOWLIST_DOMAIN_CONCEPTS = {
    "export_request",
    "hardlink",
    "limit",
    "manifest.json",
    "mixed_owner",
    "queued_as",
    "source_changed",
    "unsupported_type",
    "wlb-export-queue",
}

ALLOWLIST: set[str] = (
    ALLOWLIST_BOOLEANS
    | ALLOWLIST_NETWORKING
    | ALLOWLIST_PERMISSIONS
    | ALLOWLIST_SYSTEM_TOOLS
    | ALLOWLIST_VM_PATHS
    | ALLOWLIST_GENERIC
    | ALLOWLIST_SYSTEMD_SERVICES
    | ALLOWLIST_DOMAIN_CONCEPTS
)

# Znaczniki planowanych / przyszłych elementów
PLANNED_LINE_KEYWORDS = (
    "propozycja",
    "propozycje",
    "proponowan",
    "proponuje",
    "niezrealizowan",
    "niezaimplementowan",
    "planowan",
    "w planach",
    "nie w main",
    "niezrealizowane w main",
    "brak w main",
    "niezaimplementowana w main",
    "todo",
    "future",
)

RE_ISSUE_OR_PR = re.compile(r"(?:#\d+|PR\s*#\d+|\[#\d+\]|\(#\d+\))")
RE_HEX_SHA = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


@dataclass(frozen=True)
class Span:
    """Odwołanie do kodu lub symbolu wyodrębnione z dokumentu Markdown."""

    token: str
    line: int
    kind_hint: str  # "path", "bash_func", "hcl_var", "ansible_var", "symbol", "unknown"
    raw: str = ""
    is_planned: bool = False
    file_path: str = ""


@dataclass(frozen=True)
class Resolution:
    """Wynik weryfikacji istnienia symbolu."""

    status: str  # "defined" | "undefined" | "planned"
    kind: str
    location: str | None = None
    reason: str | None = None


@dataclass
class SymbolIndex:
    """Indeks definicji symboli w repozytorium."""

    root: Path
    files: set[str]
    file_basenames: dict[str, list[str]]
    bash_funcs: dict[str, str]
    hcl_vars: dict[str, str]
    ansible_vars: dict[str, str]


# --- Ekstrakcja definicji z kodu repozytorium ---------------------------------


def extract_bash_functions(file_path: Path) -> set[str]:
    """Wyszukuje nazwy funkcji bash zdefiniowanych w pliku.

    Ignoruje komentarze (#), stringi oraz bloki heredoc (<<EOF).
    """
    funcs: set[str] = set()
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return funcs

    in_heredoc: str | None = None
    heredoc_pattern = re.compile(r"<<-?\s*['\"]?([A-Za-z0-9_]+)['\"]?")
    func_pattern1 = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_-]*)\s*\(\)\s*\{?")
    func_pattern2 = re.compile(r"^\s*function\s+([a-zA-Z_][a-zA-Z0-9_-]+)(?:\s*\(\))?\s*\{?")

    for line in text.splitlines():
        stripped = line.strip()

        if in_heredoc:
            if stripped == in_heredoc:
                in_heredoc = None
            continue

        if stripped.startswith("#"):
            continue

        m_hd = heredoc_pattern.search(line)
        if m_hd:
            delim = m_hd.group(1)
            if delim not in ("0", "1", "2"):
                in_heredoc = delim

        m1 = func_pattern1.match(line)
        if m1:
            name = m1.group(1)
            if name not in ("if", "then", "else", "elif", "fi", "case", "esac"):
                funcs.add(name)
            continue

        m2 = func_pattern2.match(line)
        if m2:
            funcs.add(m2.group(1))

    return funcs


def extract_hcl_variables(file_path: Path) -> set[str]:
    """Wyszukuje zmienne HCL: variable \"name\" {...}.

    Ignoruje komentarze (#, //, /* ... */) i stringi.
    """
    vars_set: set[str] = set()
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return vars_set

    hcl_pattern = re.compile(r'^\s*variable\s+"([a-zA-Z0-9_-]+)"\s*\{')
    in_block_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        if "/*" in line:
            # Komentarz blokowy może zaczynać się i kończyć w tej samej linii;
            # definicja po nim nie jest już analizowana.
            if "*/" not in line.split("/*", 1)[1]:
                in_block_comment = True
            continue
        m = hcl_pattern.match(line)
        if m:
            vars_set.add(m.group(1))
    return vars_set


def extract_ansible_variables(file_path: Path) -> set[str]:
    """Wyszukuje definicje zmiennych Ansible z plików YAML (group_vars, defaults, vars)."""
    vars_set: set[str] = set()
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        data = yaml.safe_load(content)
    except Exception:
        return vars_set

    if isinstance(data, dict):
        for key in data:
            if isinstance(key, str):
                vars_set.add(key)
    return vars_set


def build_symbol_index(root: Path) -> SymbolIndex:
    """Skanuje repozytorium i indeksuje istniejące pliki, funkcje bash oraz zmienne HCL i Ansible."""
    files: set[str] = set()
    file_basenames: dict[str, list[str]] = {}
    bash_funcs: dict[str, str] = {}
    hcl_vars: dict[str, str] = {}
    ansible_vars: dict[str, str] = {}

    ignored_dirs = {".git", ".tools", "__pycache__", ".venv", "venv", ".pytest_cache", "build", "output", "dist"}

    binary_extensions = {
        ".qcow2",
        ".img",
        ".iso",
        ".bin",
        ".tar",
        ".gz",
        ".xz",
        ".zip",
        ".jar",
        ".class",
        ".png",
        ".jpg",
        ".pdf",
        ".whl",
        ".deb",
    }

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored_dirs]
        rel_dir = Path(dirpath).relative_to(root)
        if str(rel_dir) != ".":
            files.add(str(rel_dir))

        for fname in filenames:
            fpath = Path(dirpath) / fname
            rel = str(fpath.relative_to(root))
            files.add(rel)
            file_basenames.setdefault(fname, []).append(rel)

            # Ignoruj pliki binarne oraz pliki > 2 MB
            if fpath.suffix in binary_extensions:
                continue
            try:
                if fpath.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue

            # Bash scripts & files
            if (
                fpath.suffix in (".sh", ".bash", ".bats")
                or (rel.startswith("packer/scripts/") and not fpath.suffix)
                or (rel.startswith("ci/") and fpath.suffix in (".sh", ""))
                or (rel.startswith("tests/") and fpath.suffix in (".sh", ".bash", ".bats", ""))
                or ("ansible/roles" in rel and "files" in rel and not fpath.suffix)
            ):
                for func in extract_bash_functions(fpath):
                    bash_funcs[func] = rel

            # Packer / Terraform HCL
            if fpath.suffix == ".hcl" or rel.startswith("packer/"):
                for var in extract_hcl_variables(fpath):
                    hcl_vars[var] = rel

            # Ansible group_vars & defaults
            if ("group_vars" in rel or "defaults" in rel or "vars" in rel) and (fpath.suffix in (".yml", ".yaml")):
                for var in extract_ansible_variables(fpath):
                    ansible_vars[var] = rel

    return SymbolIndex(
        root=root,
        files=files,
        file_basenames=file_basenames,
        bash_funcs=bash_funcs,
        hcl_vars=hcl_vars,
        ansible_vars=ansible_vars,
    )


# --- Parsowanie dokumentów Markdown i code-spanów ----------------------------


def check_planned_marker(line: str, token: str) -> bool:
    """Sprawdza, czy obok tokenu znajduje się jawny znacznik planu/propozycji (#NNN, propozycja itp.)."""
    target_text = line
    if "|" in line and token:
        cells = [c for c in line.split("|") if token in c]
        if cells:
            target_text = cells[0]

    lower_text = target_text.lower()
    for kw in PLANNED_LINE_KEYWORDS:
        if kw in lower_text:
            return True

    return bool(RE_ISSUE_OR_PR.search(target_text))


def _classify_token(token: str) -> str:
    """Pomocnicza klasyfikacja wstępna tokenu."""
    if "/" in token or token.endswith(
        (
            ".sh",
            ".yml",
            ".yaml",
            ".hcl",
            ".bats",
            ".py",
            ".md",
            ".json",
            ".conf",
            ".service",
            ".rules",
            ".env",
        )
    ):
        return "path"
    if token.endswith("()"):
        return "bash_func"
    if token.startswith("wlb_"):
        return "symbol"
    return "unknown"


def extract_code_spans(text: str, file_path: str = "") -> list[Span]:
    """Wyodrębnia code-spany z backticków oraz bloków fenced code (```)."""
    spans: list[Span] = []
    in_fenced_block = False
    fence_info = ""

    backtick_pattern = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
    identifier_pattern = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_-]*\b")

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()

        # Fenced code block (```lang ... ```)
        if stripped.startswith("```"):
            if not in_fenced_block:
                in_fenced_block = True
                fence_info = stripped[3:].strip().lower()
            else:
                in_fenced_block = False
                fence_info = ""
            continue

        if in_fenced_block:
            # W blokach diagramów (mermaid) lub skryptów szukamy identyfikatorów
            if fence_info in ("mermaid", "bash", "sh", "shell", ""):
                line_planned = check_planned_marker(raw_line, "")
                # Ignoruj linie komentarzy wewnątrz bloku kodu
                if stripped.startswith("#"):
                    continue

                for m in identifier_pattern.finditer(raw_line):
                    word = m.group(0)
                    # Ignoruj przypisania zmiennych lokalnych w powłoce (np. local var=..., typeset var=..., var=...)
                    if re.search(rf"\b(local|typeset)\s+{re.escape(word)}\b", raw_line):
                        continue
                    if re.search(rf"^\s*{re.escape(word)}=", raw_line):
                        continue

                    # W blokach fenced filtrujemy zmienne lokalne z przykładów:
                    # sprawdzamy tylko symbole projektowe (wlb_*, wlb-*, WLB_*)
                    # lub jawne wywołania funkcji bash/sh (token przed nawiasem '(').
                    is_wlb_token = word.startswith("wlb-") or word.startswith("wlb_") or word.startswith("WLB_")
                    is_func_call = fence_info in ("bash", "sh", "shell") and bool(
                        re.search(rf"\b{re.escape(word)}\s*\(\s*\)", raw_line)
                    )

                    if is_wlb_token or is_func_call:
                        spans.append(
                            Span(
                                token=word,
                                line=line_no,
                                kind_hint="bash_func" if is_func_call else _classify_token(word),
                                raw=raw_line,
                                is_planned=line_planned or check_planned_marker(raw_line, word),
                                file_path=file_path,
                            )
                        )
            continue

        # Poza blokami fenced: odnajdujemy inline backticki
        for m in backtick_pattern.finditer(raw_line):
            code = m.group(2).strip()
            if not code:
                continue

            # Jeżeli całe wyrażenie jest na allowliście
            if code in ALLOWLIST:
                spans.append(
                    Span(
                        token=code,
                        line=line_no,
                        kind_hint="allowlist",
                        raw=raw_line,
                        is_planned=False,
                        file_path=file_path,
                    )
                )
                continue

            # Pojedynczy token w backtickach
            clean_token = code.rstrip("()").strip()
            if " " not in clean_token and "\t" not in clean_token:
                is_planned = check_planned_marker(raw_line, clean_token)
                spans.append(
                    Span(
                        token=clean_token,
                        line=line_no,
                        kind_hint=_classify_token(code),
                        raw=raw_line,
                        is_planned=is_planned,
                        file_path=file_path,
                    )
                )
            else:
                # Wyrażenie wielowyrazowe w backtickach — wyodrębniamy kandydatów na symbole
                for sub in code.split():
                    sub_clean = sub.strip("(),;:`'\"")
                    if (
                        "/" in sub_clean
                        or "_" in sub_clean
                        or sub_clean.startswith("wlb-")
                        or sub_clean.endswith((".sh", ".yml", ".hcl", ".pkr.hcl"))
                    ):
                        spans.append(
                            Span(
                                token=sub_clean,
                                line=line_no,
                                kind_hint=_classify_token(sub_clean),
                                raw=raw_line,
                                is_planned=check_planned_marker(raw_line, sub_clean),
                                file_path=file_path,
                            )
                        )

    return spans


# --- Rezolwer definicji (resolve) --------------------------------------------


def resolve(
    token: str | Span,
    root_or_index: Path | SymbolIndex,
    context: str = "",
) -> Resolution:
    """Weryfikuje status definicji tokenu: defined, undefined lub planned."""
    if isinstance(token, Span):
        token_str = token.token
        kind_hint = token.kind_hint
        is_planned = token.is_planned
        file_path = token.file_path
        context_str = token.raw or context
    else:
        token_str = str(token).strip()
        kind_hint = _classify_token(token_str)
        is_planned = check_planned_marker(context or token_str, token_str)
        file_path = ""
        context_str = context

    index = build_symbol_index(root_or_index) if isinstance(root_or_index, Path) else root_or_index

    # 1. Jawny znacznik planowanego / niezrealizowanego symbolu
    if is_planned or check_planned_marker(context_str, token_str):
        return Resolution(
            status="planned",
            kind=kind_hint,
            reason="oznaczony jako planowany / niezrealizowany",
        )

    # 2. Allowlista jawnych nie-symboli
    if token_str in ALLOWLIST or RE_HEX_SHA.match(token_str) or "*" in token_str or "~" in token_str:
        return Resolution(
            status="defined",
            kind="allowlist",
            reason="na allowliście nie-symboli",
        )

    # 2.5. Pliki w repozytorium dopasowane po jednoznacznej nazwie (np. wlb-sluza-out-mover).
    # Token ze ścieżką musi przejść przez weryfikację ścieżki poniżej, a nie przez basename.
    if "/" not in token_str:
        basename_matches = index.file_basenames.get(token_str, [])
        if len(basename_matches) == 1:
            return Resolution(
                status="defined",
                kind="file",
                location=basename_matches[0],
            )

    # 3. Weryfikacja ścieżki pliku (path)
    if (
        kind_hint == "path"
        or "/" in token_str
        or token_str.endswith((".sh", ".yml", ".yaml", ".hcl", ".bats", ".py", ".md", ".json", ".conf", ".service"))
    ):
        norm_path = token_str.removeprefix("./")

        # Ścieżka VM z allowlisty
        if token_str in ALLOWLIST_VM_PATHS or any(token_str.startswith(vm) for vm in ("/workspace", "/sluza", "/etc")):
            return Resolution(
                status="defined",
                kind="path",
                reason="ścieżka środowiska uruchomieniowego VM",
            )

        # Względna ścieżka do pliku w repozytorium
        if norm_path in index.files or (index.root / norm_path).exists():
            return Resolution(
                status="defined",
                kind="path",
                location=norm_path,
            )

        # Względna ścieżka względem katalogu dokumentu
        if file_path:
            doc_dir = (index.root / file_path).parent
            if (doc_dir / norm_path).exists():
                return Resolution(
                    status="defined",
                    kind="path",
                    location=str((doc_dir / norm_path).relative_to(index.root)),
                )

        # Dopasowanie po jednoznacznej nazwie pliku tylko dla tokenu bez ścieżki.
        if "/" not in norm_path:
            basename_matches = index.file_basenames.get(norm_path, [])
            if len(basename_matches) == 1:
                return Resolution(
                    status="defined",
                    kind="path",
                    location=basename_matches[0],
                )

        return Resolution(
            status="undefined",
            kind="path",
            reason=f"ścieżka '{token_str}' nie istnieje w repozytorium",
        )

    # 4. Zmienne HCL Packera
    if token_str in index.hcl_vars:
        return Resolution(
            status="defined",
            kind="hcl_var",
            location=index.hcl_vars[token_str],
        )

    # 5. Zmienne Ansible
    if token_str in index.ansible_vars:
        return Resolution(
            status="defined",
            kind="ansible_var",
            location=index.ansible_vars[token_str],
        )

    # 6. Funkcje Bash
    if token_str in index.bash_funcs:
        return Resolution(
            status="defined",
            kind="bash_func",
            location=index.bash_funcs[token_str],
        )

    # 7. Słowa generyczne bez podkreśleń ani myślników (np. nagłówki, proza w backtickach).
    # Wyjątek: jawne wywołanie funkcji bez definicji jest halucynacją, nie prozą.
    if kind_hint != "bash_func" and "_" not in token_str and "-" not in token_str and not token_str.startswith("wlb"):
        return Resolution(
            status="defined",
            kind="prose_token",
            reason="pojęcie ogólne / tekst prozy",
        )

    # 8. Brak definicji — symbol nie został znaleziony
    return Resolution(
        status="undefined",
        kind=kind_hint if kind_hint != "unknown" else "symbol",
        reason=f"symbol '{token_str}' nie posiada definicji w repozytorium (brak w bash, HCL i Ansible)",
    )


# --- Skanowanie dokumentacji i CLI --------------------------------------------


def scan_documents(root: Path | str, scope: str = "docs") -> list[tuple[Span, Resolution]]:
    """Skanuje pliki Markdown w zadanym zakresie i zwraca listę (Span, Resolution)."""
    root_path = Path(root)
    index = build_symbol_index(root_path)
    results: list[tuple[Span, Resolution]] = []

    if scope == "docs":
        doc_dir = root_path / "docs" / "architektura"
        if not doc_dir.is_dir():
            raise FileNotFoundError(f"Katalog zakresu docs nie istnieje: {doc_dir}")
        md_files = sorted(doc_dir.glob("*.md"))
    else:
        target = root_path / scope
        if target.is_file():
            md_files = [target]
        elif target.is_dir():
            md_files = sorted(target.glob("*.md"))
        else:
            raise FileNotFoundError(f"Zakres nie został znaleziony: {target}")

    for md_file in md_files:
        rel_path = str(md_file.relative_to(root_path))
        text = md_file.read_text(encoding="utf-8", errors="replace")
        spans = extract_code_spans(text, file_path=rel_path)
        for span in spans:
            res = resolve(span, index)
            results.append((span, res))

    return results


def main(argv: Sequence[str] | None = None) -> int:
    """Główny punkt wejścia CLI walidatora."""
    parser = argparse.ArgumentParser(
        description="Weryfikuje odwołania do symboli i identyfikatorów w dokumentacji WLB (#367)."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Ścieżka do głównego katalogu repozytorium (domyślnie: .)",
    )
    parser.add_argument(
        "--scope",
        default="docs",
        help="Zakres sprawdzanych dokumentów (domyślnie: docs -> docs/architektura/*.md)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Włącza tryb bramkujący (kod 1 przy znalezieniu nieistniejących symboli)",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"BŁĄD: Katalog repozytorium nie istnieje: {root}", file=sys.stderr)
        return 2

    is_gating = args.gate or os.environ.get("WLB_SYMBOL_REFS_GATING", "0") == "1"

    try:
        results = scan_documents(root, scope=args.scope)
    except Exception as exc:
        print(f"BŁĄD: Błąd konfiguracji lub parsera: {exc}", file=sys.stderr)
        return 2

    findings = [(span, res) for span, res in results if res.status == "undefined"]

    if findings:
        print(f"\nZnaleziono {len(findings)} nieistniejących symboli:")
        for span, res in findings:
            print(f"{span.file_path}:{span.line}:{span.token}:{res.reason}")

        if is_gating:
            print(
                "\n### BRAMKA symbol_refs — FAIL (wykryto nieistniejące symbole opisane jako istniejące)",
                file=sys.stderr,
            )
            return 1

        print(
            "\n### RAPORT symbol_refs — znaleziono naruszenia (tryb report-only; "
            "ustaw WLB_SYMBOL_REFS_GATING=1 lub dodaj --gate, aby bramkować)."
        )
        return 0

    checked_count = len(results)
    print(f"symbol_refs: sprawdzono {checked_count} odwołań — wszystkie są zdefiniowane lub zaplanowane (PASS).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
