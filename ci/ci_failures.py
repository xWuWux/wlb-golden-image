#!/usr/bin/env python3
"""Diagnoza nieudanego przebiegu CI i decyzja o automatycznym ponowieniu.

Każdy nieudany job dostaje kategorię i ścieżkę z docs/ci-runbook.md:
  test       błąd testu lub narzędzia — wymaga poprawki kodu, bez ponawiania
  oom        strażnik (ci/guard.sh) zabił proces po przekroczeniu limitu pamięci
  timeout    przekroczony limit czasu (strażnik albo timeout-minutes joba)
  infra      runner przerwał job bez błędu testu ("The operation was canceled", utrata runnera)
             albo przejściowy błąd sieci/usługi zewnętrznej (HTTP 5xx, timeout, DNS, limit API)
  cancelled  anulowane: nowszy commit w PR albo ręcznie

Automatyczne ponowienie (tylko nieudane joby, jeden raz) wyłącznie dla kategorii infra, i tylko gdy
przebieg dotyczy najnowszego commita gałęzi.

    python3 ci/ci_failures.py diagnose --repo OWNER/REPO --run-id ID
    python3 ci/ci_failures.py retry    --repo OWNER/REPO --run-id ID   # diagnoza + ewentualne ponowienie
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from ci_telemetry import API, GitHub

RUNBOOK = "docs/ci-runbook.md"
GATE_JOB = "Gotowe do code review"  # bramka końcowa — jej niepowodzenie to skutek, nie przyczyna
CATEGORIES = {
    "test": ("Błąd testu lub narzędzia", "popraw kod — logi kroku i artefakty joba"),
    "oom": ("Brak pamięci (strażnik zabił proces)", "zmniejsz zużycie albo podnieś limit --memory"),
    "timeout": ("Przekroczony limit czasu", "sprawdź, na czym proces utknął; podnieś limit tylko z uzasadnieniem"),
    "infra": ("Awaria infrastruktury (runner lub usługa zewnętrzna)", "automatyczne ponowienie raz; potem runbook"),
    "cancelled": ("Anulowane (nowszy commit albo ręcznie)", "nic — liczy się najnowszy przebieg"),
}
INFRA_MESSAGES = ("The operation was canceled", "lost communication", "shutdown signal", "runner has received")
# przejściowe błędy sieci i usług zewnętrznych (pobieranie narzędzi, API) — nie wynikają z kodu
TRANSIENT_NETWORK = re.compile(
    r"status code 5\d\d|HTTP 5\d\d|\b50[234]\b|ETIMEDOUT|ECONNRESET|ENOTFOUND|ECONNREFUSED|socket hang up"
    r"|Could not resolve host|Temporary failure in name resolution|Connection timed out|TLS handshake timeout"
    r"|rate limit exceeded|secondary rate limit",
    re.IGNORECASE,
)


def classify_job(job: dict, annotations: list[dict], run_conclusion: str | None) -> str | None:
    conclusion = job.get("conclusion")
    if conclusion in (None, "success", "skipped", "neutral"):
        return None
    titles = [a.get("title") or "" for a in annotations]
    messages = [a.get("message") or "" for a in annotations]
    if any(t.startswith("INFRA:") for t in titles):  # np. ci/enable-kvm.sh: runner bez KVM
        return "infra"
    if any(t.startswith("OOM:") for t in titles):
        return "oom"
    if conclusion == "timed_out" or any(t.startswith("TIMEOUT:") for t in titles):
        return "timeout"
    if conclusion == "cancelled" and run_conclusion == "cancelled":
        return "cancelled"
    steps = job.get("steps") or []
    step_failed = any(s.get("conclusion") == "failure" for s in steps)
    step_cancelled = any(s.get("conclusion") == "cancelled" for s in steps)
    infra_msg = any(m in msg for msg in messages for m in INFRA_MESSAGES)
    if (step_cancelled or infra_msg or conclusion == "cancelled") and not step_failed:
        return "infra"
    if any(TRANSIENT_NETWORK.search(msg) for msg in messages):
        return "infra"
    return "test"


def diagnose(gh: GitHub, run: dict, jobs: list[dict]) -> list[dict]:
    rows = []
    for job in jobs:
        if job["name"] == GATE_JOB:
            continue
        annotations = gh.fetch(f"{job['check_run_url']}/annotations", gh.token) if job.get("check_run_url") else []
        category = classify_job(job, annotations, run.get("conclusion"))
        if category:
            failed_step = next(
                (s["name"] for s in job.get("steps") or [] if s.get("conclusion") in ("failure", "cancelled")), "—"
            )
            rows.append({"job": job["name"], "category": category, "step": failed_step, "url": job.get("html_url")})
    return rows


def should_retry(gh: GitHub, run: dict, rows: list[dict]) -> tuple[bool, str]:
    if not rows:
        return False, "brak nieudanych jobów"
    if run.get("run_attempt", 1) >= 2:
        return False, "przebieg był już ponawiany — dalej ręcznie według runbooka"
    if run.get("conclusion") == "cancelled":
        return False, "przebieg anulowany"
    categories = {r["category"] for r in rows}
    if not categories <= {"infra"}:
        return False, "są błędy inne niż awaria infrastruktury (" + ", ".join(sorted(categories - {"infra"})) + ")"
    latest = gh.get(f"branches/{run['head_branch']}")["commit"]["sha"]
    if latest != run["head_sha"]:
        return False, "gałąź ma nowszy commit — liczy się jego przebieg"
    return True, "tylko awaria infrastruktury na najnowszym commicie"


def report(run: dict, rows: list[dict], decision: tuple[bool, str] | None) -> str:
    repo, sha = run.get("repository", {}).get("full_name"), run.get("head_sha")
    runbook = f"https://github.com/{repo}/blob/{sha}/{RUNBOOK}" if repo and sha else RUNBOOK
    lines = [f"## Diagnoza przebiegu {run.get('name')} #{run.get('run_number', run['id'])}", ""]
    if not rows:
        return "\n".join([*lines, "Brak nieudanych jobów.", ""])
    lines += ["| Job | Kategoria | Krok | Co dalej |", "|---|---|---|---|"]
    for r in rows:
        label, action = CATEGORIES[r["category"]]
        lines.append(
            f"| [{r['job']}]({r['url']}) | {label} | {r['step']} | {action} ([runbook]({runbook}#{r['category']})) |"
        )
    if decision is not None:
        lines += ["", f"**Automatyczne ponowienie: {'TAK' if decision[0] else 'NIE'}** — {decision[1]}."]
    return "\n".join(lines) + "\n"


def main(argv=None, gh: GitHub | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["diagnose", "retry"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args(argv)
    gh = gh or GitHub(args.repo, os.environ.get("GITHUB_TOKEN"))

    run = gh.run(args.run_id)
    rows = diagnose(gh, run, gh.jobs(args.run_id, run.get("run_attempt", 1)))
    decision = should_retry(gh, run, rows) if args.command == "retry" else None
    text = report(run, rows, decision)
    print(text)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):  # pragma: no cover
        with open(path, "a") as f:
            f.write(text)
    if decision and decision[0]:
        gh.fetch(f"{API}/repos/{args.repo}/actions/runs/{args.run_id}/rerun-failed-jobs", gh.token, b"{}")
        print("Zlecono ponowienie nieudanych jobów.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
