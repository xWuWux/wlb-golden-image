"""Selekcja zakresu, kompletność i przerwanie etapu 4b (#342)."""

import json
import sys
import time
from pathlib import Path

import mutation_plan as mp
import pytest


def test_actual_reverse_inputs_and_conservative_fallback():  # regresja zakresu etapu 4b (#342)
    inputs, commands = mp.inventory(mp.ROOT)
    assert inputs.keys() == commands.keys()
    selected, _ = mp.choose({"tests/unit/test_http_boundaries.py"}, inputs)
    assert selected == {"contracts/github-run", "contracts/license-registry"}
    selected, _ = mp.choose({"tests/unit/wlb-firstboot.bats"}, inputs)
    assert selected == {
        "bash/ansible/roles/lab_config/files/wlb-firstboot",
        "contracts/hub-rules",
        "contracts/hub-rollback",
    }
    for path in (*mp.SHARED, "new/unknown", "ci/mutation.sh", "ci/mutations/abstractions.yml", "setup.cfg"):
        assert mp.choose({path}, inputs)[0] == set(inputs)
    assert mp.choose(set(), inputs)[0] == set(inputs)
    assert mp.choose({"ci/verify_platform_images.py"}, inputs)[0] == {"mutmut"}


def commit(repo: Path) -> str:
    mp.git(repo, "add", "-A")
    mp.git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost", "commit", "-qm", "fixture")
    return mp.git(repo, "rev-parse", "HEAD").decode().strip()


def test_git_plan_rename_delete_bad_ref_and_dirty_checkout(tmp_path: Path):  # regresja zakresu etapu 4b (#342)
    mp.git(tmp_path, "init", "-q")
    old, new = "one old\nfile", "one new file"
    (tmp_path / old).write_text("content")
    base = commit(tmp_path)
    (tmp_path / old).rename(tmp_path / new)
    renamed = commit(tmp_path)
    inputs = {"old": {old}, "new": {new}, "other": {"other"}}
    report = mp.plan(tmp_path, base, inputs)
    assert report["selected"] == ["new", "old"]
    assert report["omitted"] == ["other"]
    assert (report["base"], report["head"]) == (base, renamed)
    assert report["changed"] == sorted([old, new])
    assert mp.plan(tmp_path, "no-such-base", inputs)["mode"] == "full"
    assert mp.plan(tmp_path, None, inputs)["mode"] == "full"
    (tmp_path / new).unlink()
    assert mp.plan(tmp_path, base, inputs)["reason"] == "dirty checkout"
    commit(tmp_path)
    assert mp.plan(tmp_path, renamed, inputs)["selected"] == ["new"]


def test_timeout_records_required_work_and_reaps_descendant(
    tmp_path: Path, monkeypatch
):  # regresja zakresu etapu 4b (#342)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    pidfile = tmp_path / "pid"
    code = (
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "Path(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(30)"
    )
    cmds = {"slow": [sys.executable, "-c", code, str(pidfile)], "next": [sys.executable, "-V"]}
    report = {"targets": {k: {"status": "not_started"} for k in cmds}, "mode": "full", "reason": "test", "omitted": []}
    assert mp.execute(report, cmds, tmp_path, time.monotonic(), 1) == 1
    saved = json.loads((tmp_path / "selection.json").read_text())
    assert saved["expired"] is True
    assert [saved["targets"][k]["status"] for k in cmds] == ["timeout", "not_started"]
    # An exited child awaiting reaping by PID 1 has no running code.
    stat = Path("/proc") / pidfile.read_text() / "stat"
    for _ in range(100):
        try:
            state = stat.read_text().split()[2]
        except FileNotFoundError:
            return
        if state == "Z":
            return
        time.sleep(0.01)
    pytest.fail("descendant still running")


def test_only_planned_commands_execute_and_failure_is_preserved(
    tmp_path: Path, monkeypatch
):  # regresja zakresu etapu 4b (#342)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    cmds = {"one": [sys.executable, "-c", "raise SystemExit(3)"], "two": [sys.executable, "-V"], "omitted": ["missing"]}
    report = {
        "targets": {k: {"status": "not_started"} for k in ("one", "two")},
        "mode": "incremental",
        "reason": "test",
        "omitted": ["omitted"],
    }
    assert mp.execute(report, cmds, tmp_path, time.monotonic(), 10) == 1
    assert [r["status"] for r in report["targets"].values()] == ["failed", "passed"]
    assert not (tmp_path / "omitted").exists()
