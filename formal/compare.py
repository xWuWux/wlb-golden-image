"""Compare both decisions on the very same staged schema-1 candidates (#352)."""

import errno
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from platform_image_cases import FAULTS, stage_candidate

from ci.verify_platform_images import CATALOG, unique_keys, verify

MODEL = Path(__file__).resolve().parent / ".lake/build/bin/compare-release"


class ObjectPairs(list[tuple[str, object]]):
    """A JSON object with all keys in input order, including duplicates."""


def fields(value: object, expected: set[str]) -> dict[str, object]:
    if not isinstance(value, ObjectPairs):
        raise ValueError("expected a JSON object")
    record = unique_keys(value)
    if record.keys() != expected:
        raise ValueError(f"unexpected fields for schema 1: {record.keys()}")
    return record


def project_images(raw: str, target: str) -> list[dict[str, str | None]]:
    """Accept only the typed comparison domain; pass repeated variant names through to Lean."""
    header = fields(json.loads(raw, object_pairs_hook=ObjectPairs), {"schema", "version", "images"})
    if type(header["schema"]) is not int or header["schema"] != 1 or header["version"] != target:
        raise ValueError("expected schema 1 and matching target version")
    if not isinstance(header["images"], ObjectPairs):
        raise ValueError("expected an images object")
    images = []
    for name, value in header["images"]:
        row = fields(value, {"version", "sha256", "base_sha256"})
        version, digest, base = row["version"], row["sha256"], row["base_sha256"]
        if not isinstance(version, str) or not isinstance(digest, str) or not (base is None or isinstance(base, str)):
            raise ValueError("unexpected record types")
        images.append({"name": name, "version": version, "digest": digest, "baseDigest": base})
    return images


def observe(path: Path) -> list[tuple[str, str]]:
    """Hash bounded chunks of each eligible open file in the private fixture directory."""
    files = []
    for image in path.glob("*.qcow2"):
        try:
            fd = os.open(image, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOENT):
                continue
            raise
        try:
            metadata = os.fstat(fd)
            if stat.S_ISREG(metadata.st_mode) and metadata.st_size:
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    files.append((image.stem, hashlib.file_digest(stream, "sha256").hexdigest()))
        finally:
            os.close(fd)
    return files


def compare(directory: Path, case: str, catalog: dict[str, str | None]) -> None:
    manifest = stage_candidate(directory, case)
    target = "1.2.0"
    model_input = {
        "target": target,
        "catalog": [{"name": name, "parent": parent} for name, parent in catalog.items()],
        "images": project_images(manifest.read_text(), target),
        "files": observe(directory),
    }
    result = subprocess.run(  # noqa: S603 -- fixed path to the locally built model
        [MODEL], input=json.dumps(model_input), text=True, capture_output=True, check=True, timeout=10
    )
    decision = json.loads(result.stdout)
    try:
        verify(target, manifest, directory)
        python_ok = True
    except ValueError:
        python_ok = False
    expected = case not in FAULTS
    if decision is not expected or python_ok is not expected:
        raise ValueError(f"{case}: expected={expected}, Lean={decision}, Python={python_ok}")


if __name__ == "__main__":
    catalog = json.loads(CATALOG.read_text(), object_pairs_hook=unique_keys)
    cases = ["none", "reordered", *FAULTS]
    for case in cases:
        with TemporaryDirectory() as tmp:
            compare(Path(tmp), case, catalog)
    print(f"{len(cases)} shared Python/Lean cases passed")
