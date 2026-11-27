"""Testy wiązania qcow2 wydania z manifestem Packera i sumą (#277-S3).

Sprawdzają fail-closed: obcy manifest, niezgodne custom_data, zły rozmiar, suma
innego pliku albo brak sumy muszą zatrzymać wydanie przed bramką E2E.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import REPO_ROOT, load_script

COMMIT = "a" * 40
VERSION = "1.2.3"
DATE = "20260101"
FULL = f"wlb-general-{VERSION}-{DATE}"


@pytest.fixture(scope="module")
def provenance():
    return load_script("wlb_release_provenance", REPO_ROOT / "ci/release_provenance.py")


def manifest_payload(size: int, **overrides) -> dict:
    custom = {
        "image_version": VERSION,
        "image_date": DATE,
        "git_commit": COMMIT,
        "git_dirty": "0",
        "build_run": "local",
    }
    custom.update(overrides)
    return {
        "builds": [
            {
                "name": "wlb",
                "builder_type": "qemu",
                "files": [{"name": f"{FULL}.qcow2", "size": size}],
                "artifact_id": "VM",
                "custom_data": custom,
            }
        ],
        "last_run_uuid": "test",
    }


def make_release(tmp_path: Path, *, image_bytes: bytes = b"qcow2-data") -> SimpleNamespace:
    out = tmp_path / "output" / FULL
    out.mkdir(parents=True)
    image = out / f"{FULL}.qcow2"
    image.write_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    checksum = out / f"{FULL}.qcow2.sha256"
    checksum.write_text(f"{digest}  {image.name}\n", encoding="utf-8")
    manifest = out / "packer-manifest.json"
    manifest.write_text(json.dumps(manifest_payload(len(image_bytes))), encoding="utf-8")
    artifacts = tmp_path / "build/artifacts" / FULL
    artifacts.mkdir(parents=True)
    (artifacts / "image-release").write_text(
        "\n".join(
            [
                "WLB_IMAGE_NAME=wlb-general",
                f"WLB_IMAGE_VERSION={VERSION}",
                f"WLB_IMAGE_DATE={DATE}",
                f"WLB_GIT_COMMIT={COMMIT}",
                "WLB_GIT_DIRTY=0",
                "WLB_BUILD_RUN=local",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(
        out=out,
        image=image,
        checksum=checksum,
        manifest=manifest,
        artifacts=artifacts,
        version=VERSION,
        commit=COMMIT,
    )


def argv(release: SimpleNamespace, **overrides) -> list[str]:
    values = {
        "artifacts": str(release.artifacts),
        "image": str(release.image),
        "manifest": str(release.manifest),
        "checksum": str(release.checksum),
        "version": release.version,
        "commit": release.commit,
    }
    values.update(overrides)
    return [
        "--artifacts",
        values["artifacts"],
        "--image",
        values["image"],
        "--manifest",
        values["manifest"],
        "--checksum",
        values["checksum"],
        "--version",
        values["version"],
        "--commit",
        values["commit"],
    ]


def rewrite_manifest(release: SimpleNamespace, **overrides) -> None:
    payload = manifest_payload(release.image.stat().st_size, **overrides)
    release.manifest.write_text(json.dumps(payload), encoding="utf-8")


def test_valid_release_is_bound_to_manifest_and_checksum(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    assert provenance.main(argv(release)) == 0
    out = capsys.readouterr().out
    assert FULL in out
    assert "sha256=" in out


def test_manifest_from_other_directory_is_rejected(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    other = tmp_path / "packer-manifest.json"
    other.write_text(json.dumps(manifest_payload(release.image.stat().st_size)), encoding="utf-8")
    assert provenance.main(argv(release, manifest=str(other))) == 2
    assert "manifestem tego obrazu" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("image_version", "9.9.9", "custom_data.image_version"),
        ("image_date", "20250101", "custom_data.image_date"),
        ("git_commit", "b" * 40, "custom_data.git_commit"),
        ("git_dirty", "1", "custom_data.git_dirty"),
        ("build_run", "inny", "build_run"),
    ],
)
def test_manifest_custom_data_must_match(provenance, tmp_path, capsys, field: str, value: str, message: str) -> None:
    release = make_release(tmp_path)
    rewrite_manifest(release, **{field: value})
    assert provenance.main(argv(release)) == 2
    assert message in capsys.readouterr().err


def test_manifest_size_must_match_image(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    release.manifest.write_text(json.dumps(manifest_payload(release.image.stat().st_size + 1)), encoding="utf-8")
    assert provenance.main(argv(release)) == 2
    assert "rozmiar" in capsys.readouterr().err


def test_manifest_must_describe_exactly_one_image(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    payload = manifest_payload(release.image.stat().st_size)
    payload["builds"][0]["files"][0]["name"] = "inny.qcow2"
    release.manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert provenance.main(argv(release)) == 2
    assert "dokładnie jeden build" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("nie-hex  plik.qcow2\n", "64 małymi cyframi hex"),
        ("0" * 64 + "  inny.qcow2\n", "suma dotyczy"),
        ("0" * 64 + f"  {FULL}.qcow2\n", "nie zgadza się z obrazem"),
    ],
)
def test_checksum_must_describe_this_image(provenance, tmp_path, capsys, content: str, message: str) -> None:
    release = make_release(tmp_path)
    release.checksum.write_text(content, encoding="utf-8")
    assert provenance.main(argv(release)) == 2
    assert message in capsys.readouterr().err


def test_artifacts_directory_must_match_metadata(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    foreign = tmp_path / "build/artifacts/art-e2e"
    foreign.mkdir(parents=True)
    (foreign / "image-release").write_text(
        (release.artifacts / "image-release").read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert provenance.main(argv(release, artifacts=str(foreign))) == 2
    assert "nie odpowiada metadanym" in capsys.readouterr().err


def test_duplicate_metadata_key_is_rejected(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    metadata = release.artifacts / "image-release"
    metadata.write_text(metadata.read_text(encoding="utf-8") + f"WLB_IMAGE_VERSION={VERSION}\n", encoding="utf-8")
    assert provenance.main(argv(release)) == 2
    assert "duplikat klucza" in capsys.readouterr().err


def test_invalid_date_is_rejected(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    metadata = release.artifacts / "image-release"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(f"WLB_IMAGE_DATE={DATE}", "WLB_IMAGE_DATE=20260231"),
        encoding="utf-8",
    )
    assert provenance.main(argv(release)) == 2
    assert "nieprawidłowa data" in capsys.readouterr().err


def test_dirty_tree_is_rejected(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    metadata = release.artifacts / "image-release"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace("WLB_GIT_DIRTY=0", "WLB_GIT_DIRTY=1"),
        encoding="utf-8",
    )
    assert provenance.main(argv(release)) == 2
    assert "brudnego drzewa" in capsys.readouterr().err


def test_image_symlink_is_rejected(provenance, tmp_path, capsys) -> None:
    release = make_release(tmp_path)
    target = tmp_path / "target.qcow2"
    release.image.rename(target)
    release.image.symlink_to(target)
    assert provenance.main(argv(release)) == 2
    assert "symlinkiem" in capsys.readouterr().err
