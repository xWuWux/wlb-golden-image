"""Run each reviewed source mutation against every consumer in an isolated fixture."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = Path("ci/mutations/abstractions.yml")
ID = re.compile(r"[a-z0-9][a-z0-9-]*")


def catalog(root: Path) -> dict:
    groups = yaml.safe_load((root / CATALOG).read_text())
    if not isinstance(groups, dict) or not groups:
        raise ValueError("empty contract catalog")
    for name, group in groups.items():
        if not ID.fullmatch(name) or not group["owner"] or group["risk"] not in {"critical", "normal"}:
            raise ValueError(f"invalid contract: {name}")
        for path in [group["source"], group["test"], *group["inputs"]]:
            if (
                Path(path).is_absolute()
                or ".." in Path(path).parts
                or not (root / path).resolve().is_relative_to(root.resolve())
                or not (root / path).is_file()
            ):
                raise ValueError(f"{name}: invalid input {path}")
        if not group["consumers"] or not group["mutations"] or Path(group["test"]).suffix not in {".py", ".bats"}:
            raise ValueError(f"{name}: missing selectors or mutations")
        if not all(ID.fullmatch(key) and isinstance(value, str) and value for key, value in group["consumers"].items()):
            raise ValueError(f"{name}: invalid consumer")
        source = (root / group["source"]).read_text()
        seen = set()
        for key, old, new, marker in group["mutations"]:
            if not ID.fullmatch(key) or key in seen or old == new or source.count(old) != 1 or not ID.fullmatch(marker):
                raise ValueError(f"{name}/{key}: invalid mutation or stale source fragment")
            seen.add(key)
    return groups


def verdict(rc: int, report: str, marker: str, bats: bool) -> str:
    """Only one executed assertion, failing for the declared reason, counts as a kill."""
    if bats:
        if report.startswith("1..0\n"):
            return "no-tests"
        if not report.startswith("1..1\n") or re.search(r"^ok 1 .* # skip", report, re.M | re.I):
            return "error"
        if rc == 0 and re.search(r"^ok 1 ", report, re.M):
            return "passed"
        if rc == 1 and re.search(r"^not ok 1 ", report, re.M) and f"# contract:{marker}" in report.splitlines():
            return "killed"
        return "error"
    try:
        cases = ElementTree.fromstring(report).findall(".//testcase")  # noqa: S314 - local pytest report
    except ElementTree.ParseError:
        return "error"
    if not cases:
        return "no-tests"
    if len(cases) != 1 or any(cases[0].find(tag) is not None for tag in ("error", "skipped")):
        return "error"
    failure = cases[0].find("failure")
    if rc == 0 and failure is None:
        return "passed"
    if (
        rc == 1
        and failure is not None
        and failure.get("message", "").splitlines()[:1] == [f"AssertionError: contract:{marker}"]
    ):
        return "killed"
    return "error"


def run_test(work: Path, test: str, selector: str, marker: str, log: Path) -> str:
    bats = test.endswith(".bats")
    xml = work / "pytest.xml"
    xml.unlink(missing_ok=True)
    args = (
        ["bats", "--formatter", "tap", "-f", f"^{re.escape(selector)}$", test]
        if bats
        else [
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={xml}",
            f"{test}::{selector}",
        ]
    )
    # GNU timeout also signals descendants of the test. A timeout has its own status.
    with log.open("w") as output:
        rc = subprocess.run(  # noqa: S603
            ["timeout", "-k", "5", "60", *args],  # noqa: S607 - pinned CI tools on PATH
            cwd=work,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        ).returncode
    if rc in {124, 137}:
        return "timeout"
    report = log.read_text() if bats else xml.read_text() if xml.exists() else ""
    return verdict(rc, report, marker, bats)


def run_group(root: Path, name: str, group: dict, output: Path) -> list[dict]:
    results = []
    for key, old, new, marker in group["mutations"]:
        for consumer, selector in group["consumers"].items():
            prefix = f"{name}.{key}.{consumer}"
            with tempfile.TemporaryDirectory() as temp:
                work = Path(temp)
                for path in (group["source"], group["test"], *group["inputs"]):
                    (work / path).parent.mkdir(exist_ok=True, parents=True)
                    shutil.copy2(root / path, work / path)
                baseline = run_test(work, group["test"], selector, marker, output / f"{prefix}.base.log")
                if baseline != "passed":
                    status = f"baseline-{baseline}"
                else:
                    path = work / group["source"]
                    path.write_text(path.read_text().replace(old, new, 1))
                    status = run_test(work, group["test"], selector, marker, output / f"{prefix}.mutant.log")
                    if status == "passed":
                        status = "survived"
            results.append(
                {"contract": name, "source": group["source"], "mutation": key, "consumer": consumer, "status": status}
            )
            print(f"{prefix}: {status}", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/mutation")
    args = parser.parse_args()
    groups = catalog(ROOT)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, group in groups.items():
        rows.extend(run_group(ROOT, name, group, args.output))
    (args.output / "contracts.json").write_text(json.dumps(rows, indent=2) + "\n")
    files = defaultdict(list)
    for row in rows:
        files[row["source"]].append(row["status"])
    summary = ["### Kontrakty — wykryte pary mutacja × konsument (wymagane 100% na plik)", ""]
    for source, states in sorted(files.items()):
        summary.append(f"- `{source}` — {states.count('killed')}/{len(states)}")
    (args.output / "contracts-summary.md").write_text("\n".join(summary) + "\n")
    return int(any(row["status"] != "killed" for row in rows))


if __name__ == "__main__":
    sys.exit(main())
