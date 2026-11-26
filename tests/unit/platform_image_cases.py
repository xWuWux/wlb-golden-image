"""Shared schema-1 fixtures for the Python validator and the Lean comparison (#352)."""

import hashlib
import json
from pathlib import Path

from ci.verify_platform_images import CATALOG

FAULTS = {
    "duplicate-variant": "duplicate JSON key",
    "root-base": "unexpected base digest",
    "absent-file": "expected a nonempty regular image file",
    "missing": "image set differs from the release catalog",
    "unknown": "image set differs from the release catalog",
    "different-base": "unexpected base digest",
    "tampered": "image digest mismatch",
    "version": "unexpected image version",
    "empty": "expected a nonempty regular image file",
    "link": "expected a nonempty regular image file",
}


def stage_candidate(tmp_path: Path, fault: str) -> Path:
    catalog = json.loads(CATALOG.read_text())
    digest = {name: hashlib.sha256(name.encode()).hexdigest() for name in catalog}
    records = {}
    for name, parent in catalog.items():
        (tmp_path / f"{name}.qcow2").write_bytes(name.encode())
        records[name] = {"sha256": digest[name], "version": "1.2.0", "base_sha256": digest[parent] if parent else None}
    child = next(name for name, parent in catalog.items() if parent is not None)
    derived = tmp_path / f"{child}.qcow2"
    if fault == "missing":
        del records[child]
    elif fault == "unknown":
        records["other"] = records[child]
    elif fault == "different-base":
        records[child]["base_sha256"] = digest[child]
    elif fault == "tampered":
        derived.write_bytes(b"changed")
    elif fault == "version":
        records[child]["version"] = "1.1.0"
    elif fault == "empty":
        derived.write_bytes(b"")
    elif fault == "link":
        derived.rename(tmp_path / "other")
        derived.symlink_to(tmp_path / "other")
    elif fault == "root-base":
        root = next(name for name, parent in catalog.items() if parent is None)
        records[root]["base_sha256"] = digest[root]
    elif fault == "absent-file":
        derived.unlink()
    elif fault == "reordered":
        records = dict(reversed(records.items()))
    elif fault not in ("none", "duplicate-variant"):
        raise ValueError(f"unknown test case: {fault}")
    manifest = tmp_path / "candidate.json"
    if fault == "duplicate-variant":
        entries = [*records.items(), (child, records[child])]
        pairs = ", ".join(f"{json.dumps(key)}: {json.dumps(value)}" for key, value in entries)
        manifest.write_text('{"schema": 1, "version": "1.2.0", "images": {' + pairs + "}}")
    else:
        manifest.write_text(json.dumps({"schema": 1, "version": "1.2.0", "images": records}))
    return manifest
