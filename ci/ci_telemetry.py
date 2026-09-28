#!/usr/bin/env python3
"""Telemetria potoku CI: ślady, metryki i logi przebiegu GitHub Actions w formacie OpenTelemetry.

Dla wskazanego przebiegu buduje:
  traces   przebieg -> joby -> kroki (spany z czasami, wynikiem i atrybutami CI/CD)
  metrics  czas przebiegu, czas trwania i oczekiwania w kolejce każdego joba,
           skuteczność i p90 czasu jobów z ostatnich N przebiegów, liczba jobów niestabilnych
  logs     jeden ustrukturyzowany rekord na job i krok (JSON Lines + OTLP), z trace_id/span_id

Zapisuje wszystko w katalogu --out (OTLP/JSON + summary.md). Jeśli ustawiono
OTEL_EXPORTER_OTLP_ENDPOINT, wysyła też do kolektora OTLP/HTTP (/v1/traces, /v1/metrics, /v1/logs);
nagłówki (np. token) z OTEL_EXPORTER_OTLP_HEADERS w formacie "klucz=wartość,klucz2=wartość2".

    GITHUB_TOKEN=... python3 ci/ci_telemetry.py --repo xWuWux/wlb-golden-image --run-id 123 [--attempt 1]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API = "https://api.github.com"
SERVICE = "wlb-golden-image-ci"
EXPORT_ATTEMPTS = 3  # przerwy 1 s, 2 s — kolektor chwilowo niedostępny nie gubi telemetrii przebiegu
STATUS = {"success": 1, "failure": 2, "cancelled": 2, "timed_out": 2}  # OTLP: 1 OK, 2 ERROR, 0 UNSET


# --- dostęp do API ------------------------------------------------------------------------


def http_json(url: str, token: str | None, data: bytes | None = None, headers: dict | None = None):  # pragma: no cover
    # tylko http(s) — bez file:// i innych schematów; http dla kolektora OTLP w sieci wewnętrznej
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"dozwolone tylko http(s): {url}")
    req = urllib.request.Request(url, data=data, headers=headers or {})  # noqa: S310 - sprawdzone wyżej
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310  # nosec B310
        body = resp.read()
    return json.loads(body) if body else {}


class GitHub:
    def __init__(self, repo: str, token: str | None, fetch=http_json):
        self.repo, self.token, self.fetch = repo, token, fetch

    def get(self, path: str):
        return self.fetch(f"{API}/repos/{self.repo}/{path}", self.token)

    def run(self, run_id: int) -> dict:
        return self.get(f"actions/runs/{run_id}")

    def jobs(self, run_id: int, attempt: int) -> list[dict]:
        jobs, page = [], 1
        while True:
            batch = self.get(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")["jobs"]
            jobs += batch
            if len(batch) < 100:
                return jobs
            page += 1

    def history(self, workflow_id: int, limit: int) -> list[dict]:
        runs = self.get(f"actions/workflows/{workflow_id}/runs?status=completed&per_page={limit}")["workflow_runs"]
        return [{"run": r, "jobs": self.jobs(r["id"], r.get("run_attempt", 1))} for r in runs]


# --- konwersje ---------------------------------------------------------------------------------


def ns(ts: str | None) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1e9) if ts else 0


def seconds(start: str | None, end: str | None) -> float:
    return max(0.0, (ns(end) - ns(start)) / 1e9) if start and end else 0.0


def hex_id(*parts, length: int) -> str:
    """Deterministyczne identyfikatory: ten sam przebieg zawsze daje ten sam trace_id."""
    return hashlib.sha256("/".join(map(str, parts)).encode()).hexdigest()[:length]


def attrs(d: dict) -> list[dict]:
    out = []
    for key, value in d.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out.append({"key": key, "value": {"boolValue": value}})
        elif isinstance(value, int):
            out.append({"key": key, "value": {"intValue": str(value)}})
        elif isinstance(value, float):
            out.append({"key": key, "value": {"doubleValue": value}})
        else:
            out.append({"key": key, "value": {"stringValue": str(value)}})
    return out


def resource(run: dict) -> dict:
    return {"attributes": attrs({"service.name": SERVICE, "vcs.repository.name": run["repository"]["full_name"]})}


# --- ślady, metryki, logi ---------------------------------------------------------------------


def build_traces(run: dict, jobs: list[dict]) -> tuple[dict, str]:
    attempt = run.get("run_attempt", 1)
    trace_id = hex_id(run["repository"]["full_name"], run["id"], attempt, length=32)
    root_id = hex_id(trace_id, "run", length=16)
    spans = [
        {
            "traceId": trace_id,
            "spanId": root_id,
            "name": run["name"],
            "kind": 1,
            "startTimeUnixNano": str(ns(run.get("run_started_at") or run["created_at"])),
            "endTimeUnixNano": str(ns(run["updated_at"])),
            "status": {"code": STATUS.get(run.get("conclusion"), 0)},
            "attributes": attrs(
                {
                    "cicd.pipeline.name": run["name"],
                    "cicd.pipeline.run.id": run["id"],
                    "cicd.pipeline.run.attempt": attempt,
                    "cicd.pipeline.result": run.get("conclusion"),
                    "cicd.pipeline.trigger": run.get("event"),
                    "vcs.ref.head.name": run.get("head_branch"),
                    "vcs.ref.head.revision": run.get("head_sha"),
                    "url.full": run.get("html_url"),
                }
            ),
        }
    ]
    for job in jobs:
        job_id = hex_id(trace_id, "job", job["id"], length=16)
        spans.append(
            {
                "traceId": trace_id,
                "spanId": job_id,
                "parentSpanId": root_id,
                "name": job["name"],
                "kind": 1,
                "startTimeUnixNano": str(ns(job.get("started_at"))),
                "endTimeUnixNano": str(ns(job.get("completed_at"))),
                "status": {"code": STATUS.get(job.get("conclusion"), 0)},
                "attributes": attrs(
                    {
                        "cicd.pipeline.task.name": job["name"],
                        "cicd.pipeline.task.run.id": job["id"],
                        "cicd.pipeline.task.run.result": job.get("conclusion"),
                        "cicd.pipeline.task.queue_seconds": seconds(job.get("created_at"), job.get("started_at")),
                        "cicd.worker.name": job.get("runner_name"),
                        "url.full": job.get("html_url"),
                    }
                ),
            }
        )
        for step in job.get("steps") or []:
            spans.append(
                {
                    "traceId": trace_id,
                    "spanId": hex_id(job_id, "step", step["number"], length=16),
                    "parentSpanId": job_id,
                    "name": step["name"],
                    "kind": 1,
                    "startTimeUnixNano": str(ns(step.get("started_at"))),
                    "endTimeUnixNano": str(ns(step.get("completed_at"))),
                    "status": {"code": STATUS.get(step.get("conclusion"), 0)},
                    "attributes": attrs(
                        {
                            "cicd.pipeline.task.step.number": step["number"],
                            "cicd.pipeline.task.step.result": step.get("conclusion"),
                        }
                    ),
                }
            )
    body = {
        "resourceSpans": [{"resource": resource(run), "scopeSpans": [{"scope": {"name": SERVICE}, "spans": spans}]}]
    }
    return body, trace_id


def job_stats(history: list[dict]) -> dict[str, dict]:
    """Skuteczność, czasy i niestabilność jobów w oknie ostatnich przebiegów."""
    per_job: dict[str, dict] = {}
    results_by_sha: dict[tuple[str, str], set[str]] = {}
    for item in history:
        for job in item["jobs"]:
            if job.get("conclusion") in (None, "skipped"):
                continue
            s = per_job.setdefault(job["name"], {"runs": 0, "success": 0, "durations": []})
            s["runs"] += 1
            s["success"] += job["conclusion"] == "success"
            s["durations"].append(seconds(job.get("started_at"), job.get("completed_at")))
            results_by_sha.setdefault((job["name"], item["run"]["head_sha"]), set()).add(job["conclusion"])
    for name, s in per_job.items():
        d = sorted(s["durations"])
        s["success_ratio"] = s["success"] / s["runs"]
        s["p50"] = statistics.median(d)
        s["p90"] = d[min(len(d) - 1, round(0.9 * (len(d) - 1)))]
        # niestabilny = na tym samym commicie raz przeszedł, raz nie
        s["flaky_commits"] = sum(
            1 for (job, _), r in results_by_sha.items() if job == name and {"success", "failure"} <= r
        )
    return per_job


def gauge(name: str, unit: str, desc: str, points: list[tuple[float, dict]], t: int) -> dict:
    return {
        "name": name,
        "unit": unit,
        "description": desc,
        "gauge": {
            "dataPoints": [{"asDouble": float(v), "timeUnixNano": str(t), "attributes": attrs(a)} for v, a in points]
        },
    }


def build_metrics(run: dict, jobs: list[dict], stats: dict[str, dict]) -> dict:
    t = ns(run["updated_at"])
    base = {
        "cicd.pipeline.name": run["name"],
        "cicd.pipeline.trigger": run.get("event"),
        "vcs.ref.head.name": run.get("head_branch"),
    }
    ran = [j for j in jobs if j.get("conclusion") != "skipped"]
    metrics = [
        gauge(
            "wlb.ci.run.duration",
            "s",
            "Czas przebiegu CI",
            [
                (
                    seconds(run.get("run_started_at"), run["updated_at"]),
                    {**base, "cicd.pipeline.result": run.get("conclusion")},
                )
            ],
            t,
        ),
        gauge(
            "wlb.ci.job.duration",
            "s",
            "Czas trwania joba",
            [
                (
                    seconds(j.get("started_at"), j.get("completed_at")),
                    {
                        **base,
                        "cicd.pipeline.task.name": j["name"],
                        "cicd.pipeline.task.run.result": j.get("conclusion"),
                    },
                )
                for j in ran
            ],
            t,
        ),
        gauge(
            "wlb.ci.job.queue_time",
            "s",
            "Czas oczekiwania joba na runner",
            [
                (seconds(j.get("created_at"), j.get("started_at")), {**base, "cicd.pipeline.task.name": j["name"]})
                for j in ran
            ],
            t,
        ),
    ]
    if stats:
        metrics += [
            gauge(
                "wlb.ci.job.success_ratio",
                "1",
                "Skuteczność joba w oknie ostatnich przebiegów",
                [(s["success_ratio"], {"cicd.pipeline.task.name": n}) for n, s in stats.items()],
                t,
            ),
            gauge(
                "wlb.ci.job.duration_p90",
                "s",
                "90. percentyl czasu joba w oknie ostatnich przebiegów",
                [(s["p90"], {"cicd.pipeline.task.name": n}) for n, s in stats.items()],
                t,
            ),
            gauge(
                "wlb.ci.job.flaky_commits",
                "{commit}",
                "Commity, na których job raz przeszedł, raz nie",
                [(s["flaky_commits"], {"cicd.pipeline.task.name": n}) for n, s in stats.items()],
                t,
            ),
        ]
    return {
        "resourceMetrics": [
            {"resource": resource(run), "scopeMetrics": [{"scope": {"name": SERVICE}, "metrics": metrics}]}
        ]
    }


def build_logs(run: dict, jobs: list[dict], trace_id: str) -> tuple[dict, list[dict]]:
    records, jsonl = [], []
    for job in jobs:
        job_span = hex_id(trace_id, "job", job["id"], length=16)
        entries = [(job, job_span, None)] + [
            (s, hex_id(job_span, "step", s["number"], length=16), job["name"]) for s in job.get("steps") or []
        ]
        for item, span_id, parent in entries:
            result = item.get("conclusion")
            record = {
                "timestamp": item.get("completed_at") or run["updated_at"],
                "run_id": run["id"],
                "trace_id": trace_id,
                "span_id": span_id,
                "job": parent or item["name"],
                "step": item["name"] if parent else None,
                "result": result,
                "duration_s": seconds(item.get("started_at"), item.get("completed_at")),
            }
            jsonl.append(record)
            severity = (
                17 if result in ("failure", "timed_out") else 13 if result == "cancelled" else 9
            )  # ERROR/WARN/INFO
            records.append(
                {
                    "timeUnixNano": str(ns(record["timestamp"])),
                    "severityNumber": severity,
                    "body": {
                        "stringValue": f"{record['job']}{' / ' + record['step'] if record['step'] else ''}: {result}"
                    },
                    "traceId": trace_id,
                    "spanId": span_id,
                    "attributes": attrs(
                        {k: v for k, v in record.items() if k not in ("timestamp", "trace_id", "span_id")}
                    ),
                }
            )
    body = {
        "resourceLogs": [
            {"resource": resource(run), "scopeLogs": [{"scope": {"name": SERVICE}, "logRecords": records}]}
        ]
    }
    return body, jsonl


def summary(run: dict, jobs: list[dict], stats: dict[str, dict], trace_id: str) -> str:
    lines = [
        f"## Telemetria CI: {run['name']} #{run.get('run_number', run['id'])} — {run.get('conclusion')}",
        "",
        f"trace_id `{trace_id}` · czas przebiegu {seconds(run.get('run_started_at'), run['updated_at']) / 60:.1f} min",
        "",
        "| Job | Wynik | Kolejka | Czas |",
        "|---|---|---|---|",
    ]
    for j in jobs:
        lines.append(
            f"| {j['name']} | {j.get('conclusion')} | {seconds(j.get('created_at'), j.get('started_at')):.0f} s"
            f" | {seconds(j.get('started_at'), j.get('completed_at')) / 60:.1f} min |"
        )
    steps = sorted(
        (
            (seconds(s.get("started_at"), s.get("completed_at")), j["name"], s["name"])
            for j in jobs
            for s in j.get("steps") or []
        ),
        reverse=True,
    )[:5]
    if steps:
        lines += ["", "Najwolniejsze kroki:", *[f"- {d / 60:.1f} min — {j} / {s}" for d, j, s in steps]]
    if stats:
        lines += [
            "",
            "### Trend (ostatnie przebiegi)",
            "",
            "| Job | Skuteczność | p50 | p90 | Niestabilny |",
            "|---|---|---|---|---|",
        ]
        for name, s in sorted(stats.items()):
            lines.append(
                f"| {name} | {s['success_ratio']:.0%} ({s['success']}/{s['runs']}) | {s['p50'] / 60:.1f} min"
                f" | {s['p90'] / 60:.1f} min | {s['flaky_commits'] or '—'} |"
            )
    return "\n".join(lines) + "\n"


def redact_url(url: str) -> str:
    """Adres do logów bez danych logowania (https://user:hasło@host albo https://token@host)."""
    parts = urllib.parse.urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urllib.parse.urlunsplit(parts._replace(netloc="***@" + parts.netloc.rsplit("@", 1)[1]))


def retryable(e: Exception) -> bool:
    """Ponawiamy błędy przejściowe: sieć, timeout, 429 i 5xx. Inne 4xx (np. zły token) — od razu błąd."""
    # HTTPError dziedziczy po OSError, więc musi być sprawdzony pierwszy
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 429 or e.code >= 500
    return isinstance(e, OSError)  # URLError, TimeoutError, ConnectionError


def export_otlp(endpoint: str, headers_env: str, payloads: dict[str, dict], post=http_json, sleep=None) -> list[str]:
    sleep = sleep or time.sleep  # wyszukiwane przy wywołaniu — testy podmieniają time.sleep
    headers = {"Content-Type": "application/json"}
    for pair in filter(None, (headers_env or "").split(",")):
        key, _, value = pair.partition("=")
        headers[key.strip()] = value.strip()
    safe = redact_url(endpoint)
    problems = []
    for signal, body in payloads.items():
        data = json.dumps(body).encode()
        for attempt in range(1, EXPORT_ATTEMPTS + 1):
            try:
                post(f"{endpoint.rstrip('/')}/v1/{signal}", None, data, headers)
                break
            except Exception as e:
                if attempt < EXPORT_ATTEMPTS and retryable(e):
                    sleep(2 ** (attempt - 1))
                    continue
                # komunikat wyjątku może zawierać adres — bez danych logowania
                msg = str(e).replace(endpoint, safe)
                problems.append(f"{signal}: {msg}" + (f" (po {attempt} próbach)" if attempt > 1 else ""))
                break
    return problems


def main(argv=None, gh: GitHub | None = None, post=http_json) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--history", type=int, default=30, help="liczba przebiegów do trendu (0 = bez)")
    parser.add_argument("--out", type=Path, default=Path("build/ci-telemetry"))
    args = parser.parse_args(argv)
    gh = gh or GitHub(args.repo, os.environ.get("GITHUB_TOKEN"))

    run = gh.run(args.run_id)
    jobs = gh.jobs(args.run_id, args.attempt or run.get("run_attempt", 1))
    stats = job_stats(gh.history(run["workflow_id"], args.history)) if args.history else {}
    traces, trace_id = build_traces(run, jobs)
    metrics = build_metrics(run, jobs, stats)
    logs, jsonl = build_logs(run, jobs, trace_id)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, body in (("traces", traces), ("metrics", metrics), ("logs", logs)):
        (args.out / f"otlp-{name}.json").write_text(json.dumps(body, indent=1))
    (args.out / "logs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in jsonl))
    text = summary(run, jobs, stats, trace_id)
    (args.out / "summary.md").write_text(text)
    print(text)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):  # pragma: no cover
        with open(path, "a") as f:
            f.write(text)

    if endpoint := os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        problems = export_otlp(
            endpoint,
            os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", ""),
            {"traces": traces, "metrics": metrics, "logs": logs},
            post,
        )
        for p in problems:
            print(f"::warning::Eksport OTLP nie powiódł się — {p}")
        print(f"Eksport OTLP do {redact_url(endpoint)}: {'OK' if not problems else 'częściowo nieudany'}")
    else:
        print("OTEL_EXPORTER_OTLP_ENDPOINT nie ustawiony — telemetria tylko w artefaktach.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
