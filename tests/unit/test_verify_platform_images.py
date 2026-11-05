"""Image completeness and base identity for the platform release (#224)."""

import hashlib
import json
from pathlib import Path

import pytest

from ci.verify_platform_images import CATALOG, unique_keys, verify


def test_catalog_covers_packer_variants():
    names = {p.name.removesuffix(".pkr.hcl") for p in (CATALOG.parents[1] / "packer").glob("wlb-*.pkr.hcl")}
    assert set(json.loads(CATALOG.read_text())) == names


@pytest.mark.parametrize(
    "fault", ["none", "missing", "unknown", "different-base", "tampered", "version", "empty", "link"]
)
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
        with pytest.raises(ValueError):
            verify("1.2.0", manifest, tmp_path)


def test_duplicate_variant():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"wlb-memory": 1, "wlb-memory": 2}', object_pairs_hook=unique_keys)
