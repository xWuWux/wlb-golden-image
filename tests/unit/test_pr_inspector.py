"""Testy jednostkowe modułu inspekcji PR (ci/pr_inspector.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pr_inspector as pi
import pytest


def test_parse_numstat_standard_and_binary() -> None:
    """Weryfikuje parsowanie linii numstat dla plików tekstowych i binarnych."""
    raw = """
10\t2\tci/test.sh
50\t0\tREADME.md
-\t-\timages/logo.png
0\t0\tempty.txt
"""
    files = pi.parse_numstat(raw)
    assert len(files) == 4

    assert files[0].path == "ci/test.sh"
    assert files[0].insertions == 10
    assert files[0].deletions == 2
    assert not files[0].is_binary

    assert files[1].path == "README.md"
    assert files[1].insertions == 50
    assert files[1].deletions == 0

    assert files[2].path == "images/logo.png"
    assert files[2].is_binary

    assert files[3].path == "empty.txt"


def test_parse_numstat_rejects_invalid_lines() -> None:
    """Niepoprawna linia numstat nie może być po cichu pominięta."""
    with pytest.raises(pi.PRInspectionError, match="Nieoczekiwana linia numstat"):
        pi.parse_numstat("invalid line\n")

    with pytest.raises(pi.PRInspectionError, match="Niepoprawne liczby"):
        pi.parse_numstat("x\ty\tfile.sh\n")


def test_classify_size_boundaries() -> None:
    """Weryfikuje progi klasyfikacji rozmiaru zgodne z kontraktem PR."""
    assert pi.classify_size(10, 5)[0] == "XS"
    assert pi.classify_size(49, 0)[0] == "XS"
    assert pi.classify_size(50, 0)[0] == "S"
    assert pi.classify_size(249, 0)[0] == "S"
    assert pi.classify_size(250, 0)[0] == "M"
    assert pi.classify_size(599, 0)[0] == "M"
    assert pi.classify_size(600, 0)[0] == "L"
    assert pi.classify_size(999, 0)[0] == "L"
    assert pi.classify_size(1000, 0)[0] == "XL"
    assert pi.classify_size(1500, 100)[0] == "XL"


def test_prod_patterns_cover_real_code() -> None:
    """Kod wykonawczy obejmuje całe ansible/packer, nie tylko wybrane podkatalogi."""
    for path in (
        "ansible/site.yml",
        "ansible/group_vars/all.yml",
        "ansible/roles/lab_config/tasks/main.yml",
        "packer/wlb-general.pkr.hcl",
        "packer/scripts/cleanup.sh",
        "ci/ready.sh",
        "scripts/foo.sh",
        "przewodnik-vm.sh",
    ):
        assert pi.PATTERNS_PROD_CODE.search(path), path

    for path in ("docs/ci-runbook.md", "CHANGELOG.md", "tests/unit/test_x.py"):
        assert not pi.PATTERNS_PROD_CODE.search(path), path


def test_check_test_completeness() -> None:
    """Weryfikuje regułę korelacji kodu produkcyjnego z testami."""
    files_ok = [
        pi.FileDiff("ansible/roles/lab_config/tasks/main.yml", 15, 2),
        pi.FileDiff("tests/unit/test_lab_config.py", 30, 5),
    ]
    has_prod, has_tests, msg, uncovered = pi.check_test_completeness(files_ok)
    assert has_prod is True
    assert has_tests is True
    assert uncovered == []
    assert "✅ Kod wykonawczy powiązany ze zmianami w testach" in msg
    assert "+30/-5" in msg

    files_missing = [
        pi.FileDiff("ci/unit.sh", 20, 5),
        pi.FileDiff("docs/architektura/index.md", 10, 0),
    ]
    has_prod, has_tests, msg, uncovered = pi.check_test_completeness(files_missing)
    assert has_prod is True
    assert has_tests is False
    assert uncovered == ["ci/unit.sh"]
    assert "⚠️ Wykryto zmiany w kodzie wykonawczym/CI bez modyfikacji testów" in msg

    files_only_tests = [
        pi.FileDiff("tests/unit/test_demo.py", 40, 0),
    ]
    has_prod, has_tests, msg, uncovered = pi.check_test_completeness(files_only_tests)
    assert has_prod is False
    assert has_tests is True
    assert uncovered == []
    assert "✅ Rozszerzenie zestawu testów" in msg

    files_docs = [
        pi.FileDiff("docs/ci-runbook.md", 25, 2),
    ]
    has_prod, has_tests, msg, uncovered = pi.check_test_completeness(files_docs)
    assert has_prod is False
    assert has_tests is False
    assert uncovered == []
    assert "ℹ️ Zmiana dotyczy wyłącznie dokumentacji" in msg


def test_check_test_completeness_rejects_unrelated_test() -> None:
    """Sam plik w tests/ nie dowodzi pokrycia konkretnego pliku produkcyjnego."""
    has_prod, has_tests, msg, uncovered = pi.check_test_completeness(
        [
            pi.FileDiff("ci/ready.sh", 10, 0),
            pi.FileDiff("tests/unit/test_unrelated.py", 50, 0),
        ]
    )
    assert has_prod is True
    assert has_tests is True
    assert uncovered == ["ci/ready.sh"]
    assert "brak bezpośredniego pokrycia" in msg


def test_check_test_completeness_matches_module_test() -> None:
    """Plik ci/foo.py jest pokryty przez tests/unit/test_foo.py."""
    has_prod, has_tests, msg, uncovered = pi.check_test_completeness(
        [
            pi.FileDiff("ci/foo.py", 10, 0),
            pi.FileDiff("tests/unit/test_foo.py", 50, 0),
        ]
    )
    assert has_prod is True
    assert has_tests is True
    assert uncovered == []
    assert "✅" in msg


CHANGELOG_DIFF = """diff --git a/CHANGELOG.md b/CHANGELOG.md
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -10,4 +10,5 @@
 ## Niewydane

+- **Nowy wpis:** opis zmiany.
"""

CHANGELOG_OTHER_SECTION = """diff --git a/CHANGELOG.md b/CHANGELOG.md
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -10,4 +10,5 @@
 ## Starsze zmiany

+- wpis w starej sekcji
"""

CHANGELOG_WITHOUT_SECTION = """diff --git a/CHANGELOG.md b/CHANGELOG.md
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -10,4 +10,5 @@
+- wpis bez sekcji
"""


def test_check_changelog() -> None:
    """Weryfikuje wpis w sekcji ## Niewydane, a nie samą zmianę pliku."""
    files_with_cl = [
        pi.FileDiff("ansible/roles/tljh/tasks/main.yml", 10, 0),
        pi.FileDiff("CHANGELOG.md", 5, 0),
    ]
    has_cl, msg = pi.check_changelog(files_with_cl, CHANGELOG_DIFF, has_prod=True)
    assert has_cl is True
    assert "✅ Wpis w sekcji ## Niewydane obecny" in msg

    has_cl, msg = pi.check_changelog(files_with_cl, CHANGELOG_OTHER_SECTION, has_prod=True)
    assert has_cl is False
    assert "brak wpisu w sekcji ## Niewydane" in msg

    has_cl, msg = pi.check_changelog(files_with_cl, CHANGELOG_WITHOUT_SECTION, has_prod=True)
    assert has_cl is False
    assert "brak wpisu w sekcji ## Niewydane" in msg

    files_no_cl = [
        pi.FileDiff("ansible/roles/tljh/tasks/main.yml", 10, 0),
    ]
    has_cl, msg = pi.check_changelog(files_no_cl, "", has_prod=True)
    assert has_cl is False
    assert "⚠️ Zmiana kodu/CI bez wpisu w CHANGELOG.md" in msg

    has_cl, msg = pi.check_changelog(files_no_cl, "", has_prod=False)
    assert "opcjonalny" in msg


def test_analyze_risks_categories() -> None:
    """Weryfikuje przypisywanie poziomów ryzyka na podstawie ścieżek i smells."""
    files_sec = [
        pi.FileDiff("ansible/roles/lab_config/files/nftables.conf", 5, 1),
    ]
    overall, risks = pi.analyze_risks(files_sec, [])
    assert overall == "HIGH"
    assert len(risks) == 1
    assert risks[0].area == "Bezpieczeństwo, sieć i izolacja"
    assert "nftables.conf" in risks[0].files[0]

    files_ci = [
        pi.FileDiff(".github/workflows/ci.yml", 12, 0),
    ]
    overall, risks = pi.analyze_risks(files_ci, [])
    assert overall == "MEDIUM"
    assert len(risks) == 1
    assert risks[0].area == "Potok CI/CD i budowa obrazu"

    files_docs = [
        pi.FileDiff("docs/architektura/index.md", 20, 5),
    ]
    overall, risks = pi.analyze_risks(files_docs, [])
    assert overall == "LOW"
    assert len(risks) == 0

    # Dokumentacja nie może być fałszywie klasyfikowana przez substring auth/storage.
    overall, risks = pi.analyze_risks([pi.FileDiff("docs/auth.md", 10, 0)], [])
    assert overall == "LOW"
    assert risks == []

    overall, risks = pi.analyze_risks([pi.FileDiff("ansible/roles/storage/tasks/main.yml", 10, 0)], [])
    assert overall == "HIGH"
    assert risks[0].area == "Bezpieczeństwo, sieć i izolacja"

    # Smell musi podnosić ryzyko, nawet jeśli ścieżka nie jest w macierzy.
    overall, risks = pi.analyze_risks([pi.FileDiff("docs/foo.md", 1, 0)], ["chmod 777 /tmp/x"])
    assert overall == "HIGH"
    assert any(r.area == "Ryzykowne wzorce w diffie" for r in risks)


def test_scan_diff_smells() -> None:
    """Weryfikuje wykrywanie realnych, niebezpiecznych wzorców w diffie."""
    diff_text = """
diff --git a/script.sh b/script.sh
--- a/script.sh
+++ b/script.sh
@@ -1,3 +1,7 @@
 # Normalny komentarz
+chmod 777 /tmp/secret_dir
+chmod -R a+rwx /tmp/open_dir
+curl -sSL https://example.com/install.sh | sudo bash
+eval $USER_INPUT
+permissions: write-all
-stara_linia
"""
    smells = pi.scan_diff_smells(diff_text)
    assert len(smells) == 5
    assert any("chmod 777" in s for s in smells)
    assert any("curl" in s and "bash" in s for s in smells)
    assert any("eval $" in s for s in smells)
    assert any("permissions: write-all" in s for s in smells)


def test_scan_diff_smells_ignores_docs_tests_and_prose() -> None:
    """Docstringi, komentarze i fikstury testowe nie mogą być raportowane jako smells."""
    diff_text = """
diff --git a/docs/security.md b/docs/security.md
--- a/docs/security.md
+++ b/docs/security.md
@@ -1,2 +1,3 @@
+# Przykład
+chmod 777 /tmp/example
diff --git a/tests/unit/test_fixture.py b/tests/unit/test_fixture.py
--- a/tests/unit/test_fixture.py
+++ b/tests/unit/test_fixture.py
@@ -1,2 +1,3 @@
+chmod 777 /tmp/fixture
diff --git a/ci/pr_inspector.py b/ci/pr_inspector.py
--- a/ci/pr_inspector.py
+++ b/ci/pr_inspector.py
@@ -1,2 +1,3 @@
+5. Wykrywania wzorców: chmod 777, curl | bash
+smells.append(f"chmod 777: {line}")
"""
    assert pi.scan_diff_smells(diff_text) == []


def test_generate_reviewer_questions() -> None:
    """Weryfikuje generowanie pytań kontrolnych dla recenzenta."""
    risks = [
        pi.RiskFactor(
            level="HIGH",
            area="Bezpieczeństwo, sieć i izolacja",
            reason="Firewall",
            files=["nftables.conf"],
        ),
        pi.RiskFactor(
            level="MEDIUM",
            area="Potok CI/CD i budowa obrazu",
            reason="CI",
            files=["ci.yml"],
        ),
        pi.RiskFactor(
            level="HIGH",
            area="Ryzykowne wzorce w diffie",
            reason="Smells",
            files=[],
        ),
    ]
    questions = pi.generate_reviewer_questions(risks, has_prod_without_tests=True)
    assert len(questions) > 0
    assert any("nftables" in q for q in questions)
    assert any("ci/guard.sh" in q for q in questions)
    assert any("bez zmian w testach" in q for q in questions)
    assert any("fiksturą testową" in q for q in questions)


def test_inspect_pr_and_render_markdown() -> None:
    """Weryfikuje pełny przepływ inspekcji i renderowania raportu Markdown."""
    numstat_text = """
25\t5\tansible/roles/lab_config/files/nftables.conf
40\t0\ttests/unit/test_lab_config.py
5\t0\tCHANGELOG.md
"""
    diff_text = """
diff --git a/CHANGELOG.md b/CHANGELOG.md
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -10,4 +10,5 @@
 ## Niewydane

+- **Wpis:** opis.
diff --git a/ansible/roles/lab_config/files/nftables.conf b/ansible/roles/lab_config/files/nftables.conf
--- a/ansible/roles/lab_config/files/nftables.conf
+++ b/ansible/roles/lab_config/files/nftables.conf
@@ -1,1 +1,1 @@
+table inet filter {}
"""
    report = pi.inspect_pr(
        base="origin/main",
        head="HEAD",
        numstat_text=numstat_text,
        diff_text=diff_text,
    )

    assert report.total_files == 3
    assert report.total_insertions == 70
    assert report.total_deletions == 5
    assert report.size_category == "S"
    assert report.overall_risk == "HIGH"
    assert report.has_tests is True
    assert report.has_changelog is True
    assert report.uncovered_prod == []

    md = pi.render_markdown_report(report)
    assert "## 🔍 Automatyczna Karta PR (Pre-Review Inspector)" in md
    assert "`S` — Mały" in md
    assert "🔴 `HIGH`" in md
    assert "CHANGELOG zaktualizowany" in md
    assert "Bezpieczeństwo, sieć i izolacja" in md


def test_inspect_pr_rejects_empty_numstat() -> None:
    """Pusty diff nie może udawać poprawnego raportu XS/LOW."""
    with pytest.raises(pi.PRInspectionError, match="pusty wynik"):
        pi.inspect_pr(base="origin/main", head="HEAD", numstat_text="", diff_text="")


def test_cli_inspect_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Weryfikuje wywołanie CLI inspect wraz z zapisem JSON i GITHUB_STEP_SUMMARY."""
    out_json = tmp_path / "report.json"
    summary_file = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    fake_report = pi.PRInspectionReport(
        base_ref="origin/main",
        head_ref="HEAD",
        total_files=2,
        total_insertions=50,
        total_deletions=10,
        size_category="S",
        size_description="Mały",
        has_prod_code=True,
        has_tests=True,
        has_docs=False,
        has_changelog=True,
        test_assessment="✅ Testy obecne",
        changelog_assessment="✅ CHANGELOG obecny",
        overall_risk="MEDIUM",
        risks=[pi.RiskFactor("MEDIUM", "CI", "Pipeline zmiana", ["ci.yml"])],
        smells=[],
        reviewer_questions=["Czy zadania działają pod guard.sh?"],
    )
    monkeypatch.setattr(pi, "resolve_base_ref", lambda ref, cwd: "origin/main")
    monkeypatch.setattr(pi, "inspect_pr", lambda base, head: fake_report)

    rc = pi.main(["inspect", "--base", "origin/main", "--output", str(out_json), "--summary"])
    assert rc == 0
    assert out_json.exists()
    assert summary_file.exists()

    saved_data = json.loads(out_json.read_text(encoding="utf-8"))
    assert saved_data["total_files"] == 2
    assert saved_data["size_category"] == "S"

    stdout = capsys.readouterr().out
    assert "Automatyczna Karta PR" in stdout


def test_cli_invalid_base_returns_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Błąd rozwiązania refu bazowego musi być błędem CLI, nie pustą kartą."""

    def fail(ref: str, cwd: Path) -> str:
        raise pi.PRInspectionError("Nie znaleziono gałęzi bazowej")

    monkeypatch.setattr(pi, "resolve_base_ref", fail)
    rc = pi.main(["inspect", "--base", "no-such-base"])
    assert rc == 2
    assert "BŁĄD inspekcji PR" in capsys.readouterr().err


def test_cli_output_error_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nieudany zapis --output nie może kończyć się rc 0."""
    fake_report = pi.PRInspectionReport(
        base_ref="origin/main",
        head_ref="HEAD",
        total_files=1,
        total_insertions=1,
        total_deletions=0,
        size_category="XS",
        size_description="Bardzo mały",
        has_prod_code=False,
        has_tests=False,
        has_docs=True,
        has_changelog=False,
        test_assessment="ℹ️ docs",
        changelog_assessment="ℹ️ docs",
        overall_risk="LOW",
    )
    out_dir = tmp_path / "report-dir"
    out_dir.mkdir()
    monkeypatch.setattr(pi, "resolve_base_ref", lambda ref, cwd: "origin/main")
    monkeypatch.setattr(pi, "inspect_pr", lambda base, head: fake_report)

    rc = pi.main(["inspect", "--base", "origin/main", "--output", str(out_dir)])
    assert rc == 2
    assert "BŁĄD zapisu" in capsys.readouterr().err


def test_render_markdown_escapes_table_cells() -> None:
    """Pionowa kreska i newline w danych nie mogą rozbić tabeli Markdown."""
    report = pi.PRInspectionReport(
        base_ref="origin/main",
        head_ref="HEAD",
        total_files=1,
        total_insertions=10,
        total_deletions=0,
        size_category="XS",
        size_description="Bardzo mały",
        has_prod_code=True,
        has_tests=True,
        has_docs=False,
        has_changelog=True,
        test_assessment="✅ Testy",
        changelog_assessment="✅ Wpis",
        overall_risk="MEDIUM",
        risks=[
            pi.RiskFactor(
                "MEDIUM",
                "CI | pipeline",
                "Powód z | kreską\noraz newline",
                ["ci/foo|bar.sh"],
            )
        ],
        smells=["ci/foo|bar.sh: chmod 777"],
        reviewer_questions=["Czy plik ci/foo|bar.sh jest poprawny?"],
    )
    md = pi.render_markdown_report(report)
    assert r"ci/foo\|bar.sh" in md
    assert "CI \\| pipeline" in md
    assert "Powód z \\| kreską oraz newline" in md
    assert "ci/foo\\|bar.sh: chmod 777" in md


def test_run_git_diff_wraps_git_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Błąd gita nie może być zamieniony na pusty string."""

    def fail(*args: object, **kwargs: object) -> None:
        raise pi.subprocess.CalledProcessError(128, ["git"], stderr="fatal: bad revision")

    monkeypatch.setattr(pi.subprocess, "run", fail)
    with pytest.raises(pi.PRInspectionError, match="fatal: bad revision"):
        pi._run_git_diff(["--numstat", "base...HEAD"], Path("."))


def test_run_git_diff_wraps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout gita również jest błędem inspekcji, nie pustym diffem."""

    def fail(*args: object, **kwargs: object) -> None:
        raise pi.subprocess.TimeoutExpired(["git"], 60)

    monkeypatch.setattr(pi.subprocess, "run", fail)
    with pytest.raises(pi.PRInspectionError, match="git diff nie powiódł się"):
        pi._run_git_diff(["--numstat", "base...HEAD"], Path("."))


def test_git_diff_numstat_falls_back_to_two_dot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Po nieudanym three-dot próbujemy base..head, a nie zwracamy pustki."""
    calls: list[list[str]] = []

    def fake(args: list[str], cwd: Path) -> str:
        calls.append(args)
        if len(calls) == 1:
            raise pi.PRInspectionError("three-dot failed")
        return "1\t0\tfile.sh\n"

    monkeypatch.setattr(pi, "_run_git_diff", fake)
    assert pi.get_git_diff_numstat("origin/main", "HEAD", Path(".")) == "1\t0\tfile.sh\n"
    assert calls[0] == ["--numstat", "origin/main...HEAD"]
    assert calls[1] == ["--numstat", "origin/main..HEAD"]


def test_git_diff_text_falls_back_to_two_dot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Analogiczny fallback dla pełnego tekstu diffu."""
    calls: list[list[str]] = []

    def fake(args: list[str], cwd: Path) -> str:
        calls.append(args)
        if len(calls) == 1:
            raise pi.PRInspectionError("three-dot failed")
        return "diff --git a/x b/x\n"

    monkeypatch.setattr(pi, "_run_git_diff", fake)
    assert pi.get_git_diff_text("origin/main", "HEAD", Path(".")).startswith("diff --git")
    assert calls[1] == ["origin/main..HEAD"]


class _FakeGitResult:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_resolve_base_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rozwiązuje lokalny ref albo origin/ref; nieistniejący ref jest błędem."""
    monkeypatch.setattr(pi.subprocess, "run", lambda *args, **kwargs: _FakeGitResult(0))
    assert pi.resolve_base_ref("main", Path(".")) == "main"

    monkeypatch.setattr(pi.subprocess, "run", lambda *args, **kwargs: _FakeGitResult(1))
    with pytest.raises(pi.PRInspectionError, match="Nie znaleziono gałęzi bazowej"):
        pi.resolve_base_ref("no-such", Path("."))


def test_cli_summary_error_returns_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nieudany zapis GITHUB_STEP_SUMMARY też jest błędem CLI."""
    fake_report = pi.PRInspectionReport(
        base_ref="origin/main",
        head_ref="HEAD",
        total_files=1,
        total_insertions=1,
        total_deletions=0,
        size_category="XS",
        size_description="Bardzo mały",
        has_prod_code=False,
        has_tests=False,
        has_docs=True,
        has_changelog=False,
        test_assessment="ℹ️ docs",
        changelog_assessment="ℹ️ docs",
        overall_risk="LOW",
    )
    summary_dir = tmp_path / "summary-dir"
    summary_dir.mkdir()
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_dir))
    monkeypatch.setattr(pi, "resolve_base_ref", lambda ref, cwd: "origin/main")
    monkeypatch.setattr(pi, "inspect_pr", lambda base, head: fake_report)

    rc = pi.main(["inspect", "--base", "origin/main"])
    assert rc == 2
    assert "BŁĄD zapisu GITHUB_STEP_SUMMARY" in capsys.readouterr().err
