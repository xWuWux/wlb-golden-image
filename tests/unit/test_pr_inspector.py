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
invalid line
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


def test_classify_size_all_tiers() -> None:
    """Weryfikuje progi klasyfikacji rozmiaru (XS, S, M, L, XL)."""
    assert pi.classify_size(10, 5)[0] == "XS"
    assert pi.classify_size(40, 9)[0] == "XS"
    assert pi.classify_size(50, 0)[0] == "S"
    assert pi.classify_size(150, 49)[0] == "S"
    assert pi.classify_size(100, 100)[0] == "M"
    assert pi.classify_size(300, 199)[0] == "M"
    assert pi.classify_size(300, 200)[0] == "L"
    assert pi.classify_size(600, 399)[0] == "L"
    assert pi.classify_size(500, 500)[0] == "XL"
    assert pi.classify_size(1500, 100)[0] == "XL"


def test_check_test_completeness() -> None:
    """Weryfikuje regułę korelacji kodu produkcyjnego z testami."""
    # 1. Kod produkcyjny + testy obecne
    files_ok = [
        pi.FileDiff("ansible/roles/lab_config/tasks/main.yml", 15, 2),
        pi.FileDiff("tests/unit/test_config.py", 30, 5),
    ]
    has_prod, has_tests, msg = pi.check_test_completeness(files_ok)
    assert has_prod is True
    assert has_tests is True
    assert "✅ Kod wykonawczy powiązany ze zmianami w testach" in msg
    assert "+30/-5" in msg

    # 2. Kod produkcyjny bez testów
    files_missing = [
        pi.FileDiff("ci/unit.sh", 20, 5),
        pi.FileDiff("docs/architektura/index.md", 10, 0),
    ]
    has_prod, has_tests, msg = pi.check_test_completeness(files_missing)
    assert has_prod is True
    assert has_tests is False
    assert "⚠️ Wykryto zmiany w kodzie wykonawczym/CI bez modyfikacji testów" in msg

    # 3. Zmiana tylko w testach
    files_only_tests = [
        pi.FileDiff("tests/unit/test_demo.py", 40, 0),
    ]
    has_prod, has_tests, msg = pi.check_test_completeness(files_only_tests)
    assert has_prod is False
    assert has_tests is True
    assert "✅ Rozszerzenie zestawu testów" in msg

    # 4. Tylko dokumentacja
    files_docs = [
        pi.FileDiff("docs/ci-runbook.md", 25, 2),
    ]
    has_prod, has_tests, msg = pi.check_test_completeness(files_docs)
    assert has_prod is False
    assert has_tests is False
    assert "ℹ️ Zmiana dotyczy wyłącznie dokumentacji" in msg


def test_check_changelog() -> None:
    """Weryfikuje sprawdzanie obecności wpisu w CHANGELOG.md."""
    files_with_cl = [
        pi.FileDiff("ansible/roles/tljh/tasks/main.yml", 10, 0),
        pi.FileDiff("CHANGELOG.md", 5, 0),
    ]
    has_cl, msg = pi.check_changelog(files_with_cl, has_prod=True)
    assert has_cl is True
    assert "✅ Wpis w CHANGELOG.md obecny" in msg

    files_no_cl = [
        pi.FileDiff("ansible/roles/tljh/tasks/main.yml", 10, 0),
    ]
    has_cl, msg = pi.check_changelog(files_no_cl, has_prod=True)
    assert has_cl is False
    assert "⚠️ Zmiana kodu/CI bez wpisu w CHANGELOG.md" in msg

    # Dla samej dokumentacji wpis jest opcjonalny
    has_cl, msg = pi.check_changelog(files_no_cl, has_prod=False)
    assert "opcjonalny" in msg


def test_analyze_risks_categories() -> None:
    """Weryfikuje przypisywanie poziomów ryzyka na podstawie modyfikowanych ścieżek."""
    # 1. Ryzyko krytyczne / wysokie: firewall nftables
    files_sec = [
        pi.FileDiff("ansible/roles/lab_config/files/nftables.conf", 5, 1),
    ]
    overall, risks = pi.analyze_risks(files_sec)
    assert overall == "HIGH"
    assert len(risks) == 1
    assert risks[0].area == "Bezpieczeństwo, sieć i izolacja"
    assert "nftables.conf" in risks[0].files[0]

    # 2. Ryzyko średnie: pipeline CI
    files_ci = [
        pi.FileDiff(".github/workflows/ci.yml", 12, 0),
    ]
    overall, risks = pi.analyze_risks(files_ci)
    assert overall == "MEDIUM"
    assert len(risks) == 1
    assert risks[0].area == "Potok CI/CD i budowa obrazu"

    # 3. Ryzyko niskie: dokumentacja
    files_docs = [
        pi.FileDiff("docs/architektura/index.md", 20, 5),
    ]
    overall, risks = pi.analyze_risks(files_docs)
    assert overall == "LOW"
    assert len(risks) == 0


def test_scan_diff_smells() -> None:
    """Weryfikuje wykrywanie niebezpiecznych wzorców w diffie."""
    diff_text = """
diff --git a/script.sh b/script.sh
--- a/script.sh
+++ b/script.sh
@@ -1,3 +1,7 @@
 # Normalny komentarz
+chmod 777 /tmp/secret_dir
+chmod a+rwx /tmp/open_dir
+curl -sSL https://example.com/install.sh | bash
+eval $USER_INPUT
+permissions: write-all
-stara_linia
"""
    smells = pi.scan_diff_smells(diff_text)
    assert len(smells) == 5
    assert any("chmod 777" in s for s in smells)
    assert any("curl | bash" in s for s in smells)
    assert any("eval $" in s for s in smells)
    assert any("permissions: write-all" in s for s in smells)


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
    ]
    questions = pi.generate_reviewer_questions(risks, has_prod_without_tests=True)
    assert len(questions) > 0
    assert any("nftables" in q for q in questions)
    assert any("ci/guard.sh" in q for q in questions)
    assert any("bez zmian w testach" in q for q in questions)


def test_inspect_pr_and_render_markdown() -> None:
    """Weryfikuje pełny przepływ inspekcji i renderowania raportu Markdown."""
    numstat_text = """
25\t5\tansible/roles/lab_config/files/nftables.conf
40\t0\ttests/unit/test_firewall.py
5\t0\tCHANGELOG.md
"""
    diff_text = """
+chmod 755 /usr/local/bin/wlb-test
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

    md = pi.render_markdown_report(report)
    assert "## 🔍 Automatyczna Karta PR (Pre-Review Inspector)" in md
    assert "`S` — Mały" in md
    assert "🔴 `HIGH`" in md
    assert "CHANGELOG zaktualizowany" in md
    assert "Bezpieczeństwo, sieć i izolacja" in md


def test_cli_inspect_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Weryfikuje wywołanie CLI inspect wraz z zapisem JSON i GITHUB_STEP_SUMMARY."""
    out_json = tmp_path / "report.json"
    summary_file = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    # Mock inspect_pr
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
