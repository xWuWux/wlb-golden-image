"""Kontrakt workflow publikacji SARIF w GitHub Code scanning (#257).

Pilnuje decyzji z zgłoszenia: zapis security-events tylko w jobie publikującym, który nie wykonuje kodu
z repozytorium; dwa jawne raporty ze stałymi kategoriami; publikacja także po znaleziskach; job wliczony
do bramki "Gotowe do code review".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sarif_report
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
JOBS = CI["jobs"]
SCAN = JOBS["security"]
PUBLISH = JOBS["security-report"]
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _steps(job: dict, uses: str) -> list[dict]:
    return [s for s in job["steps"] if s.get("uses", "").startswith(uses)]


# --- uprawnienia: zapis security-events wyłącznie w jobie publikującym (#257) ---
def test_security_events_write_only_in_publishing_job_257() -> None:
    assert CI["permissions"] == {"contents": "read"}
    holders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "security-events" not in (workflow.get("permissions") or {}), path.name
        for name, job in workflow["jobs"].items():
            if "security-events" in (job.get("permissions") or {}):
                holders.append((path.name, name))
    assert holders == [("ci.yml", "security-report")]
    assert PUBLISH["permissions"] == {"actions": "read", "contents": "read", "security-events": "write"}


def test_scanning_job_stays_read_only_257() -> None:
    # job wykonujący kod PR i instalujący narzędzia dziedziczy contents: read
    assert "permissions" not in SCAN


def test_ci_has_no_privileged_triggers_257() -> None:
    triggers = CI.get("on", CI.get(True))
    assert "pull_request_target" not in triggers
    assert "workflow_run" not in triggers


# --- job publikujący nie wykonuje kodu z repozytorium (#257) ---
def test_publishing_job_runs_no_repository_code_257() -> None:
    for step in PUBLISH["steps"]:
        assert "continue-on-error" not in step, step
        if "uses" in step:
            assert PINNED.match(step["uses"]), f"akcja nieprzypięta do pełnego SHA: {step['uses']}"
            assert not step["uses"].startswith("./"), "lokalna akcja w jobie z zapisem"
        else:
            script = step["run"]
            assert not re.search(r"(^|\s)(\./|ci/|tests/|python|pip|make|bash\s)", script), step["name"]
    (checkout,) = _steps(PUBLISH, "actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False


def test_publishing_job_downloads_only_expected_artifact_257() -> None:
    (download,) = _steps(PUBLISH, "actions/download-artifact@")
    assert download["with"]["name"] == "code-scanning-sarif"
    (upload,) = [s for s in _steps(SCAN, "actions/upload-artifact@") if s["with"]["name"] == "code-scanning-sarif"]
    paths = sorted(upload["with"]["path"].split())
    expected = sorted(f"build/code-scanning/{r.sarif}" for r in sarif_report.REPORTS.values())
    assert paths == sorted([*expected, "build/code-scanning/manifest.json"])
    assert upload["with"]["if-no-files-found"] == "error"


# --- dwa raporty, stałe kategorie, publikacja także po znaleziskach (#257) ---
def test_one_upload_per_tool_with_fixed_category_257() -> None:
    uploads = _steps(PUBLISH, "github/codeql-action/upload-sarif@")
    by_category = {s["with"]["category"]: s for s in uploads}
    assert sorted(by_category) == sorted(r.category for r in sarif_report.REPORTS.values())
    assert len(uploads) == len(sarif_report.REPORTS)
    for tool, report in sarif_report.REPORTS.items():
        step = by_category[report.category]
        assert step["id"] == tool
        assert step["with"]["sarif_file"].endswith(f"/code-scanning/{report.sarif}")
        assert step["with"]["wait-for-processing"] is True
        # próba publikacji także po nieudanym uploadzie poprzedniego narzędzia
        assert "!cancelled()" in step["if"]
        # tylko poprawny raport z wynikiem skanu clean/findings — nigdy pusty zamiennik
        assert f"needs.security.outputs.{tool} == 'clean'" in step["if"]
        assert f"needs.security.outputs.{tool} == 'findings'" in step["if"]
        assert SCAN["outputs"][tool] == f"${{{{ steps.sarif.outputs.{tool} }}}}"


def test_publication_runs_after_findings_but_not_after_cancel_257() -> None:
    assert PUBLISH["needs"] == "security"
    assert "!cancelled()" in PUBLISH["if"]
    assert "needs.security.result == 'failure'" in PUBLISH["if"]
    assert "needs.security.result == 'success'" in PUBLISH["if"]
    (prepare,) = [s for s in SCAN["steps"] if s.get("id") == "sarif"]
    assert "!cancelled()" in prepare["if"]
    assert "ci/sarif_report.py prepare" in prepare["run"]


def test_merge_queue_is_named_unsupported_context_257() -> None:
    (context,) = [s for s in PUBLISH["steps"] if s.get("id") == "context"]
    assert "merge_group" in context["run"]
    (state,) = [s for s in PUBLISH["steps"] if s.get("name") == "Stan publikacji"]
    assert state["if"] == "always()"


def test_ready_gate_includes_publication_257() -> None:
    assert "security-report" in JOBS["ready"]["needs"]


@pytest.mark.parametrize("tool", sorted(sarif_report.REPORTS))
def test_security_script_records_scanner_status_257(tool: str) -> None:
    script = (ROOT / "ci" / "security.sh").read_text(encoding="utf-8")
    assert f"scan_with_status build/sca {tool} {tool} " in script
    assert f"build/sca/{sarif_report.REPORTS[tool].sarif}" in script
