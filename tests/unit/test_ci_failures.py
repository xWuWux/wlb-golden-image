"""Diagnoza nieudanych przebiegów CI i decyzja o automatycznym ponowieniu (bez sieci)."""

import pytest

import ci_failures as cf

RUN = {"id": 7, "name": "CI", "run_number": 4, "run_attempt": 1, "conclusion": "failure", "head_branch": "ci/pipeline",
       "head_sha": "abc", "repository": {"full_name": "o/r"}}  # fmt: skip


def job(name, conclusion, steps, check=None):
    return {"name": name, "conclusion": conclusion, "html_url": f"https://x/{name}", "check_run_url": check,
            "steps": [{"name": n, "conclusion": c} for n, c in steps]}  # fmt: skip


# przebieg #4 z PR #1: runner zabity przez OOM osv-scannera — krok "cancelled", job "failure"
INFRA = job("5. Integracja", "failure", [("integration", "success"), ("Podatności", "cancelled")], "https://api/c/1")
TEST = job("2. Build test", "failure", [("checkout", "success"), ("build-check", "failure")], "https://api/c/2")
OOM = job("3. Security", "failure", [("security", "failure")], "https://api/c/3")
GATE = job(cf.GATE_JOB, "failure", [("ready", "failure")], "https://api/c/4")
ANNOTATIONS = {
    "https://api/c/1/annotations": [{"title": None, "message": "The operation was canceled."}],
    "https://api/c/2/annotations": [{"title": "FAIL: 2. Build test", "message": "Kod wyjścia 1"}],
    "https://api/c/3/annotations": [{"title": "OOM: 3. Security", "message": "limit 6G"}],
    "https://api/c/4/annotations": [],
}


class FakeGitHub:
    token = "tok"

    def __init__(self, jobs, run=None, latest="abc"):
        self._jobs, self._run, self.latest, self.posted = jobs, run or RUN, latest, []

    def fetch(self, url, token, data=None, headers=None):
        if data is not None:
            self.posted.append(url)
            return {}
        return ANNOTATIONS.get(url, [])

    def get(self, path):
        assert path == "branches/ci/pipeline"
        return {"commit": {"sha": self.latest}}

    def run(self, run_id):
        return self._run

    def jobs(self, run_id, attempt):
        return self._jobs


@pytest.mark.parametrize(
    "j, annotations, run_conclusion, expected",
    [
        (INFRA, ANNOTATIONS["https://api/c/1/annotations"], "failure", "infra"),
        (TEST, ANNOTATIONS["https://api/c/2/annotations"], "failure", "test"),
        (OOM, ANNOTATIONS["https://api/c/3/annotations"], "failure", "oom"),
        (job("x", "failure", [("a", "failure")]), [{"title": "TIMEOUT: x"}], "failure", "timeout"),
        (job("x", "timed_out", []), [], "failure", "timeout"),
        (job("x", "cancelled", [("a", "cancelled")]), [], "cancelled", "cancelled"),
        (job("x", "cancelled", []), [], "failure", "infra"),
        (
            job("x", "failure", [("a", "success")]),
            [{"message": "runner has received a shutdown signal"}],
            "failure",
            "infra",
        ),
        (job("x", "success", []), [], "failure", None),
        (job("x", "skipped", []), [], "failure", None),
    ],
)
def test_classify_job(j, annotations, run_conclusion, expected):
    assert cf.classify_job(j, annotations, run_conclusion) == expected


def test_diagnoza_pomija_bramke_koncowa():
    rows = cf.diagnose(FakeGitHub([INFRA, GATE]), RUN, [INFRA, GATE])
    assert [(r["job"], r["category"], r["step"]) for r in rows] == [("5. Integracja", "infra", "Podatności")]


@pytest.mark.parametrize(
    "jobs, run, latest, expected",
    [
        ([INFRA], RUN, "abc", (True, "tylko awaria infrastruktury na najnowszym commicie")),
        ([INFRA, TEST], RUN, "abc", (False, "są błędy inne niż awaria infrastruktury (test)")),
        (
            [INFRA],
            {**RUN, "run_attempt": 2},
            "abc",
            (False, "przebieg był już ponawiany — dalej ręcznie według runbooka"),
        ),
        ([INFRA], {**RUN, "conclusion": "cancelled"}, "abc", (False, "przebieg anulowany")),
        ([INFRA], RUN, "nowszy", (False, "gałąź ma nowszy commit — liczy się jego przebieg")),
        ([], RUN, "abc", (False, "brak nieudanych jobów")),
    ],
)
def test_should_retry(jobs, run, latest, expected):
    gh = FakeGitHub(jobs, run, latest)
    assert cf.should_retry(gh, run, cf.diagnose(gh, run, jobs)) == expected


def test_retry_zleca_ponowienie_tylko_dla_infra(capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    gh = FakeGitHub([INFRA, GATE])
    assert cf.main(["retry", "--repo", "o/r", "--run-id", "7"], gh=gh) == 0
    assert gh.posted == [f"{cf.API}/repos/o/r/actions/runs/7/rerun-failed-jobs"]
    out = capsys.readouterr().out
    assert "**Automatyczne ponowienie: TAK**" in out
    assert "https://github.com/o/r/blob/abc/docs/ci-runbook.md#infra" in out

    gh = FakeGitHub([INFRA, TEST])
    cf.main(["retry", "--repo", "o/r", "--run-id", "7"], gh=gh)
    assert gh.posted == []


def test_diagnose_bez_decyzji_i_bez_bledow(capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    cf.main(["diagnose", "--repo", "o/r", "--run-id", "7"], gh=FakeGitHub([TEST]))
    out = capsys.readouterr().out
    assert "Błąd testu lub narzędzia" in out and "Automatyczne ponowienie" not in out
    assert "Brak nieudanych jobów." in cf.report({"id": 1}, [], None)
