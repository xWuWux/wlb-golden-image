"""Quarantine stale pydantic dist-info left by pip/conda overlays (#179).

Only metadata is moved; package code and conda records are never changed.
The imported version, conda record and retained METADATA must agree.
"""

import json
import sys
import sysconfig
from email.parser import Parser
from pathlib import Path


def reconcile(site: Path, conda_meta: Path, quarantine: Path, version: str) -> list[str]:
    """Validate first, then move obsolete metadata; return moved directory names.

    Paths identify this environment's site-packages, conda-meta and an external
    quarantine directory. version is the version imported by this interpreter.
    Ambiguous ownership or a conflicting quarantine entry raises ValueError.
    """
    site = site.resolve()
    quarantine = quarantine.resolve()
    if quarantine == site or site in quarantine.parents:
        raise ValueError("quarantine must be outside site-packages")
    records = []
    for path in conda_meta.glob("pydantic-*.json"):
        record = json.loads(path.read_text())
        if record.get("name") == "pydantic":
            records.append(record)
    if len(records) != 1 or records[0].get("version") != version:
        raise ValueError("imported pydantic and conda ownership/version disagree")
    active = []
    stale = []
    for path in sorted(site.glob("pydantic-*.dist-info")):
        if path.is_symlink() or not path.is_dir() or (path / "METADATA").is_symlink():
            raise ValueError(f"unsafe metadata path: {path}")
        metadata = Parser().parsestr((path / "METADATA").read_text())
        if metadata.get_all("Name") != ["pydantic"] or len(metadata.get_all("Version", [])) != 1:
            raise ValueError(f"ambiguous metadata: {path}")
        found = metadata["Version"]
        if path.name != f"pydantic-{found}.dist-info":
            raise ValueError(f"metadata directory/version disagree: {path}")
        (active if found == version else stale).append(path)
    if len(active) != 1:
        raise ValueError("expected exactly one metadata directory for imported pydantic")
    owned_metadata = (
        f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/{active[0].name}/METADATA"
    )
    if owned_metadata not in records[0].get("files", []):
        raise ValueError("active METADATA is not owned by the conda record")
    for path in stale:
        target = quarantine / path.name
        if target.exists() or target.is_symlink():
            raise ValueError(f"quarantine entry already exists: {target}")
    if stale:
        quarantine.mkdir(parents=True, exist_ok=True)
    for path in stale:
        path.rename(quarantine / path.name)
    return [path.name for path in stale]


def main() -> None:
    import pydantic

    site = Path(sysconfig.get_path("purelib")).resolve()
    if Path(pydantic.__file__).resolve().parent != site / "pydantic":
        raise ValueError("pydantic imported from outside this environment")
    moved = reconcile(site, Path(sys.prefix) / "conda-meta", Path(sys.argv[1]), pydantic.__version__)
    print(json.dumps({"changed": bool(moved), "quarantined": moved}))


if __name__ == "__main__":
    main()
