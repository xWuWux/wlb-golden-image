"""#20 E1: resolve one verified v1 export bundle by request UUID."""

# ruff: noqa: S603 - subprocess arguments are fixed test paths, never shell input.

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from conftest import REPO_ROOT, load_script

SCRIPT = REPO_ROOT / "ansible/roles/storage/files/wlb-export-snapshot"
REQUEST_ID = UUID("c76ae24c-441d-4b8c-8b13-809b522e04e5")
OTHER_ID = UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def snapshot():
    return load_script("wlb_export_snapshot", SCRIPT)


def make_bundle(
    snapshot,
    queue: Path,
    name: str,
    *,
    content: bytes = b"ok",
    request_id: UUID = REQUEST_ID,
    directory: bool = False,
):
    source = queue.parent / f"source-{name}"
    if directory:
        source.mkdir()
        (source / "empty").mkdir()
        (source / "result.csv").write_bytes(content)
    else:
        source.write_bytes(content)
    bundle = queue / name
    manifest = snapshot.create(source, bundle, source.name, str(request_id))
    return bundle, manifest


def test_resolve_file_returns_verified_bundle(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, manifest = make_bundle(snapshot, queue, "20260101T000000Z_u01_result.csv")
    result = snapshot.resolve_request(queue, REQUEST_ID)
    assert result.request_id == REQUEST_ID
    assert result.bundle == bundle
    assert result.manifest == manifest
    assert result.manifest_sha256 == hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()
    assert result.payload_digest == manifest["sha256"]
    assert result.digest_algorithm == "sha256-file"
    assert snapshot.verify(result.bundle) == manifest


def test_resolve_directory_returns_verified_bundle(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, _manifest = make_bundle(snapshot, queue, "20260101T000000Z_u01_tree", directory=True)
    result = snapshot.resolve_request(queue, REQUEST_ID)
    assert result.bundle == bundle
    assert result.digest_algorithm == "sha256-inventory-v1"
    assert [entry["path"] for entry in result.manifest["entries"]] == [".", "empty", "result.csv"]


def test_resolve_selects_by_uuid_among_several_bundles(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    first, _ = make_bundle(snapshot, queue, "first", content=b"first", request_id=OTHER_ID)
    second, manifest = make_bundle(snapshot, queue, "second", content=b"second", request_id=REQUEST_ID)
    result = snapshot.resolve_request(queue, REQUEST_ID)
    assert result.bundle == second
    assert result.manifest == manifest
    assert result.bundle != first


def test_resolve_rejects_duplicate_uuid(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    make_bundle(snapshot, queue, "first")
    make_bundle(snapshot, queue, "second")
    with pytest.raises(snapshot.SnapshotError, match="duplicate_request"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_rejects_missing_uuid(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    make_bundle(snapshot, queue, "only")
    with pytest.raises(snapshot.SnapshotError, match="not_found"):
        snapshot.resolve_request(queue, OTHER_ID)


def test_resolve_rejects_legacy_without_manifest(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    legacy = queue / "legacy"
    legacy.mkdir()
    (legacy / "payload").write_bytes(b"old")
    with pytest.raises(snapshot.SnapshotError, match="legacy_entry"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_ignores_legacy_when_valid_uuid_exists(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    legacy = queue / "legacy"
    legacy.mkdir()
    (legacy / "payload").write_bytes(b"old")
    bundle, manifest = make_bundle(snapshot, queue, "valid")
    result = snapshot.resolve_request(queue, REQUEST_ID)
    assert result.bundle == bundle
    assert result.manifest == manifest


@pytest.mark.parametrize("payload", [b"", b"{}", b"not-json", b'{"request_id":"' + str(REQUEST_ID).encode() + b'"}'])
def test_resolve_rejects_bad_manifest(snapshot, tmp_path, payload):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle = queue / "bad"
    bundle.mkdir()
    (bundle / "payload").write_bytes(b"payload")
    (bundle / "manifest.json").write_bytes(payload)
    with pytest.raises(snapshot.SnapshotError, match="invalid_manifest"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_rejects_unknown_manifest_fields(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, manifest = make_bundle(snapshot, queue, "valid")
    manifest["unknown"] = "field"
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(snapshot.SnapshotError, match="invalid_manifest"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_ignores_invalid_manifest_when_valid_uuid_exists(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bad = queue / "bad"
    bad.mkdir()
    (bad / "payload").write_bytes(b"payload")
    (bad / "manifest.json").write_bytes(b"not-json")
    bundle, manifest = make_bundle(snapshot, queue, "valid")
    result = snapshot.resolve_request(queue, REQUEST_ID)
    assert result.bundle == bundle
    assert result.manifest == manifest


def test_resolve_rejects_symlink_package(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real, _ = make_bundle(snapshot, outside, "real")
    (queue / "linked").symlink_to(real, target_is_directory=True)
    with pytest.raises(snapshot.SnapshotError, match="unsafe_entry"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_rejects_symlink_manifest(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, _manifest = make_bundle(snapshot, queue, "package")
    outside = tmp_path / "manifest-outside.json"
    outside.write_bytes((bundle / "manifest.json").read_bytes())
    (bundle / "manifest.json").unlink()
    (bundle / "manifest.json").symlink_to(outside)
    with pytest.raises(snapshot.SnapshotError, match="unsafe_entry"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_keeps_verified_package_after_directory_swap(snapshot, tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, _ = make_bundle(snapshot, queue, "package")
    real_verify = snapshot.verify_open_bundle

    def swap_after_verify(package_fd, raw):
        verified = real_verify(package_fd, raw)
        moved = bundle.with_name("moved")
        bundle.rename(moved)
        bundle.mkdir()
        (bundle / "manifest.json").write_bytes((moved / "manifest.json").read_bytes())
        (bundle / "payload").write_bytes(b"UNVERIFIED")
        return verified

    monkeypatch.setattr(snapshot, "verify_open_bundle", swap_after_verify)
    with snapshot.resolve_request(queue, REQUEST_ID) as result:
        payload_fd = os.open("payload", os.O_RDONLY, dir_fd=result.package_fd)
        try:
            assert os.read(payload_fd, 100) == b"ok"
        finally:
            os.close(payload_fd)


def test_resolve_does_not_reopen_manifest_after_read(snapshot, tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, manifest = make_bundle(snapshot, queue, "package")
    manifest_path = bundle / "manifest.json"
    real_verify = snapshot.verify_open_bundle

    def swap_after_verify(package_fd, raw):
        verified = real_verify(package_fd, raw)
        manifest_path.unlink()
        os.mkfifo(manifest_path)
        return verified

    monkeypatch.setattr(snapshot, "verify_open_bundle", swap_after_verify)
    with snapshot.resolve_request(queue, REQUEST_ID) as result:
        assert result.manifest == manifest


def test_resolve_rejects_fifo_manifest(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, _ = make_bundle(snapshot, queue, "package")
    manifest_path = bundle / "manifest.json"
    manifest_path.unlink()
    os.mkfifo(manifest_path)
    with pytest.raises(snapshot.SnapshotError, match="unsafe_entry"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_requires_uuid_type(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    with pytest.raises(TypeError, match="UUID"):
        snapshot.resolve_request(queue, str(REQUEST_ID))


def test_resolve_cli_prints_metadata_only(snapshot, tmp_path):
    import subprocess
    import sys

    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, manifest = make_bundle(snapshot, queue, "20261119_u01_sensitive.csv")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "resolve", str(queue), str(REQUEST_ID)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "digest_algorithm": manifest["digest_algorithm"],
        "manifest_sha256": hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest(),
        "payload_digest": manifest["sha256"],
        "request_id": str(REQUEST_ID),
    }
    assert "sensitive.csv" not in result.stdout
    assert "bundle" not in payload

    with_path = subprocess.run(
        [sys.executable, str(SCRIPT), "resolve", str(queue), str(REQUEST_ID), "--show-path"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert with_path.returncode == 0
    assert json.loads(with_path.stdout)["bundle"] == str(bundle)


def test_resolve_cli_returns_failure_for_missing_uuid(snapshot, tmp_path):
    import subprocess
    import sys

    queue = tmp_path / "queue"
    queue.mkdir()
    make_bundle(snapshot, queue, "package")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "resolve", str(queue), str(OTHER_ID)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "not_found" in result.stderr


def test_resolve_accepts_legal_uuid_suffix_in_basename(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, manifest = make_bundle(snapshot, queue, f"20261119_u01_result.{OTHER_ID}")
    with snapshot.resolve_request(queue, REQUEST_ID) as result:
        assert result.bundle == bundle
        assert result.manifest == manifest


def test_resolve_accepts_mover_collision_suffix(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, manifest = make_bundle(snapshot, queue, f"20261119_u01_result.{REQUEST_ID}")
    with snapshot.resolve_request(queue, REQUEST_ID) as result:
        assert result.bundle == bundle
        assert result.manifest == manifest


def test_resolve_rejects_non_v4_request_id(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    with pytest.raises(snapshot.SnapshotError, match="invalid_request_id"):
        snapshot.resolve_request(queue, UUID("11111111-1111-1111-1111-111111111111"))


def test_resolve_rejects_intermediate_queue_symlink(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    make_bundle(snapshot, queue, "package")
    parent = tmp_path / "parent"
    parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(snapshot.SnapshotError, match="unsafe_entry"):
        snapshot.resolve_request(parent / "queue", REQUEST_ID)


def test_resolve_rejects_duplicate_json_keys(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, _ = make_bundle(snapshot, queue, "package")
    text = (bundle / "manifest.json").read_text(encoding="utf-8")
    text = text.replace('"state":"pending_review"', '"state":"approved","state":"pending_review"')
    (bundle / "manifest.json").write_text(text, encoding="utf-8")
    with pytest.raises(snapshot.SnapshotError, match="invalid_manifest"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_ignores_non_utf8_manifest_when_valid_uuid_exists(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bad = queue / "bad"
    bad.mkdir()
    (bad / "payload").write_bytes(b"payload")
    (bad / "manifest.json").write_bytes(b"\xff")
    bundle, manifest = make_bundle(snapshot, queue, "valid")
    with snapshot.resolve_request(queue, REQUEST_ID) as result:
        assert result.bundle == bundle
        assert result.manifest == manifest


def test_resolve_rejects_queue_limit(snapshot, tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    make_bundle(snapshot, queue, "package")
    monkeypatch.setattr(snapshot, "MAX_QUEUE_ENTRIES", 0)
    with pytest.raises(snapshot.SnapshotError, match="limit_exceeded"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_rejects_scan_byte_limit(snapshot, tmp_path, monkeypatch):
    queue = tmp_path / "queue"
    queue.mkdir()
    make_bundle(snapshot, queue, "package")
    monkeypatch.setattr(snapshot, "MAX_SCAN_MANIFEST_BYTES", 1)
    with pytest.raises(snapshot.SnapshotError, match="limit_exceeded"):
        snapshot.resolve_request(queue, REQUEST_ID)


def test_resolve_maps_missing_payload_to_stable_error(snapshot, tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    bundle, _ = make_bundle(snapshot, queue, "package")
    (bundle / "payload").unlink()
    with pytest.raises(snapshot.SnapshotError, match="source_changed"):
        snapshot.resolve_request(queue, REQUEST_ID)
