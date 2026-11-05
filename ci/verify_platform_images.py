"""Verify the image subset of a WLB platform release candidate (#224)."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "release/image-catalog.json"
VERSION = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}")


def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def verify(version: str, manifest: Path, directory: Path) -> None:
    """Check an explicitly staged, trusted CI directory against catalog and candidate."""
    if not VERSION.fullmatch(version):
        raise ValueError("expected target version X.Y.Z")
    catalog = json.loads(CATALOG.read_text(), object_pairs_hook=unique_keys)
    candidate = json.loads(manifest.read_text(), object_pairs_hook=unique_keys)
    if not isinstance(candidate, dict) or set(candidate) != {"schema", "version", "images"}:
        raise ValueError("invalid candidate fields")
    if type(candidate["schema"]) is not int or candidate["schema"] != 1 or candidate["version"] != version:
        raise ValueError("invalid schema or target version")
    images = candidate["images"]
    if not isinstance(images, dict) or images.keys() != catalog.keys():
        raise ValueError("image set differs from the release catalog")
    for name in catalog:
        record = images[name]
        if not isinstance(record, dict) or set(record) != {"version", "sha256", "base_sha256"}:
            raise ValueError(f"{name}: invalid image record")
        if record["version"] != version:
            raise ValueError(f"{name}: unexpected image version")
        path = directory / f"{name}.qcow2"
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"{name}: expected a nonempty regular image file")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if record["sha256"] != digest:
            raise ValueError(f"{name}: image digest mismatch")
    for name, parent in catalog.items():
        expected = images[parent]["sha256"] if parent else None
        if images[name]["base_sha256"] != expected:
            raise ValueError(f"{name}: unexpected base digest")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="target platform version X.Y.Z")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("directory", type=Path, help="trusted staging directory containing <variant>.qcow2")
    args = parser.parse_args()
    try:
        verify(args.version, args.manifest, args.directory)
    except (OSError, ValueError) as exc:
        print(f"invalid platform image set: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
