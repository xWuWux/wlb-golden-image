"""Wiązanie qcow2 wydania z manifestem Packera i sumą kontrolną (#277-S3).

`ci/release.sh` nie może ufać ścieżce złożonej z pól `image-release`: musi wykazać,
że kontrolowany plik to dokładnie artefakt opisany przez manifest tego builda i przez
sumę `.qcow2.sha256`. Dzięki temu bramka E2E działa na zweryfikowanym obrazie, a nie
na przypadkowym qcow2 z `output/`.

Waliduje:
  - metadane `image-release` (nazwa, wersja, data, commit, dirty=0) i ich zgodność
    z katalogiem artefaktów oraz tagiem/HEAD przekazanym przez release.sh;
  - manifest leży w katalogu obrazu (bez `find ... | head -1`);
  - `custom_data` manifestu (wersja, data, commit, dirty, build_run);
  - `files[]` manifestu: dokładnie jeden qcow2 o nazwie i rozmiarze obrazu;
  - `.qcow2.sha256`: 64 hex, wskazuje ten sam plik i zgadza się z rzeczywistą sumą.

Kod 0 = obraz związany z manifestem i sumą; 2 = nie można tego wykazać (fail-closed).
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

NAME_RE = re.compile(r"wlb-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
DATE_RE = re.compile(r"[0-9]{8}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

REQUIRED_KEYS = (
    "WLB_IMAGE_NAME",
    "WLB_IMAGE_VERSION",
    "WLB_IMAGE_DATE",
    "WLB_GIT_COMMIT",
    "WLB_GIT_DIRTY",
)


class ProvenanceError(ValueError):
    """Obraz nie jest jednoznacznie powiązany z manifestem i sumą wydania."""


def read_metadata(path: Path) -> dict[str, str]:
    """Czyta `image-release` jako KEY=VALUE; duplikat klucza to błąd (niejednoznaczność)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProvenanceError(f"nie można odczytać {path}: {exc}") from exc

    values: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        key, sep, raw = text.partition("=")
        if not sep:
            raise ProvenanceError(f"{path}:{number}: wiersz bez '=': {text!r}")
        key = key.strip()
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            raise ProvenanceError(f"{path}:{number}: nieprawidłowa nazwa klucza: {key!r}")
        if key in values:
            raise ProvenanceError(f"{path}:{number}: duplikat klucza {key}")
        values[key] = raw.strip()

    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        raise ProvenanceError(f"{path}: brak wartości dla {', '.join(missing)}")
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProvenanceError(f"nie można policzyć sumy {path}: {exc}") from exc
    return digest.hexdigest()


def read_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProvenanceError(f"nie można odczytać manifestu {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"manifest {path} nie jest poprawnym JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProvenanceError(f"manifest {path}: oczekiwano obiektu JSON")
    builds = data.get("builds")
    if not isinstance(builds, list) or not builds:
        raise ProvenanceError(f"manifest {path}: brak niepustej listy 'builds'")
    return data


def file_entries(build: dict, image_name: str) -> list[dict]:
    files = build.get("files")
    if not isinstance(files, list):
        return []
    return [entry for entry in files if isinstance(entry, dict) and Path(str(entry.get("name", ""))).name == image_name]


def validate_build(manifest: dict, image: Path, metadata: dict[str, str], version: str) -> dict:
    builds = [build for build in manifest["builds"] if isinstance(build, dict)]
    matching = [build for build in builds if file_entries(build, image.name)]
    if len(matching) != 1:
        raise ProvenanceError(
            f"manifest musi opisywać dokładnie jeden build z plikiem {image.name} (znaleziono {len(matching)})"
        )
    build = matching[0]

    custom = build.get("custom_data")
    if not isinstance(custom, dict):
        raise ProvenanceError("manifest: build bez obiektu 'custom_data'")
    expected = {
        "image_version": version,
        "image_date": metadata["WLB_IMAGE_DATE"],
        "git_commit": metadata["WLB_GIT_COMMIT"],
        "git_dirty": "0",
    }
    for key, want in expected.items():
        got = str(custom.get(key, ""))
        if got != want:
            raise ProvenanceError(f"manifest: custom_data.{key}={got!r}, oczekiwano {want!r}")
    build_run = metadata.get("WLB_BUILD_RUN", "")
    manifest_run = str(custom.get("build_run", ""))
    if build_run and manifest_run and build_run != manifest_run:
        raise ProvenanceError(f"manifest: build_run={manifest_run!r}, a image-release mówi {build_run!r}")

    entries = file_entries(build, image.name)
    size = entries[0].get("size")
    actual_size = image.stat().st_size
    if not isinstance(size, int) or size != actual_size:
        raise ProvenanceError(f"manifest: rozmiar {image.name}={size!r}, a plik ma {actual_size} B")
    return build


def validate_checksum(checksum: Path, image: Path) -> str:
    try:
        fields = checksum.read_text(encoding="utf-8").split()
    except OSError as exc:
        raise ProvenanceError(f"nie można odczytać sumy {checksum}: {exc}") from exc
    if len(fields) != 2:
        raise ProvenanceError(f"{checksum}: oczekiwano '<sha256>  <plik>', jest {fields!r}")
    digest, filename = fields
    if filename.startswith("*"):
        filename = filename[1:]
    if not SHA256_RE.fullmatch(digest):
        raise ProvenanceError(f"{checksum}: suma nie jest 64 małymi cyframi hex")
    if Path(filename).name != image.name:
        raise ProvenanceError(f"{checksum}: suma dotyczy {filename!r}, a nie {image.name!r}")
    actual = sha256_file(image)
    if actual != digest:
        raise ProvenanceError(f"{checksum}: suma {digest} nie zgadza się z obrazem {image} ({actual})")
    return digest


def validate(args: argparse.Namespace) -> dict[str, str]:
    artifacts = Path(args.artifacts)
    image = Path(args.image)
    manifest = Path(args.manifest)
    checksum = Path(args.checksum)

    if not artifacts.is_dir():
        raise ProvenanceError(f"katalog artefaktów nie istnieje: {artifacts}")
    metadata = read_metadata(artifacts / "image-release")

    name = metadata["WLB_IMAGE_NAME"]
    date = metadata["WLB_IMAGE_DATE"]
    commit = metadata["WLB_GIT_COMMIT"]
    if not NAME_RE.fullmatch(name):
        raise ProvenanceError(f"image-release: nieprawidłowa nazwa obrazu {name!r}")
    if not DATE_RE.fullmatch(date):
        raise ProvenanceError(f"image-release: data musi mieć format YYYYMMDD, jest {date!r}")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError as exc:
        raise ProvenanceError(f"image-release: nieprawidłowa data {date!r}: {exc}") from exc
    if not VERSION_RE.fullmatch(metadata["WLB_IMAGE_VERSION"]):
        raise ProvenanceError(f"image-release: nieprawidłowa wersja {metadata['WLB_IMAGE_VERSION']!r}")
    if not COMMIT_RE.fullmatch(commit):
        raise ProvenanceError(f"image-release: commit musi być pełnym SHA-1, jest {commit!r}")
    if metadata["WLB_GIT_DIRTY"] != "0":
        raise ProvenanceError(f"image-release: obraz z brudnego drzewa (WLB_GIT_DIRTY={metadata['WLB_GIT_DIRTY']})")

    if metadata["WLB_IMAGE_VERSION"] != args.version:
        raise ProvenanceError(f"image-release: wersja {metadata['WLB_IMAGE_VERSION']!r}, a tag mówi {args.version!r}")
    if commit != args.commit:
        raise ProvenanceError(f"image-release: commit {commit}, a HEAD to {args.commit}")

    full_name = f"{name}-{args.version}-{date}"
    if artifacts.name != full_name:
        raise ProvenanceError(f"katalog artefaktów {artifacts.name!r} nie odpowiada metadanym {full_name!r}")
    if image.name != f"{full_name}.qcow2" or image.parent.name != full_name:
        raise ProvenanceError(f"obraz {image} nie leży w output/{full_name}/{full_name}.qcow2")
    if image.parent.parent.name != "output":
        raise ProvenanceError(f"obraz {image} nie leży w katalogu output/")
    if image.is_symlink():
        raise ProvenanceError(f"obraz {image} jest symlinkiem — nie weryfikujemy celu")
    if not image.is_file():
        raise ProvenanceError(f"obraz nie istnieje: {image}")

    expected_manifest = image.parent / "packer-manifest.json"
    if manifest.is_symlink() or manifest.resolve() != expected_manifest.resolve():
        raise ProvenanceError(f"manifest {manifest} nie jest manifestem tego obrazu ({expected_manifest})")
    if not manifest.is_file():
        raise ProvenanceError(f"manifest nie istnieje: {manifest}")

    expected_checksum = image.with_name(image.name + ".sha256")
    if checksum.is_symlink() or checksum.resolve() != expected_checksum.resolve():
        raise ProvenanceError(f"suma {checksum} nie jest sumą tego obrazu ({expected_checksum})")

    manifest_data = read_manifest(manifest)
    validate_build(manifest_data, image, metadata, args.version)
    digest = validate_checksum(checksum, image)
    return {"full_name": full_name, "sha256": digest}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Powiąż qcow2 wydania z manifestem i sumą (#277-S3)")
    parser.add_argument("--artifacts", required=True, metavar="DIR", help="katalog metadanych builda")
    parser.add_argument("--image", required=True, metavar="IMG", help="qcow2 wydania")
    parser.add_argument("--manifest", required=True, metavar="JSON", help="packer-manifest.json")
    parser.add_argument("--checksum", required=True, metavar="FILE", help="<obraz>.qcow2.sha256")
    parser.add_argument("--version", required=True, metavar="X.Y.Z", help="wersja z tagu")
    parser.add_argument("--commit", required=True, metavar="SHA", help="pełny SHA HEAD")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = validate(args)
    except ProvenanceError as exc:
        print(f"release-provenance: {exc}", file=sys.stderr)
        return 2
    print(f"release-provenance: OK ({result['full_name']}, sha256={result['sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
