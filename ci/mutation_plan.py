"""Select mutation targets from their actual inputs and enforce one deadline for the stage."""

from __future__ import annotations

import argparse
import configparser
import csv
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from mutation_contracts import ROOT, catalog

OUT = Path("build/mutation")
# These inputs affect more than their immediate unit tests (or the test harness itself).
SHARED = {
    "ci/deployment_vars.py",
    "ansible/roles/lab_config/files/wlb-firstboot",
    "observability/contract.yml",
    "tests/channels.yaml",
    "tests/unit/helpers.bash",
    "tests/unit/conftest.py",
}


def inventory(root: Path) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    inputs, commands = {}, {}
    config = configparser.ConfigParser()
    config.read(root / "setup.cfg")
    settings = config["mutmut"]
    inputs["mutmut"] = set(settings["source_paths"].split() + settings["pytest_add_cli_args_test_selection"].split())
    commands["mutmut"] = ["ci/mutation-python.sh"]
    table = (root / "ci/mutations/bash-mutations.tsv").read_text().splitlines()
    rows = list(
        csv.reader((line for line in table if line.strip() and not line.lstrip().startswith("#")), delimiter="\t")
    )
    if not rows:
        raise ValueError("empty Bash mutation table")
    for source, _before, _after, test, _selector, _description in rows:
        if not source or Path(source).is_absolute() or ".." in Path(source).parts:
            raise ValueError(f"invalid Bash source: {source}")
        key = "bash/" + source
        inputs.setdefault(key, set()).update([source, test])
        commands[key] = ["ci/mutation-bash.sh", "--source", source, "--output", str(OUT / key / "bash-summary.md")]
    for name, group in catalog(root).items():
        key = "contracts/" + name
        inputs[key] = {group["source"], group["test"], *group["inputs"]}
        commands[key] = [sys.executable, "ci/mutation_contracts.py", "--group", name, "--output", str(OUT / key)]
    return inputs, commands


def git(root: Path, *args: str, deadline: float | None = None) -> bytes:
    timeout = 10 if deadline is None else min(10, max(0, deadline - time.monotonic()))
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True, timeout=timeout).stdout  # noqa: S603,S607


def choose(paths: set[str], inputs: dict[str, set[str]]) -> tuple[set[str], str]:
    all_targets = set(inputs)
    if not paths:
        return all_targets, "empty diff"
    unknown = paths - set.union(*inputs.values())
    if paths & SHARED or unknown:
        return all_targets, "shared or unmapped inputs"
    return {key for key, deps in inputs.items() if paths & deps}, "mapped inputs and consumers"


def plan(root: Path, since: str | None, inputs: dict[str, set[str]], deadline: float | None = None) -> dict:
    try:
        head = git(root, "rev-parse", "--verify", "HEAD^{commit}", deadline=deadline).decode().strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        head = None
    selected, reason = set(inputs), "full run requested"
    base, paths = None, set()
    if head is None:
        reason = "unavailable HEAD"
    elif since is not None:
        try:
            ref = (
                git(root, "rev-parse", "--verify", "--end-of-options", since + "^{commit}", deadline=deadline)
                .decode()
                .strip()
            )
            base = git(root, "merge-base", ref, head, deadline=deadline).decode().strip()
            # With rename detection disabled both old and new paths appear in the diff.
            entries = git(root, "diff", "--no-renames", "--name-only", "-z", base, head, "--", deadline=deadline).split(
                b"\0"
            )
            paths = {os.fsdecode(p) for p in entries if p}
            if git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal", deadline=deadline):
                reason = "dirty checkout"
            else:
                selected, reason = choose(paths, inputs)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            reason = "unavailable base or incomplete history"
    return {
        "version": 1,
        "base": base,
        "head": head,
        "changed": sorted(paths),
        "reason": reason,
        "mode": "full" if selected == set(inputs) else "incremental",
        "selected": sorted(selected),
        "omitted": sorted(set(inputs) - selected),
        "targets": {key: {"status": "not_started"} for key in sorted(selected)},
    }


def save(path: Path, value: object) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def run_target(args: list[str], log: Path, deadline: float) -> str:
    with (
        tempfile.TemporaryDirectory() as work,
        log.open("w") as out,
        subprocess.Popen(  # noqa: S603 - argv assembled from known adapters
            args,
            start_new_session=True,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, "TMPDIR": work},
        ) as child,
    ):
        try:
            return "passed" if child.wait(timeout=max(0, deadline - time.monotonic())) == 0 else "failed"
        except subprocess.TimeoutExpired:
            return "timeout"
        finally:
            # Stop the whole group even on SIGTERM or if an adapter left a descendant behind.
            with suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def execute(report: dict, commands: dict[str, list[str]], out: Path, start: float, budget: int) -> int:
    deadline = start + budget
    report["budget_seconds"] = budget
    report_path = out / "selection.json"
    save(report_path, report)
    for key, result in report["targets"].items():
        if time.monotonic() >= deadline:
            break
        folder = out / key
        folder.mkdir(exist_ok=True, parents=True)
        result["status"] = "running"
        save(report_path, report)
        began = time.monotonic()
        try:
            result["status"] = run_target(commands[key], folder / "run.log", deadline)
        except OSError as exc:
            result.update(status="error", error=str(exc))
        finally:
            if result["status"] == "running":
                result["status"] = "interrupted"
            result["seconds"] = round(time.monotonic() - began, 3)
            save(report_path, report)
        print(f"{key}: {result['status']} ({result['seconds']} s)", flush=True)
        if result["status"] != "passed":
            log = folder / "run.log"
            if log.exists():
                print(log.read_text(errors="replace")[-3000:], file=sys.stderr)
    rows = []
    # Retain completed pairs even if their group ran out of time.
    for journal in sorted((out / "contracts").glob("*/pairs.jsonl")):
        for line in journal.read_bytes().splitlines(keepends=True):
            if line.endswith(b"\n"):
                rows.append(json.loads(line))
    if rows:
        save(out / "contracts.json", rows)
    for name in ("bash-summary.md", "contracts-summary.md"):
        parts = [f.read_text() for f in sorted(out.glob(f"*/**/{name}"))]
        if parts:
            (out / name).write_text("\n\n".join(parts))
    report["seconds"] = round(time.monotonic() - start, 3)
    report["expired"] = time.monotonic() >= deadline
    save(report_path, report)
    summary = [
        f"### Zakres mutacji: {report['mode']} ({report['reason']}, {report['seconds']} s)",
        "",
        *(f"- `{key}` — {result['status']}" for key, result in report["targets"].items()),
        "",
        "Pominięte przez selektor: " + (", ".join(report["omitted"]) or "brak"),
    ]
    if report["expired"]:
        summary.append("Przekroczony budżet etapu.")
    (out / "selection-summary.md").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    if dest := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(dest).open("a") as stream:
            for path in sorted(out.glob("*-summary.md")):
                stream.write(path.read_text() + "\n")
    return int(report["expired"] or any(r["status"] != "passed" for r in report["targets"].values()))


def main() -> int:
    start = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="compare merge-base with the tested HEAD")
    args = parser.parse_args()
    try:
        budget = int(os.environ.get("MUTATION_MAX_SECONDS", "1080"))
        if budget < 1:
            raise ValueError("MUTATION_MAX_SECONDS must be positive")
        inputs, commands = inventory(ROOT)
        report = plan(ROOT, args.since, inputs, start + budget)
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"mutation plan: {exc}\n")
    return execute(report, commands, ROOT / OUT, start, budget)


if __name__ == "__main__":

    def terminate(_signal, _frame):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main())
