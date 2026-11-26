"""Compare both decisions on the very same staged schema-1 candidates (#352)."""

import hashlib
import json
import stat
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from platform_image_cases import FAULTS, stage_candidate

from ci.verify_platform_images import CATALOG, verify

MODEL = Path(__file__).resolve().parent / ".lake/build/bin/compare-release"


def observe(path: Path) -> list[tuple[str, str]]:
    """Independently project each eligible staged file to its name and actual digest."""
    files = []
    for image in path.glob("*.qcow2"):
        metadata = image.lstat()
        if stat.S_ISREG(metadata.st_mode) and metadata.st_size:
            files.append((image.stem, hashlib.sha256(image.read_bytes()).hexdigest()))
    return files


def compare(directory: Path, case: str, catalog: dict[str, str | None]) -> None:
    manifest = stage_candidate(directory, case)
    candidate = json.loads(manifest.read_text())
    target = "1.2.0"
    model_input = {
        "target": target,
        "catalog": [{"name": name, "parent": parent} for name, parent in catalog.items()],
        "images": [
            {"name": name, "version": row["version"], "digest": row["sha256"], "baseDigest": row["base_sha256"]}
            for name, row in candidate["images"].items()
        ],
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
    catalog = json.loads(CATALOG.read_text())
    cases = ["none", "reordered", *FAULTS]
    for case in cases:
        with TemporaryDirectory() as tmp:
            compare(Path(tmp), case, catalog)
    print(f"{len(cases)} shared Python/Lean cases passed")
