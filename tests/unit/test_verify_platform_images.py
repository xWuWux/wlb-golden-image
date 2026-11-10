"""Image completeness and base identity for the platform release (#224)."""

import hashlib
import json
from pathlib import Path

import pytest

from ci.verify_platform_images import CATALOG, unique_keys, verify


def test_catalog_covers_packer_variants():
    names = {p.name.removesuffix(".pkr.hcl") for p in (CATALOG.parents[1] / "packer").glob("wlb-*.pkr.hcl")}
    assert set(json.loads(CATALOG.read_text())) == names


FAULTS = {
    "missing": "image set differs from the release catalog",
    "unknown": "image set differs from the release catalog",
    "different-base": "unexpected base digest",
    "tampered": "image digest mismatch",
    "version": "unexpected image version",
    "empty": "expected a nonempty regular image file",
    "link": "expected a nonempty regular image file",
}


@pytest.mark.parametrize("fault", ["none", *FAULTS])
def test_candidate(tmp_path: Path, fault: str):
    catalog = json.loads(CATALOG.read_text())
    digest = {name: hashlib.sha256(name.encode()).hexdigest() for name in catalog}
    records = {}
    for name, parent in catalog.items():
        (tmp_path / f"{name}.qcow2").write_bytes(name.encode())
        records[name] = {"sha256": digest[name], "version": "1.2.0", "base_sha256": digest[parent] if parent else None}
    derived = tmp_path / "wlb-memory.qcow2"
    if fault == "missing":
        del records["wlb-radiologia"]
    elif fault == "unknown":
        records["other"] = records["wlb-memory"]
    elif fault == "different-base":
        records["wlb-memory"]["base_sha256"] = digest["wlb-memory"]
    elif fault == "tampered":
        derived.write_bytes(b"changed")
    elif fault == "version":
        records["wlb-memory"]["version"] = "1.1.0"
    elif fault == "empty":
        derived.write_bytes(b"")
    elif fault == "link":
        derived.rename(tmp_path / "other")
        derived.symlink_to(tmp_path / "other")
    manifest = tmp_path / "candidate.json"
    manifest.write_text(json.dumps({"schema": 1, "version": "1.2.0", "images": records}))
    if fault == "none":
        verify("1.2.0", manifest, tmp_path)
    else:
        with pytest.raises(ValueError, match=FAULTS[fault]):
            verify("1.2.0", manifest, tmp_path)


def test_duplicate_variant():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"wlb-memory": 1, "wlb-memory": 2}', object_pairs_hook=unique_keys)


def _candidate(tmp_path: Path, payload: object) -> Path:
    manifest = tmp_path / "candidate.json"
    manifest.write_text(json.dumps(payload))
    return manifest


def test_manifest_duplicate_key_is_rejected(tmp_path: Path):
    # Duplikat klucza w manifeście musi zostać odrzucony przez object_pairs_hook=unique_keys.
    manifest = tmp_path / "candidate.json"
    manifest.write_text('{"schema": 1, "schema": 2, "version": "1.2.0", "images": {}}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        verify("1.2.0", manifest, tmp_path)


def test_catalog_duplicate_key_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"wlb-general": null, "wlb-general": null}')
    monkeypatch.setattr("ci.verify_platform_images.CATALOG", catalog)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        verify("1.2.0", _candidate(tmp_path, {"schema": 1, "version": "1.2.0", "images": {}}), tmp_path)


def test_candidate_must_be_a_dict(tmp_path: Path):
    with pytest.raises(ValueError, match=r"^invalid candidate fields$"):
        verify("1.2.0", _candidate(tmp_path, ["schema", "version", "images"]), tmp_path)


def test_candidate_missing_field_is_rejected(tmp_path: Path):
    # Guard pól musi odrzucić brak "images" jako ValueError, nie KeyError/TypeError.
    with pytest.raises(ValueError, match=r"^invalid candidate fields$"):
        verify("1.2.0", _candidate(tmp_path, {"schema": 1, "version": "1.2.0"}), tmp_path)


def test_candidate_extra_field_is_rejected(tmp_path: Path):
    payload = {"schema": 1, "version": "1.2.0", "images": {}, "extra": True}
    with pytest.raises(ValueError, match=r"^invalid candidate fields$"):
        verify("1.2.0", _candidate(tmp_path, payload), tmp_path)


def test_schema_must_be_one(tmp_path: Path):
    with pytest.raises(ValueError, match=r"^invalid schema or target version$"):
        verify("1.2.0", _candidate(tmp_path, {"schema": 2, "version": "1.2.0", "images": {}}), tmp_path)


def test_top_level_version_must_match(tmp_path: Path):
    with pytest.raises(ValueError, match=r"^invalid schema or target version$"):
        verify("1.2.0", _candidate(tmp_path, {"schema": 1, "version": "1.1.0", "images": {}}), tmp_path)


def test_images_must_be_a_dict(tmp_path: Path):
    payload = {"schema": 1, "version": "1.2.0", "images": ["wlb-general"]}
    with pytest.raises(ValueError, match=r"^image set differs from the release catalog$"):
        verify("1.2.0", _candidate(tmp_path, payload), tmp_path)


def test_record_must_be_a_dict(tmp_path: Path):
    catalog = json.loads(CATALOG.read_text())
    payload = {"schema": 1, "version": "1.2.0", "images": {name: "not-a-record" for name in catalog}}
    with pytest.raises(ValueError, match="invalid image record"):
        verify("1.2.0", _candidate(tmp_path, payload), tmp_path)


def test_one_byte_image_is_digest_mismatch(tmp_path: Path):
    catalog = json.loads(CATALOG.read_text())
    images = {}
    for name, parent in catalog.items():
        (tmp_path / f"{name}.qcow2").write_bytes(b"x")
        images[name] = {
            "sha256": hashlib.sha256(name.encode()).hexdigest(),
            "version": "1.2.0",
            "base_sha256": hashlib.sha256(parent.encode()).hexdigest() if parent else None,
        }
    payload = {"schema": 1, "version": "1.2.0", "images": images}
    with pytest.raises(ValueError, match="image digest mismatch"):
        verify("1.2.0", _candidate(tmp_path, payload), tmp_path)


def test_target_version_format_is_rejected(tmp_path: Path):
    # "1.2" nie jest X.Y.Z — walidacja wersji docelowej musi odrzucić ją własnym komunikatem.
    with pytest.raises(ValueError, match=r"^expected target version X\.Y\.Z$"):
        verify("1.2", _candidate(tmp_path, {"schema": 1, "version": "1.2", "images": {}}), tmp_path)


def test_record_with_wrong_fields_is_rejected(tmp_path: Path):
    # Guard rekordu musi odrzucić dict z niepełnym zestawem pól jako ValueError, nie KeyError.
    catalog = json.loads(CATALOG.read_text())
    images = {name: {"version": "1.2.0"} for name in catalog}
    payload = {"schema": 1, "version": "1.2.0", "images": images}
    with pytest.raises(ValueError, match=r"^wlb-general: invalid image record$"):
        verify("1.2.0", _candidate(tmp_path, payload), tmp_path)
