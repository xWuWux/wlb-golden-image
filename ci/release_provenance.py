"""Wiązanie qcow2 wydania z manifestem Packera i sumą kontrolną (#277-S3).

`ci/release.sh` nie może ufać ścieżce złożonej z pól `image-release`: musi wykazać,
że kontrolowany plik to dokładnie artefakt opisany przez manifest tego builda i przez
sumę `.qcow2.sha256`. Dzięki temu bramka E2E działa na zweryfikowanym obrazie, a nie
na przypadkowym qcow2 z `output/`.

Waliduje:
  - metadane `image-release` (nazwa, wersja, data, commit, dirty=0) i ich zgodność
    z katalogiem artefaktów oraz tagiem/HEAD przekazanym przez release.sh; wartości
    mogą być w cudzysłowach pojedynczych albo podwójnych (format dotenv);
  - obraz leży dokładnie w `<repo-root>/output/<pełna-nazwa>/<pełna-nazwa>.qcow2`
    (bez heurystyki nazwy katalogu dziadka i bez podążania za symlinkiem obrazu);
  - manifest leży w katalogu obrazu (bez `find ... | head -1`);
  - `custom_data` manifestu (wersja, data, commit, dirty, build_run);
  - `files[]` manifestu: dokładnie jeden qcow2 o nazwie i rozmiarze obrazu;
  - `.qcow2.sha256`: wpis dla tego pliku w formacie GNU `sha256sum` (64 hex,
    opcjonalny znacznik `*`), także w pliku zbiorczym z komentarzami i innymi
    plikami; duplikat wpisu dla tego obrazu to błąd (niejednoznaczność).

To bramka **spójności** wewnątrz potoku CI, nie podpis kryptograficzny: `image-release`,
manifest Packera i suma leżą w tym samym katalogu roboczym runnera. Kompromitacja runnera
może podmienić wszystkie trzy. Proweniencja authenticity (SLSA/in-toto, cosign/KMS) należy
do prac wydawniczych #12b/#224 — patrz `docs/wersjonowanie-wydan.md`.

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


def _unquote(value: str) -> str:
    """Usuwa parę otaczających cudzysłowów, tak jak POSIX/dotenv (bez interpretacji escape'ów)."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


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
        values[key] = _unquote(raw.strip())

    missing = [key for key in REQUIRED_KEYS if not values.get(key)]
    if missing:
        raise ProvenanceError(f"{path}: brak wartości dla {', '.join(missing)}")
    return values


def sha256_file(path: Path) -> str:
    # file_digest czyta plik w pętli C (bez wywołania Pythona na każdy blok); dla obrazu
    # 15–30 GB to istotnie mniej narzutu niż `for chunk in iter(...)`.
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise ProvenanceError(f"nie można policzyć sumy {path}: {exc}") from exc


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


def parse_checksum_entries(checksum: Path) -> list[tuple[str, str]]:
    """Czyta plik sum w formacie GNU `sha256sum`: `<64 hex> [ *]<plik>`, linia po linii.

    Dopuszcza puste linie i komentarze (`#`). Każdy inny wiersz musi mieć poprawną sumę
    i nazwę pliku — uszkodzony wiersz zatrzymuje wydanie zamiast być po cichu pominięty.
    """
    try:
        lines = checksum.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProvenanceError(f"nie można odczytać sumy {checksum}: {exc}") from exc

    entries: list[tuple[str, str]] = []
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        fields = text.split(None, 1)
        if len(fields) != 2:
            raise ProvenanceError(f"{checksum}:{number}: oczekiwano '<sha256>  <plik>', jest {text!r}")
        digest, filename = fields
        if filename.startswith("\\"):
            # GNU coreutils poprzedza backslashem nazwy wymagające escapowania.
            filename = filename[1:]
        filename = filename.lstrip("*")
        if not SHA256_RE.fullmatch(digest):
            raise ProvenanceError(f"{checksum}:{number}: suma nie jest 64 małymi cyframi hex")
        if not filename:
            raise ProvenanceError(f"{checksum}:{number}: brak nazwy pliku")
        entries.append((digest, filename))
    if not entries:
        raise ProvenanceError(f"{checksum}: brak wpisów sumy")
    return entries


def validate_checksum(checksum: Path, image: Path) -> str:
    entries = parse_checksum_entries(checksum)
    matching = [(digest, filename) for digest, filename in entries if Path(filename).name == image.name]
    if not matching:
        names = ", ".join(repr(filename) for _, filename in entries)
        raise ProvenanceError(f"{checksum}: brak wpisu dla {image.name!r} (są: {names})")
    if len(matching) > 1:
        raise ProvenanceError(f"{checksum}: wiele wpisów dla {image.name!r} — niejednoznaczna suma")
    digest, _filename = matching[0]
    actual = sha256_file(image)
    if actual != digest:
        raise ProvenanceError(f"{checksum}: suma {digest} nie zgadza się z obrazem {image} ({actual})")
    return digest


def validate(args: argparse.Namespace) -> dict[str, str]:
    artifacts = Path(args.artifacts)
    image = Path(args.image)
    manifest = Path(args.manifest)
    checksum = Path(args.checksum)
    repo_root = Path(args.repo_root)

    if not artifacts.is_dir():
        raise ProvenanceError(f"katalog artefaktów nie istnieje: {artifacts}")
    if not repo_root.is_dir():
        raise ProvenanceError(f"katalog repozytorium nie istnieje: {repo_root}")
    repo_root = repo_root.resolve()
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
    expected_image = repo_root / "output" / full_name / f"{full_name}.qcow2"
    if image.is_symlink():
        raise ProvenanceError(f"obraz {image} jest symlinkiem — nie weryfikujemy celu")
    image_resolved = image.resolve()
    if image_resolved != expected_image:
        raise ProvenanceError(f"obraz {image} nie leży w {expected_image} (względem --repo-root {repo_root})")
    if not image.is_file():
        raise ProvenanceError(f"obraz nie istnieje: {image}")
    image = image_resolved

    expected_manifest = image.parent / "packer-manifest.json"
    if manifest.is_symlink() or manifest.resolve() != expected_manifest:
        raise ProvenanceError(f"manifest {manifest} nie jest manifestem tego obrazu ({expected_manifest})")
    if not manifest.is_file():
        raise ProvenanceError(f"manifest nie istnieje: {manifest}")

    expected_checksum = image.with_name(image.name + ".sha256")
    if checksum.is_symlink() or checksum.resolve() != expected_checksum:
        raise ProvenanceError(f"suma {checksum} nie jest sumą tego obrazu ({expected_checksum})")
    if not checksum.is_file():
        raise ProvenanceError(f"suma nie istnieje: {checksum}")

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
