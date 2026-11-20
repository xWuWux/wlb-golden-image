"""Regresje bramki mutant × konsument (#340)."""

from pathlib import Path

import mutation_contracts as mc
import pytest


@pytest.mark.parametrize(
    ("rc", "report", "status"),
    [
        (0, "1..0\n", "no-tests"),
        (0, "1..1\nok 1 a # skip offline\n", "error"),
        (127, "1..1\n", "error"),
        (1, "1..1\nnot ok 1 a\n# crash\n", "error"),
        (1, "1..1\nnot ok 1 a\n# contract:a\n", "killed"),
    ],
)
def test_tap_requires_exact_assertion(rc, report, status):
    assert mc.verdict(rc, report, "a", True) == status


@pytest.mark.parametrize("element", ["<error/>", "<skipped/>", "<failure message='setup failed'/>"])
def test_pytest_infrastructure_failure(element):
    report = f"<testsuite><testcase>{element}</testcase></testsuite>"
    assert mc.verdict(1, report, "a", False) == "error"


def test_survivor_is_independent_and_source_restored(tmp_path: Path):
    (tmp_path / "values.py").write_text("value = 1\n")
    (tmp_path / "test_values.py").write_text(
        "from values import value\n"
        "def test_strict():\n    assert value == 1, 'contract:value'\n"
        "def test_weak():\n    assert value > 0\n"
    )
    group = {
        "source": "values.py",
        "test": "test_values.py",
        "inputs": [],
        "consumers": {"strict": "test_strict", "weak": "test_weak", "absent": "test_missing"},
        "mutations": [["alter", "value = 1", "value = 2", "value"]],
    }
    rows = mc.run_group(tmp_path, "value", group, tmp_path)
    assert [r["status"] for r in rows] == ["killed", "survived", "baseline-no-tests"]
    assert (tmp_path / "values.py").read_text() == "value = 1\n"


def test_reviewed_matrix_has_both_languages_and_all_variants():
    groups = mc.catalog(mc.ROOT)
    assert set(groups["deployment-values"]["consumers"]) == {"env-example", "cloud-init-base", "cloud-init-optional"}
    assert all(set(groups[name]["consumers"]) == {"http", "https"} for name in ("hub-rules", "hub-rollback"))
    assert set(groups["apparmor-switched"]["consumers"]) == {"two-profiles"}
    assert set(groups["snapshot-algorithm-integrity"]["consumers"]) == {"algorithm"}
    for suffix in (".py", ".bats"):
        assert sum(len(g["mutations"]) for g in groups.values() if g["test"].endswith(suffix)) >= 5


def test_junit_rejects_doctype():
    assert mc.verdict(0, "<!DOCTYPE testsuite><testsuite><testcase/></testsuite>", "value", False) == "error"
