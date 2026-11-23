"""Testy jednostkowe walidatora symboli symbol_refs.py (#367).

Weryfikuje:
1. Fixture regresji #366:
   - verify_audit_ready i wlb_build_profile opisane jako istniejące -> finding (undefined),
   - wlb_enable_e2e_target -> defined (PASS),
   - jawny plan (#268, propozycja) -> planned (PASS).
2. Zasada "komentarz / string / heredoc != definicja" (bash i HCL).
3. Brak fałszywych trafień dla allowlisty (true/false, IP, uprawnienia, ścieżki VM).
4. Kody wyjścia CLI:
   - kod 0 dla poprawnych symboli oraz w trybie report-only przy braku bramki,
   - kod 1 dla naruszeń przy aktywnej bramce (--gate / WLB_SYMBOL_REFS_GATING=1),
   - kod 2 dla błędu parsera lub konfiguracji (nieistniejący root / scope).
5. Brak fałszywych trafień na aktualnej dokumentacji repozytorium w docs/architektura/*.md.
"""

# ruff: noqa: S104, S108, E402

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ci.symbol_refs import (
    ALLOWLIST,
    Span,
    build_symbol_index,
    check_planned_marker,
    extract_ansible_variables,
    extract_bash_functions,
    extract_hcl_variables,
    main,
    resolve,
    scan_documents,
)

# --- 1. Fixture regresji #366 ------------------------------------------------


def test_regression_366_fixture(tmp_path: Path):
    """Fixture regresji z #366:

    - verify_audit_ready + wlb_build_profile opisane jako istniejące -> finding (undefined),
    - wlb_enable_e2e_target -> pass (defined),
    - jawny plan #268 -> pass (planned).
    """
    # 1. Tworzymy strukturę repozytorium odpowiadającą stanowi z #366 (brak wlb_build_profile i verify_audit_ready)
    packer_dir = tmp_path / "packer"
    packer_dir.mkdir(parents=True)
    (packer_dir / "variables.pkr.hcl").write_text(
        """
variable "image_name" {
  type = string
}

variable "wlb_enable_e2e_target" {
  type    = bool
  default = false
}
""",
        encoding="utf-8",
    )

    fb_dir = tmp_path / "ansible" / "roles" / "lab_config" / "files"
    fb_dir.mkdir(parents=True)
    (fb_dir / "wlb-firstboot").write_text(
        """#!/usr/bin/env bash
write_nftables() {
  echo "nftables"
}
""",
        encoding="utf-8",
    )

    doc_dir = tmp_path / "docs" / "architektura"
    doc_dir.mkdir(parents=True)

    # Dokument z odwołaniami jak w #366
    doc_text = """# Cykl wydania obrazu
| Element | Definicja |
|---|---|
| Profil (#277) | `packer/variables.pkr.hcl` (`wlb_build_profile`) |
| Weryfikacja | `wlb-firstboot` → `verify_audit_ready` |
| Przełącznik E2E | `packer` var `wlb_enable_e2e_target` |
| Planowany audyt | #268: `verify_audit_ready` (propozycja w PR #365) |
"""
    (doc_dir / "cykl-wydania-obrazu.md").write_text(doc_text, encoding="utf-8")

    index = build_symbol_index(tmp_path)
    results = scan_documents(tmp_path, scope="docs")

    findings = {span.token: res for span, res in results if res.status == "undefined"}
    defined = {span.token: res for span, res in results if res.status == "defined"}
    planned = {span.token: res for span, res in results if res.status == "planned"}

    # wlb_build_profile opisany jako istniejący -> finding (undefined)
    assert "wlb_build_profile" in findings
    assert findings["wlb_build_profile"].status == "undefined"

    # verify_audit_ready w wierszu 4 opisany jako istniejący -> finding (undefined)
    assert "verify_audit_ready" in findings
    assert findings["verify_audit_ready"].status == "undefined"

    # verify_audit_ready w wierszu 6 oznaczony z planem #268 / propozycja -> pass (planned)
    assert "verify_audit_ready" in planned
    assert planned["verify_audit_ready"].status == "planned"

    # wlb_enable_e2e_target zdefiniowany w variables.pkr.hcl -> pass (defined)
    assert "wlb_enable_e2e_target" in defined
    assert defined["wlb_enable_e2e_target"].status == "defined"
    assert "variables.pkr.hcl" in (defined["wlb_enable_e2e_target"].location or "")

    # Jawny plan #268 / propozycja -> pass (planned)
    # W wierszu 6 verify_audit_ready posiada znacznik propozycji i #268
    span_planned = Span(
        token="verify_audit_ready",
        line=6,
        kind_hint="bash_func",
        raw="| Planowany audyt | #268: `verify_audit_ready` (propozycja w PR #365) |",
        is_planned=True,
    )
    res_planned = resolve(span_planned, index)
    assert res_planned.status == "planned"


# --- 2. Komentarz / string / heredoc != definicja ----------------------------


def test_comment_string_heredoc_not_definition(tmp_path: Path):
    """Komentarz, string lub heredoc nie mogą być traktowane jako definicja symbolu."""
    # Test skryptu Bash
    script = tmp_path / "test_script.sh"
    script.write_text(
        """#!/usr/bin/env bash
# fake_commented_func() {
#   echo "not a definition"
# }

cat <<'EOF'
heredoc_func() {
  echo "inside heredoc"
}
EOF

echo "inline_string_func() { true; }"

real_active_func() {
  echo "real"
}
""",
        encoding="utf-8",
    )

    funcs = extract_bash_functions(script)
    assert "real_active_func" in funcs
    assert "fake_commented_func" not in funcs
    assert "heredoc_func" not in funcs
    assert "inline_string_func" not in funcs

    # Test pliku HCL
    hcl = tmp_path / "test.pkr.hcl"
    hcl.write_text(
        """
# variable "commented_var" {
// variable "slash_commented_var" {
/* variable "block_comment_var" { */
variable "real_hcl_var" {
  type = string
}
""",
        encoding="utf-8",
    )

    hcl_vars = extract_hcl_variables(hcl)
    assert "real_hcl_var" in hcl_vars
    assert "commented_var" not in hcl_vars
    assert "slash_commented_var" not in hcl_vars
    assert "block_comment_var" not in hcl_vars


def test_ansible_vars_extraction(tmp_path: Path):
    """Wyodrębnianie zmiennych Ansible z plików YAML."""
    group_vars = tmp_path / "all.yml"
    group_vars.write_text(
        """
# Komentarz z fałszywą zmienną: fake_comment_var: 123
wlb_timezone: Europe/Warsaw
wlb_image_name: wlb-general
wlb_directories:
  - path: /workspace
""",
        encoding="utf-8",
    )

    vars_set = extract_ansible_variables(group_vars)
    assert "wlb_timezone" in vars_set
    assert "wlb_image_name" in vars_set
    assert "wlb_directories" in vars_set
    assert "fake_comment_var" not in vars_set


# --- 3. Allowlista nie daje fałszywych trafień --------------------------------


def test_allowlist_no_false_positives(tmp_path: Path):
    """Żaden element z jawnej allowlisty nie może być klasyfikowany jako undefined."""
    index = build_symbol_index(tmp_path)

    sample_allowlist = [
        "true",
        "false",
        "null",
        "127.0.0.1",
        "0.0.0.0",
        "5432",
        "0600",
        "0755",
        "systemctl",
        "auditctl",
        "nftables",
        "/sluza-out",
        "/workspace/.wlb-export-queue",
        "~/.pgpass",
        "main",
        "UUID v4",
        "sha256",
        "wlb-sluza-out.service",
        "manifest.json",
        "unsupported_type",
    ]

    for item in sample_allowlist:
        assert item in ALLOWLIST, f"Brak elementu {item} w globalnej ALLOWLIST"
        res = resolve(item, index)
        assert res.status in (
            "defined",
            "planned",
        ), f"Element allowlisty '{item}' nie przeszedł (status: {res.status}, reason: {res.reason})"


def test_planned_markers_detection():
    """Wykrywanie znaczników planu w tekście."""
    assert check_planned_marker("Weryfikacja audytu (#268): verify_audit_ready", "verify_audit_ready")
    assert check_planned_marker("Weryfikacja audytu [#268]: verify_audit_ready", "verify_audit_ready")
    assert check_planned_marker("Propozycja: wlb_build_profile", "wlb_build_profile")
    assert check_planned_marker("wlb_build_profile — niezrealizowane w main", "wlb_build_profile")
    assert check_planned_marker("funkcja planowana do realizacji: token", "token")
    assert not check_planned_marker("Zwykły opis komponentu: token", "token")
    # Tabela Markdown: znacznik w innej kolumnie nie planuje tokenu w bieżącej kolumnie
    table_row = "| Profil (#277) | `packer/variables.pkr.hcl` (`wlb_build_profile`) |"
    assert not check_planned_marker(table_row, "wlb_build_profile")


# --- 4. Kody wyjścia CLI (0, 1, 2) -------------------------------------------


def test_cli_exit_code_2_on_config_or_parser_error():
    """Błąd konfiguracji lub parsera (nieistniejący root / scope) zwraca kod 2."""
    # Nieistniejący katalog root
    rc = main(["--root", "/tmp/non_existent_wlb_root_dir_367", "--scope", "docs"])
    assert rc == 2

    # Nieistniejący zakres
    rc = main(["--root", str(REPO_ROOT), "--scope", "non_existent_scope_dir"])
    assert rc == 2


def test_cli_report_only_vs_gating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Tryb report-only zwraca kod 0 przy naruszeniach; --gate zwraca kod 1."""
    doc_dir = tmp_path / "docs" / "architektura"
    doc_dir.mkdir(parents=True)
    (doc_dir / "test.md").write_text("Odwołanie do `wlb_non_existent_symbol_367`.\n", encoding="utf-8")

    # 1. Domyślnie report-only -> kod 0 mimo znalezienia naruszeń
    monkeypatch.delenv("WLB_SYMBOL_REFS_GATING", raising=False)
    rc_report = main(["--root", str(tmp_path), "--scope", "docs"])
    assert rc_report == 0

    # 2. Z flagą --gate -> kod 1 (bramka)
    rc_gate = main(["--root", str(tmp_path), "--scope", "docs", "--gate"])
    assert rc_gate == 1

    # 3. Ze zmienną środowiskową WLB_SYMBOL_REFS_GATING=1 -> kod 1
    monkeypatch.setenv("WLB_SYMBOL_REFS_GATING", "1")
    rc_env_gate = main(["--root", str(tmp_path), "--scope", "docs"])
    assert rc_env_gate == 1


def test_cli_clean_returns_0(tmp_path: Path):
    """Czyste dokumenty zwracają kod 0 zarówno w trybie raportowym, jak i bramkującym."""
    doc_dir = tmp_path / "docs" / "architektura"
    doc_dir.mkdir(parents=True)
    (doc_dir / "clean.md").write_text(
        "Odwołanie do dozwolonych pojęć `true`, `127.0.0.1`, `0600` oraz `/sluza-out`.\n",
        encoding="utf-8",
    )

    assert main(["--root", str(tmp_path), "--scope", "docs"]) == 0
    assert main(["--root", str(tmp_path), "--scope", "docs", "--gate"]) == 0


# --- 5. Poprawki z recenzji: ukryte ścieżki i zmienne w blokach fenced --------


def test_hidden_path_prefix_preservation(tmp_path: Path):
    """Ścieżki ukryte (np. .github/workflows/ci.yml) nie mogą tracić kropki przez stripowanie."""
    gh_dir = tmp_path / ".github" / "workflows"
    gh_dir.mkdir(parents=True)
    (gh_dir / "ci.yml").write_text("name: CI\n", encoding="utf-8")

    index = build_symbol_index(tmp_path)

    # Bez prefiksu ./
    res1 = resolve(".github/workflows/ci.yml", index)
    assert res1.status == "defined", f"Oczekiwano statusu 'defined', otrzymano: {res1}"
    assert res1.location == ".github/workflows/ci.yml"

    # Z prefiksem ./
    res2 = resolve("./.github/workflows/ci.yml", index)
    assert res2.status == "defined", f"Oczekiwano statusu 'defined', otrzymano: {res2}"
    assert res2.location == ".github/workflows/ci.yml"


def test_fenced_code_blocks_local_variables_ignored(tmp_path: Path):
    """Zmienne lokalne w blokach kodu fenced nie generują fałszywych trafień (undefined)."""
    doc_dir = tmp_path / "docs" / "architektura"
    doc_dir.mkdir(parents=True)

    doc_content = """# Przykładowy skrypt
```bash
# Komentarz w bloku: funkcja_w_komentarzu()
local przykladowa_zmienna_lokalna="wartosc"
druga_zmienna_lokalna=123
echo "$przykladowa_zmienna_lokalna"

# Wywołanie funkcji z prefiksem wlb lub z nawiasami:
wlb_brakujaca_funkcja()
wlb_nieistniejaca_zmienna=1
```
"""
    (doc_dir / "snippet.md").write_text(doc_content, encoding="utf-8")

    results = scan_documents(tmp_path, scope="docs")
    undefined_tokens = {span.token for span, res in results if res.status == "undefined"}

    # Zmienne lokalne bez prefiksu wlb_* nie mogą być raportowane jako undefined
    assert "przykladowa_zmienna_lokalna" not in undefined_tokens
    assert "druga_zmienna_lokalna" not in undefined_tokens
    assert "funkcja_w_komentarzu" not in undefined_tokens

    # Symbole projektowe wlb_* i wywołania funkcji powinny być wykryte
    assert "wlb_brakujaca_funkcja" in undefined_tokens


# --- 6. Weryfikacja bieżących dokumentów repozytorium -------------------------


def test_real_repo_docs_architektura_clean():
    """Bieżące dokumenty w docs/architektura/*.md nie posiadają nieistniejących symboli."""
    results = scan_documents(REPO_ROOT, scope="docs")
    findings = [(span, res) for span, res in results if res.status == "undefined"]
    assert not findings, f"Wykryto nieoczekiwane naruszenia w docs/architektura: {findings}"
