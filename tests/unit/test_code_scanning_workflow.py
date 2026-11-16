"""Kontrakt workflow publikacji SARIF w GitHub Code scanning (#257).

Pilnuje decyzji z zgłoszenia: zapis security-events tylko w jobie publikującym, który nie wykonuje kodu
z repozytorium; dwa jawne raporty ze stałymi kategoriami; publikacja także po znaleziskach; job wliczony
do bramki "Gotowe do code review".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
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
RUN_STEPS = {"context", "manifest", "confirm", "state"}  # jedyne dozwolone kroki run: w jobie z zapisem


def test_publishing_job_runs_no_repository_code_257() -> None:
    for step in PUBLISH["steps"]:
        assert "continue-on-error" not in step, step
        if "uses" in step:
            assert PINNED.match(step["uses"]), f"akcja nieprzypięta do pełnego SHA: {step['uses']}"
            assert not step["uses"].startswith("./"), "lokalna akcja w jobie z zapisem"
        else:
            # allowlista, nie czarna lista: każdy nowy krok run: wymaga świadomej zmiany testu
            assert step.get("id") in RUN_STEPS, step.get("name")
            forbidden = r"(^|[\s;|&(])(\./|ci/|tests/|(python3?|pip3?|make|node|npm)\b|sh\s|bash\s|source\s|\.\s)"
            assert not re.search(forbidden, step["run"]), step["name"]
    assert {s.get("id") for s in PUBLISH["steps"] if "run" in s} == RUN_STEPS
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


# --- konteksty zdarzeń i stan publikacji: wykonanie kroków run: joba 3r (#257) ---
def _run_step(step_id: str, tmp_path: Path, env: dict[str, str]) -> tuple[int, str, dict[str, str], str]:
    (step,) = [s for s in PUBLISH["steps"] if s.get("id") == step_id]
    assert "${{" not in step["run"], "dane wejściowe tylko przez env, nie przez interpolację wyrażeń"
    output, summary = tmp_path / "output", tmp_path / "summary"
    output.touch()
    summary.touch()
    full_env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary), **env}
    process = subprocess.run(  # noqa: S603 - skrypt z workflow, bez wejścia użytkownika
        ["/bin/bash", "-e", "-c", step["run"]],  # domyślny shell kroku w Actions: bash -e {0}
        env=full_env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line)
    return process.returncode, process.stdout + process.stderr, outputs, summary.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("event", "actor", "head_author", "supported"),
    [
        ("pull_request", "lukasz", "", "true"),
        ("pull_request", "dependabot[bot]", "", "true"),  # GitHub przyjmuje upload z pull_request
        ("push", "lukasz", "lukasz", "true"),
        ("schedule", "lukasz", "", "true"),
        ("workflow_dispatch", "lukasz", "", "true"),
        ("merge_group", "lukasz", "", "false"),
        ("push", "dependabot[bot]", "dependabot[bot]", "false"),
        ("push", "lukasz", "dependabot[bot]", "false"),  # squash-merge PR Dependabota
    ],
)
def test_publication_context_per_event_257(
    tmp_path: Path, event: str, actor: str, head_author: str, supported: str
) -> None:
    code, log, outputs, _ = _run_step("context", tmp_path, {"EVENT": event, "ACTOR": actor, "HEAD_AUTHOR": head_author})
    assert code == 0, log
    assert outputs["supported"] == supported
    # kontekst bez publikacji zawsze ma jawny powód
    assert bool(outputs["reason"]) is (supported == "false")


# jq jest na runnerze GitHub i w kontenerze etapu 4; lokalnie bez jq test jest pomijany, w CI nigdy
@pytest.mark.skipif(shutil.which("jq") is None and not os.environ.get("CI"), reason="brak jq (lokalnie)")
def test_manifest_must_match_run_257(tmp_path: Path) -> None:
    directory = tmp_path / "code-scanning"
    directory.mkdir()
    manifest = directory / "manifest.json"
    env = {"DIR": str(directory), "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "77"}
    sarif = directory / "semgrep.sarif"
    sarif.write_bytes(b'{"version":"2.1.0"}')
    digest = hashlib.sha256(sarif.read_bytes()).hexdigest()

    def write(run: dict, reports: list[dict]) -> None:
        manifest.write_text(json.dumps({"run": run, "reports": reports}), encoding="utf-8")

    ok_run = {"sha": "a" * 40, "run_id": "77", "run_attempt": "1"}
    reports = [
        {"tool": "semgrep", "publish": True, "sha256": digest},
        {"tool": "checkov", "publish": False},
    ]
    write(ok_run, reports)
    assert _run_step("manifest", tmp_path, env)[0] == 0
    # inna próba tego samego przebiegu (Re-run failed jobs) jest poprawna
    write({**ok_run, "run_attempt": "2"}, reports)
    assert _run_step("manifest", tmp_path, env)[0] == 0

    write({**ok_run, "sha": "b" * 40}, reports)
    code, log, _, _ = _run_step("manifest", tmp_path, env)
    assert code == 1
    assert "nie pasuje do przebiegu" in log
    write({**ok_run, "run_id": "76"}, reports)
    assert _run_step("manifest", tmp_path, env)[0] == 1

    # podmieniony plik raportu, brak skrótu albo brak pliku do publikacji
    write(ok_run, [{"tool": "semgrep", "publish": True, "sha256": "0" * 64}, reports[1]])
    code, log, _, _ = _run_step("manifest", tmp_path, env)
    assert code == 1
    assert "skrót raportu semgrep" in log
    write(ok_run, [{"tool": "semgrep", "publish": True}, reports[1]])
    assert _run_step("manifest", tmp_path, env)[0] == 1
    write(ok_run, [reports[0], {"tool": "checkov", "publish": True, "sha256": digest}])
    assert _run_step("manifest", tmp_path, env)[0] == 1

    manifest.unlink()
    assert _run_step("manifest", tmp_path, env)[0] == 1


@pytest.mark.parametrize(
    ("env", "expected_code", "expected"),
    [
        # upload-sarif zielony, ale GitHub nie potwierdził przetworzenia (timeout akcji = tylko ostrzeżenie)
        (
            {
                "SUPPORTED": "true",
                "SEMGREP_SCAN": "clean",
                "SEMGREP_UPLOAD": "success",
                "SEMGREP_CONFIRM": "pending",
                "CHECKOV_SCAN": "clean",
                "CHECKOV_UPLOAD": "success",
                "CHECKOV_CONFIRM": "complete",
            },
            1,
            ["| semgrep | clean | pending — brak terminalnego statusu przetwarzania w terminie |"],
        ),
        (
            {
                "SUPPORTED": "true",
                "SEMGREP_SCAN": "clean",
                "SEMGREP_UPLOAD": "success",
                "SEMGREP_CONFIRM": "failed",
                "CHECKOV_SCAN": "clean",
                "CHECKOV_UPLOAD": "success",
            },
            1,
            ["(status: failed)", "| checkov | clean | failed — przetwarzanie niepotwierdzone (status: none) |"],
        ),
        (
            {
                "SUPPORTED": "true",
                "SEMGREP_SCAN": "findings",
                "SEMGREP_UPLOAD": "success",
                "SEMGREP_CONFIRM": "complete",
                "CHECKOV_SCAN": "clean",
                "CHECKOV_UPLOAD": "success",
                "CHECKOV_CONFIRM": "complete",
            },
            0,
            ["| semgrep | findings | processed |", "| checkov | clean | processed |"],
        ),
        ({"SUPPORTED": "false", "REASON": "merge queue"}, 0, ["unsupported — merge queue"]),
        # brak powodu = nieznany kontekst, nie cichy sukces
        ({"SUPPORTED": "false"}, 1, ["unsupported — nieznany kontekst"]),
        # krok kontekstu nie zadziałał
        ({}, 1, ["unsupported — nieznany kontekst"]),
        (
            {
                "SUPPORTED": "true",
                "SEMGREP_SCAN": "error",
                "SEMGREP_UPLOAD": "skipped",
                "CHECKOV_SCAN": "clean",
                "CHECKOV_UPLOAD": "success",
                "CHECKOV_CONFIRM": "complete",
            },
            1,
            ["brak poprawnego raportu (error)"],
        ),
        (
            {
                "SUPPORTED": "true",
                "SEMGREP_SCAN": "clean",
                "SEMGREP_UPLOAD": "success",
                "SEMGREP_CONFIRM": "complete",
                "CHECKOV_SCAN": "not_run",
                "CHECKOV_UPLOAD": "skipped",
            },
            1,
            ["brak poprawnego raportu (not_run)"],
        ),
        (
            {
                "SUPPORTED": "true",
                "SEMGREP_SCAN": "clean",
                "SEMGREP_UPLOAD": "failure",
                "CHECKOV_SCAN": "clean",
                "CHECKOV_UPLOAD": "success",
                "CHECKOV_CONFIRM": "complete",
            },
            1,
            ["upload/przetwarzanie: failure", "| checkov | clean | processed |"],
        ),
        (
            {
                "SUPPORTED": "true",
                "SEMGREP_SCAN": "clean",
                "SEMGREP_UPLOAD": "cancelled",
                "CHECKOV_SCAN": "clean",
                "CHECKOV_UPLOAD": "success",
                "CHECKOV_CONFIRM": "complete",
            },
            1,
            ["| semgrep | clean | cancelled |"],
        ),
        # manifest odrzucony -> upload pominięty mimo poprawnego skanu
        ({"SUPPORTED": "true", "SEMGREP_SCAN": "clean", "CHECKOV_SCAN": "clean"}, 1, ["upload/przetwarzanie: skipped"]),
    ],
)
def test_publication_state_257(tmp_path: Path, env: dict[str, str], expected_code: int, expected: list[str]) -> None:
    code, log, _, summary = _run_step("state", tmp_path, env)
    assert code == expected_code, log
    for fragment in expected:
        assert fragment in summary


# --- potwierdzenie terminalnego statusu sarif-id (#257, review PR #324) ---
def _fake_api(tmp_path: Path, statuses: dict[str, list[str]]) -> dict[str, str]:
    """Atrapa curl: kolejne odpowiedzi API /code-scanning/sarifs/<id> z listy statusów danego id."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for sarif_id, sequence in statuses.items():
        (tmp_path / f"seq-{sarif_id}").write_text("\n".join(sequence) + "\n", encoding="utf-8")
    curl = stubs / "curl"
    # atrapa rozumie -o PLIK i -w '%{http_code}': wpis "complete" = 200 z tym statusem, "http403" = kod 403
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "out=/dev/null; while (($#)); do case $1 in -o) out=$2; shift 2 ;; *) url=$1; shift ;; esac; done\n"
        'id=${url##*/}; seq="$SEQ_DIR/seq-$id"\n'
        'echo "$url" >>"$SEQ_DIR/calls"\n'
        "[[ -s $seq ]] || { printf 000; exit 7; }\n"
        'entry=$(head -n1 "$seq"); [[ $(wc -l <"$seq") -gt 1 ]] && sed -i 1d "$seq"\n'
        'if [[ $entry == http* ]]; then printf "%s" "${entry#http}"; exit 0; fi\n'
        'printf \'{"processing_status": "%s"}\\n\' "$entry" >"$out"; printf 200\n',
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return {
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "SEQ_DIR": str(tmp_path),
        "GH_TOKEN": "t",
        "REPO": "o/r",
        "CONFIRM_INTERVAL": "0",
    }


@pytest.mark.skipif(shutil.which("jq") is None and not os.environ.get("CI"), reason="brak jq (lokalnie)")
@pytest.mark.parametrize(
    ("sequence", "timeout", "expected"),
    [
        (["complete"], "30", "complete"),
        (["pending", "pending", "complete"], "30", "complete"),
        (["failed"], "30", "failed"),
        # pending po terminie zostaje pending (Stan publikacji zrobi z tego błąd)
        (["pending"], "0", "pending"),
        # chwilowe błędy API i opóźniona widoczność uploadu, potem wynik
        (["http500", "http429", "http404", "complete"], "30", "complete"),
        # brak uprawnień do odczytu (np. fork) nie jest complete i nie jest ponawiany
        (["http403", "complete"], "30", "forbidden"),
        (["http401"], "30", "forbidden"),
        (["http418"], "30", "http_418"),
        # usługa niedostępna do końca terminu
        (["http503"], "0", "unavailable"),
    ],
)
def test_confirm_processing_status_257(tmp_path: Path, sequence: list[str], timeout: str, expected: str) -> None:
    env = _fake_api(tmp_path, {"11": sequence})
    env.update({"SEMGREP_ID": "11", "CHECKOV_ID": "", "CONFIRM_TIMEOUT": timeout})
    code, log, outputs, _ = _run_step("confirm", tmp_path, env)
    assert code == 0, log
    assert outputs == {"semgrep": expected, "checkov": "none"}
    calls = (tmp_path / "calls").read_text(encoding="utf-8")
    assert "https://api.github.com/repos/o/r/code-scanning/sarifs/11" in calls


# --- zakres ochrony eksportu: logi i surowe artefakty (#257, review PR #324) ---
def test_raw_sarif_never_leaves_runner_257() -> None:
    (reports,) = [s for s in _steps(SCAN, "actions/upload-artifact@") if s["with"]["name"] == "security-reports"]
    paths = reports["with"]["path"].split()
    assert "!build/sca/**/*.sarif" in paths  # także raporty kontraktu w podkatalogach
    for job_name, job in JOBS.items():
        for step in _steps(job, "actions/upload-artifact@"):
            if step["with"]["name"] == "code-scanning-sarif":
                continue
            assert "semgrep.sarif" not in step["with"]["path"], job_name
            assert "checkov.sarif" not in step["with"]["path"], job_name


def test_scanner_logs_without_code_fragments_257() -> None:
    script = (ROOT / "ci" / "security.sh").read_text(encoding="utf-8")
    # tekstowe wyjście semgrepa (dopasowane linie kodu) nie trafia do publicznego logu
    assert "--sarif-output=build/sca/semgrep.sarif . >/dev/null" in script
    # bandit: tylko plik:linia i id testu, bez fragmentu kodu i komunikatu z wartością
    assert '--msg-template "{relpath}:{line} {test_id} {severity}/{confidence}"' in script
    # checkov: tryb bez bloków kodu
    assert "--compact" in script


def test_contract_fixture_excluded_from_main_scans_257() -> None:
    script = (ROOT / "ci" / "security.sh").read_text(encoding="utf-8")
    assert "CONTRACT=tests/fixtures/sarif-contract" in script
    assert '--exclude "$CONTRACT"' in script
    assert '--skip-path "$CONTRACT"' in script
    assert 'run_check "Kontrakt SARIF na przypiętych skanerach (#257)" sarif_contract' in script
    fixture = ROOT / "tests" / "fixtures" / "sarif-contract"
    assert (fixture / "leak.py").is_file()
    assert (fixture / ".github" / "workflows" / "w.yml").is_file()
