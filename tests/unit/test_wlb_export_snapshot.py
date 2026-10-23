"""#20: snapshot integrity, hostile inputs and failure containment."""

# ruff: noqa: S603 - subprocess arguments are fixed test paths, never shell input.
import hashlib
import json
import os
import subprocess
import sys

import pytest
from conftest import REPO_ROOT, load_script

SCRIPT = REPO_ROOT / "ansible/roles/storage/files/wlb-export-snapshot"
MOVER = SCRIPT.with_name("wlb-sluza-out-mover")


@pytest.fixture
def snapshot():
    return load_script("wlb_export_snapshot", SCRIPT)


# --- #20: integralność kopii, manifest, wyścigi i awarie ---
def test_open_writer_cannot_modify_snapshot(snapshot, tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"reviewed")
    with source.open("r+b") as writer:
        bundle = tmp_path / "bundle"
        manifest = snapshot.create(source, bundle, "result.csv", "test-id")
        writer.write(b"modified")
        writer.flush()
        assert (bundle / "payload").read_bytes() == b"reviewed"
        assert snapshot.verify(bundle) == manifest
        assert source.stat().st_ino != (bundle / "payload").stat().st_ino
    assert manifest["requester"]["uid"] == os.getuid()
    assert manifest["sha256"] == hashlib.sha256(b"reviewed").hexdigest()
    assert (bundle / "payload").stat().st_mode & 0o777 == 0o600
    assert (bundle / "manifest.json").stat().st_mode & 0o777 == 0o600


def test_directory_inventory_is_relocatable_and_includes_empty_dirs(snapshot, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "empty").mkdir()
    (source / "a\n\\b").write_bytes(b"data")
    bundle = tmp_path / "bundle"
    manifest = snapshot.create(source, bundle, "source", "id")
    moved = tmp_path / "relocated"
    bundle.rename(moved)
    assert snapshot.verify(moved) == manifest
    assert [entry["path"] for entry in manifest["entries"]] == [".", "a\n\\b", "empty"]
    (moved / "payload" / "empty").rmdir()
    with pytest.raises(snapshot.SnapshotError, match="integrity_mismatch"):
        snapshot.verify(moved)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "nested_symlink", "nested_fifo"])
def test_unsafe_input_is_not_partially_accepted(snapshot, tmp_path, kind):
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    outside.write_text("secret")
    target = source
    if kind.startswith("nested_"):
        source.mkdir()
        (source / "ok").write_text("ok")
        target = source / "unsafe"
    if kind.endswith("symlink"):
        target.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, target)
    else:
        os.mkfifo(target)
    bundle = tmp_path / "bundle"
    with pytest.raises((OSError, snapshot.SnapshotError)):
        snapshot.create(source, bundle, "original", "id")
    assert not (bundle / "manifest.json").exists()
    assert outside.read_text() == "secret"
    assert source.exists()  # retained, not deleted on failure


@pytest.mark.parametrize("change", ["content", "extra_file", "algorithm", "version", "state"])
def test_verify_refuses_tampering(snapshot, tmp_path, change):
    source = tmp_path / "source"
    source.mkdir()
    (source / "result").write_text("ok")
    bundle = tmp_path / "bundle"
    manifest = snapshot.create(source, bundle, "original", "id")
    if change == "content":
        (bundle / "payload" / "result").write_text("bad")
    elif change == "extra_file":
        (bundle / "payload" / "extra").touch()
    else:
        key = {"algorithm": "digest_algorithm", "version": "schema_version", "state": "state"}[change]
        manifest[key] = "bad"
        (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(snapshot.SnapshotError):
        snapshot.verify(bundle)


def test_old_entries_are_not_silently_approved(snapshot, tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshot.verify(tmp_path)


@pytest.mark.parametrize("limit", ["MAX_BYTES", "MAX_ENTRIES", "MAX_DEPTH"])
def test_resource_limits(snapshot, tmp_path, monkeypatch, limit):
    source = tmp_path / "source"
    source.mkdir()
    (source / "child").write_text("x")
    monkeypatch.setattr(snapshot, limit, 0)
    with pytest.raises(snapshot.SnapshotError, match="limit_exceeded"):
        snapshot.create(source, tmp_path / "bundle", "name", "id")


def test_disk_full_keeps_source_and_no_ready_manifest(snapshot, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_text("result")

    def fail_write(*args):
        raise OSError(28, "No space left")

    monkeypatch.setattr(snapshot.os, "write", fail_write)
    with pytest.raises(OSError):
        snapshot.create(source, tmp_path / "bundle", "name", "id")
    assert source.read_text() == "result"
    assert not (tmp_path / "bundle/manifest.json").exists()


def test_concurrent_edit_during_copy_is_rejected(snapshot, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    real_read = snapshot.os.read

    def read_and_mutate(fd, size):
        result = real_read(fd, size)
        if result:
            source.write_bytes(b"mutation")
        return result

    monkeypatch.setattr(snapshot.os, "read", read_and_mutate)
    with pytest.raises(snapshot.SnapshotError, match="source_changed"):
        snapshot.create(source, tmp_path / "bundle", "name", "id")


def test_symlink_swap_between_list_and_open(snapshot, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    child = source / "child"
    child.write_text("ok")
    outside = tmp_path / "outside"
    outside.write_text("secret")
    real_listdir = snapshot.child_names

    def swap(fd, limit):
        result = real_listdir(fd, limit)
        child.unlink()
        child.symlink_to(outside)
        return result

    monkeypatch.setattr(snapshot, "child_names", swap)
    with pytest.raises(OSError):
        snapshot.create(source, tmp_path / "bundle", "name", "id")
    assert outside.read_text() == "secret"
    assert not (tmp_path / "bundle/payload/child").exists()


def test_cli(snapshot, tmp_path):
    source = tmp_path / "source"
    source.write_text("ok")
    bundle = tmp_path / "bundle"
    command = [sys.executable, str(SCRIPT)]
    result = subprocess.run([*command, "create", str(source), str(bundle), "name", "id"], capture_output=True)
    assert result.returncode == 0
    verified = subprocess.run([*command, "verify", str(bundle)], capture_output=True)
    assert verified.stdout == result.stdout
    assert verified.returncode == 0
    (bundle / "payload").write_text("tampered")
    assert subprocess.run([*command, "verify", str(bundle)], capture_output=True).returncode == 1


def run_mover(tmp_path, name="result", content=b"reviewed", *, fail=False):
    src = tmp_path / "sluza"
    src.mkdir()
    queue = tmp_path / "queue"
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for tool, body in {"fuser": "exit 1", "logger": 'printf "%s\\n" "$*" >>"$TEST_LOG"'}.items():
        script = stubs / tool
        script.write_text("#!/bin/sh\n" + body + "\n")
        script.chmod(0o700)
    source = src / name
    if fail:
        source.mkdir()
        (source / "bad").symlink_to("/etc/passwd")
    else:
        source.write_bytes(content)
    env = {
        **os.environ,
        "PATH": str(stubs) + ":" + os.environ["PATH"],
        "WLB_SLUZA_OUT": str(src),
        "WLB_EXPORT_QUEUE": str(queue),
        "WLB_IMAGE_CONF": str(tmp_path / "missing"),
        "WLB_DIR_SETTLE_SECONDS": "0",
        "TEST_LOG": str(tmp_path / "log"),
    }
    return source, queue, env


def test_mover_manifest_and_retained_writer_regression(tmp_path):
    source, queue, env = run_mover(tmp_path)
    with source.open("r+b") as writer:
        subprocess.run([str(MOVER), "--once"], env=env, check=True, capture_output=True)
        (bundle,) = [p for p in queue.iterdir() if not p.name.startswith(".")]
        writer.write(b"modified")
        writer.flush()
        payload = bundle / "payload" if bundle.is_dir() else bundle  # also exercise the pre-fix format
        assert payload.read_bytes() == b"reviewed"
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    assert manifest["original_name"] == "result"
    assert manifest["state"] == "pending_review"
    assert not list(queue.glob(".incoming.*"))


def test_mover_failure_retains_quarantine_without_ready_request(tmp_path):
    _, queue, env = run_mover(tmp_path, fail=True)
    subprocess.run([str(MOVER), "--once"], env=env, check=True, capture_output=True)
    assert not [p for p in queue.iterdir() if not p.name.startswith(".")]
    assert list(queue.glob(".incoming.*/source/bad"))
    assert "export_request" not in (tmp_path / "log").read_text()
    assert "snapshot_failed" in (tmp_path / "log").read_text()


def test_newline_name_does_not_inject_audit_fields(tmp_path):
    name = "result\nexport_request uid=0"
    _, queue, env = run_mover(tmp_path, name=name)
    subprocess.run([str(MOVER), "--once"], env=env, check=True, capture_output=True)
    assert len((tmp_path / "log").read_text().splitlines()) == 1
    (bundle,) = [p for p in queue.iterdir() if not p.name.startswith(".")]
    assert json.loads((bundle / "manifest.json").read_bytes())["original_name"] == name


def test_quarantine_blocks_retry_and_preserves_new_submissions(tmp_path):
    source, queue, env = run_mover(tmp_path, fail=True)
    subprocess.run([str(MOVER), "--once"], env=env, check=True, capture_output=True)
    new = source.parent / "new.csv"
    new.write_text("keep")
    before = sorted(p.name for p in queue.iterdir())
    subprocess.run([str(MOVER), "--once"], env=env, check=True, capture_output=True)
    assert sorted(p.name for p in queue.iterdir()) == before
    assert new.read_text() == "keep"


def test_concurrent_mover_does_not_claim_source(tmp_path):
    import fcntl

    source, queue, env = run_mover(tmp_path)
    queue.mkdir()
    with (queue / ".mover.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        subprocess.run([str(MOVER), "--once"], env=env, check=True, capture_output=True)
    assert source.read_bytes() == b"reviewed"
    assert not list(queue.glob(".incoming.*"))


def test_main_create_verify_and_error(snapshot, tmp_path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.write_text("ok")
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(sys, "argv", ["snapshot", "create", str(source), str(bundle), "name", "id"])
    assert snapshot.main() == 0
    monkeypatch.setattr(sys, "argv", ["snapshot", "verify", str(bundle)])
    assert snapshot.main() == 0
    (bundle / "payload").write_text("changed")
    assert snapshot.main() == 1
    assert "SnapshotError" in capsys.readouterr().err


@pytest.mark.parametrize("fault", ["short_read", "growth", "zero_write", "fsync", "replace"])
def test_copy_faults_never_create_ready_manifest(snapshot, tmp_path, monkeypatch, fault):
    source = tmp_path / "source"
    source.write_bytes(b"ok")
    real_read = os.read
    real_write = os.write

    def read_fault(fd, count):
        data = real_read(fd, count)
        if fault == "short_read":
            return b""
        if fault == "growth" and not data:
            return b"extra"
        if fault == "replace" and data:
            source.unlink()
            source.write_bytes(b"replacement")
        return data

    def write_fault(fd, data):
        return 0 if fault == "zero_write" else real_write(fd, data)

    def fsync_fault(fd):
        raise OSError("fsync failed")

    monkeypatch.setattr(snapshot.os, "read", read_fault)
    monkeypatch.setattr(snapshot.os, "write", write_fault)
    if fault == "fsync":
        monkeypatch.setattr(snapshot.os, "fsync", fsync_fault)
    with pytest.raises((snapshot.SnapshotError, OSError)):
        snapshot.create(source, tmp_path / "bundle", "name", "id")
    assert not (tmp_path / "bundle/manifest.json").exists()


def test_directory_changed_during_walk(snapshot, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    real_listdir = snapshot.child_names
    count = 0

    def mutate(fd, limit):
        nonlocal count
        count += 1
        if count == 2:
            (source / "late").touch()
        return real_listdir(fd, limit)

    monkeypatch.setattr(snapshot, "child_names", mutate)
    with pytest.raises(snapshot.SnapshotError, match="source_changed"):
        snapshot.create(source, tmp_path / "bundle", "name", "id")


def test_unknown_uid_is_recorded_numerically(snapshot, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.touch()

    def no_account(uid):
        raise KeyError(uid)

    monkeypatch.setattr(snapshot.pwd, "getpwuid", no_account)
    manifest = snapshot.create(source, tmp_path / "bundle", "name", "id")
    assert manifest["requester"]["username"] == str(os.getuid())


def test_mixed_ownership_is_rejected(snapshot, tmp_path, monkeypatch):
    from types import SimpleNamespace

    source = tmp_path / "source"
    source.mkdir()
    (source / "child").touch()
    real_fstat = os.fstat

    def other_owner(fd):
        st = real_fstat(fd)
        if snapshot.stat.S_ISREG(st.st_mode):
            return SimpleNamespace(st_uid=st.st_uid + 1)
        return st

    monkeypatch.setattr(snapshot.os, "fstat", other_owner)
    with pytest.raises(snapshot.SnapshotError, match="mixed_owner"):
        snapshot.create(source, tmp_path / "bundle", "name", "id")


def test_directory_listing_is_bounded(snapshot, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("a", "b", "c"):
        (source / name).touch()
    monkeypatch.setattr(snapshot, "MAX_ENTRIES", 2)
    with pytest.raises(snapshot.SnapshotError, match="limit_exceeded"):
        snapshot.create(source, tmp_path / "bundle", "name", "id")


def test_malformed_manifest_returns_failure(snapshot, tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text("[]")
    monkeypatch.setattr(sys, "argv", ["snapshot", "verify", str(tmp_path)])
    assert snapshot.main() == 1


@pytest.mark.parametrize("fault", ["rename", "sync", "logger"])
def test_publication_failure_does_not_delete_captured_source(tmp_path, fault):
    _, queue, env = run_mover(tmp_path)
    tool = {"rename": "mv", "sync": "sync", "logger": "logger"}[fault]
    stub = tmp_path / "bin" / tool
    body = 'case "$3" in */bundle) exit 1;; esac\nexec /usr/bin/mv "$@"' if fault == "rename" else "exit 1"
    stub.write_text("#!/bin/sh\n" + body + "\n")
    stub.chmod(0o700)
    subprocess.run([str(MOVER), "--once"], env=env, check=True, capture_output=True)
    sources = list(queue.glob(".incoming.*/source"))
    assert len(sources) == 1
    assert sources[0].read_bytes() == b"reviewed"
    if fault == "rename":
        assert not [p for p in queue.iterdir() if not p.name.startswith(".")]
    else:
        assert len([p for p in queue.iterdir() if not p.name.startswith(".")]) == 1
