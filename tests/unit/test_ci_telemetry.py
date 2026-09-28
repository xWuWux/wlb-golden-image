"""Telemetria CI (OTLP/JSON) na danych w formacie API GitHub Actions — bez sieci."""

import json
import urllib.error

import pytest

import ci_telemetry as ct

REPO = {"full_name": "xWuWux/wlb-golden-image"}


def job(jid, name, conclusion, start, end, created="2026-09-25T10:00:00Z", steps=()):
    return {
        "id": jid,
        "name": name,
        "conclusion": conclusion,
        "created_at": created,
        "started_at": start,
        "completed_at": end,
        "runner_name": "GitHub Actions 1",
        "html_url": f"https://x/{jid}",
        "steps": [
            {"number": i + 1, "name": s, "conclusion": conclusion, "started_at": start, "completed_at": end}
            for i, s in enumerate(steps)
        ],
    }


RUN = {
    "id": 42,
    "name": "CI",
    "run_number": 7,
    "run_attempt": 1,
    "workflow_id": 9,
    "conclusion": "failure",
    "event": "pull_request",
    "head_branch": "ci/pipeline",
    "head_sha": "abc",
    "html_url": "https://x/run",
    "created_at": "2026-09-25T10:00:00Z",
    "run_started_at": "2026-09-25T10:00:00Z",
    "updated_at": "2026-09-25T10:30:00Z",
    "repository": REPO,
}
JOBS = [
    job(1, "1. Lint", "success", "2026-09-25T10:00:05Z", "2026-09-25T10:01:05Z", steps=["checkout", "lint"]),
    job(2, "5. Integracja", "failure", "2026-09-25T10:02:00Z", "2026-09-25T10:29:00Z", steps=["build"]),
    job(3, "6a. Perf", "skipped", "2026-09-25T10:29:00Z", "2026-09-25T10:29:00Z"),
]


def history():
    # ten sam commit: Integracja raz przeszła, raz nie -> niestabilna
    other = {**RUN, "id": 41, "conclusion": "success"}
    return [
        {"run": RUN, "jobs": JOBS},
        {
            "run": other,
            "jobs": [
                job(4, "5. Integracja", "success", "2026-09-25T09:00:00Z", "2026-09-25T09:20:00Z"),
                job(5, "1. Lint", "success", "2026-09-25T09:00:00Z", "2026-09-25T09:00:30Z"),
            ],
        },
    ]


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def run(self, run_id):
        return RUN

    def jobs(self, run_id, attempt):
        self.calls.append(("jobs", run_id, attempt))
        return JOBS

    def history(self, workflow_id, limit):
        self.calls.append(("history", workflow_id, limit))
        return history()


def test_slad_przebieg_joby_kroki():
    body, trace_id = ct.build_traces(RUN, JOBS)
    spans = body["resourceSpans"][0]["scopeSpans"][0]["spans"]
    root, lint, integ = spans[0], spans[1], spans[4]
    assert len(trace_id) == 32 and all(len(s["spanId"]) == 16 for s in spans)
    assert trace_id == ct.build_traces(RUN, JOBS)[1]  # deterministyczny
    assert "parentSpanId" not in root and lint["parentSpanId"] == root["spanId"]
    assert spans[2]["parentSpanId"] == lint["spanId"]  # krok pod jobem
    assert (root["status"]["code"], lint["status"]["code"], integ["status"]["code"]) == (2, 1, 2)
    assert spans[-1]["status"]["code"] == 0  # skipped = UNSET
    attrs = {a["key"]: a["value"] for a in lint["attributes"]}
    assert attrs["cicd.pipeline.task.queue_seconds"] == {"doubleValue": 5.0}


def test_statystyki_i_niestabilnosc():
    stats = ct.job_stats(history())
    assert stats["5. Integracja"]["success_ratio"] == 0.5
    assert stats["5. Integracja"]["flaky_commits"] == 1
    assert stats["1. Lint"]["flaky_commits"] == 0
    assert stats["1. Lint"]["p90"] == 60.0
    assert "6a. Perf" not in stats  # pominięte joby nie liczą się do skuteczności


def test_metryki():
    body = ct.build_metrics(RUN, JOBS, ct.job_stats(history()))
    metrics = {m["name"]: m for m in body["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
    assert set(metrics) == {
        "wlb.ci.run.duration",
        "wlb.ci.job.duration",
        "wlb.ci.job.queue_time",
        "wlb.ci.job.success_ratio",
        "wlb.ci.job.duration_p90",
        "wlb.ci.job.flaky_commits",
    }
    assert metrics["wlb.ci.run.duration"]["gauge"]["dataPoints"][0]["asDouble"] == 1800.0
    assert len(metrics["wlb.ci.job.duration"]["gauge"]["dataPoints"]) == 2  # bez pominiętych
    assert "wlb.ci.job.success_ratio" not in {
        m["name"] for m in ct.build_metrics(RUN, JOBS, {})["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    }


def test_logi_z_korelacja():
    body, jsonl = ct.build_logs(RUN, JOBS, "t" * 32)
    records = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    assert len(records) == len(jsonl) == 6  # 3 joby + 3 kroki
    failed = next(r for r in jsonl if r["job"] == "5. Integracja" and r["step"] is None)
    assert failed["duration_s"] == 1620.0 and failed["trace_id"] == "t" * 32
    assert {r["severityNumber"] for r in records} == {9, 17}


def test_atrybuty_typy():
    out = {a["key"]: a["value"] for a in ct.attrs({"b": True, "i": 3, "f": 1.5, "s": "x", "n": None})}
    assert out == {
        "b": {"boolValue": True},
        "i": {"intValue": "3"},
        "f": {"doubleValue": 1.5},
        "s": {"stringValue": "x"},
    }


def test_export_otlp_naglowki_i_bledy():
    sent, slept = [], []

    def post(url, token, data, headers):
        sent.append((url, headers))
        if url.endswith("/v1/logs"):
            raise OSError("odmowa")

    problems = ct.export_otlp(
        "https://otel:4318/", "Authorization=Bearer x, X-Org = wlb", {"traces": {}, "logs": {}}, post, slept.append
    )
    assert [u for u, _ in sent] == ["https://otel:4318/v1/traces"] + ["https://otel:4318/v1/logs"] * 3
    assert sent[0][1] == {"Content-Type": "application/json", "Authorization": "Bearer x", "X-Org": "wlb"}
    assert problems == ["logs: odmowa (po 3 próbach)"]
    assert slept == [1, 2]


def http_error(code):
    return urllib.error.HTTPError("https://otel:4318/v1/traces", code, "błąd", {}, None)


@pytest.mark.parametrize(
    ("errors", "calls", "problems"),
    [
        ([http_error(503), TimeoutError("timeout")], 3, []),  # przejściowe — trzecia próba udana
        ([http_error(429)], 2, []),
        ([http_error(401)], 1, ["traces: HTTP Error 401: błąd"]),  # zły token — bez ponawiania
        ([ValueError("dozwolone tylko http(s)")], 1, ["traces: dozwolone tylko http(s)"]),
    ],
)
def test_export_otlp_ponawia_tylko_bledy_przejsciowe(errors, calls, problems):
    sent = []

    def post(url, *a):
        sent.append(url)
        if len(sent) <= len(errors):
            raise errors[len(sent) - 1]

    assert ct.export_otlp("https://otel:4318", "", {"traces": {}}, post, lambda s: None) == problems
    assert len(sent) == calls


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:tajne@otel:4318/x", "https://***@otel:4318/x"),
        ("https://token123@otel:4318", "https://***@otel:4318"),
        ("http://otel:4318", "http://otel:4318"),
    ],
)
def test_redact_url(url, expected):
    assert ct.redact_url(url) == expected


def test_dane_logowania_z_adresu_nie_trafiaja_do_logu(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://user:tajne@otel:4318")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer sekret-z-naglowka")
    monkeypatch.setattr(ct.time, "sleep", lambda s: None)

    def post(url, *a):
        raise OSError(f"nie można połączyć z {url}")

    ct.main(["--repo", "r", "--run-id", "42", "--history", "0", "--out", str(tmp_path)], gh=FakeGitHub(), post=post)
    out = capsys.readouterr().out
    assert "tajne" not in out and "sekret-z-naglowka" not in out
    assert "https://***@otel:4318" in out and "częściowo nieudany" in out


def test_main_zapisuje_artefakty(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    gh = FakeGitHub()
    assert ct.main(["--repo", "r", "--run-id", "42", "--out", str(tmp_path)], gh=gh) == 0
    assert {p.name for p in tmp_path.iterdir()} == {
        "otlp-traces.json",
        "otlp-metrics.json",
        "otlp-logs.json",
        "logs.jsonl",
        "summary.md",
    }
    json.loads((tmp_path / "otlp-traces.json").read_text())
    out = capsys.readouterr().out
    assert "| 5. Integracja | 50% (1/2)" in out and "tylko w artefaktach" in out
    assert ("jobs", 42, 1) in gh.calls


def test_main_eksport_i_bez_historii(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4318")
    sent = []
    gh = FakeGitHub()
    ct.main(
        ["--repo", "r", "--run-id", "42", "--attempt", "2", "--history", "0", "--out", str(tmp_path)],
        gh=gh,
        post=lambda url, *a: sent.append(url),
    )
    assert len(sent) == 3 and "Eksport OTLP do http://otel:4318: OK" in capsys.readouterr().out
    assert gh.calls == [("jobs", 42, 2)]  # --history 0: bez zapytań o historię


def test_github_klient_stronicowanie():
    pages = {1: [{"id": i} for i in range(100)], 2: [{"id": 100}]}

    def fetch(url, token):
        assert token == "tok" and url.startswith(ct.API + "/repos/o/r/")
        if "/jobs" in url:
            return {"jobs": pages[int(url.rsplit("page=", 1)[1])]}
        if "workflows/9/runs" in url:
            return {"workflow_runs": [{"id": 5, "run_attempt": 2}]}
        return {"id": 5}

    gh = ct.GitHub("o/r", "tok", fetch)
    assert len(gh.jobs(5, 1)) == 101
    assert gh.run(5) == {"id": 5}
    assert gh.history(9, 1)[0]["run"]["id"] == 5


@pytest.mark.parametrize(
    "start,end,expected", [("2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", 60.0), (None, "x", 0.0)]
)
def test_seconds(start, end, expected):
    assert ct.seconds(start, end) == expected
