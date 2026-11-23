"""Własności walidatora manifestu wydania (#351).

Testy przykładowe w `test_verify_platform_images.py` sprawdzają wybrane przypadki.
Tutaj Hypothesis generuje dane i sprawdza niezmienniki kontraktu:

1. poprawny manifest przechodzi walidację i walidacja jest idempotentna;
2. kolejność rekordów w JSON nie zmienia wyniku (kolejność nie jest częścią kontraktu);
3. zmiana bajtów obrazu bez zmiany sumy jest zawsze odrzucana;
4. zmiana wersji pojedynczego obrazu jest zawsze odrzucana;
5. `base_sha256` obrazu pochodnego musi wskazywać na bieżący digest rodzica;
6. brak lub nadmiarowy wariant jest odrzucany;
7. dowolny kształt JSON oraz uszkodzony/ucięty tekst JSON są odrzucane jako `ValueError`
   (fail-closed; nie tylko poprawne struktury).

Limity są w profilu Hypothesis (`tests/conftest.py`): CI 50 przykładów bez deadline,
lokalnie 15 przykładów z deadline 5 s. Shrinking i raportowanie kontrprzykładu są
włączone domyślnie. Testy działają w istniejącym etapie 4.
"""

import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from ci.verify_platform_images import CATALOG, verify

CATALOG_DATA = json.loads(CATALOG.read_text())
NAMES = tuple(CATALOG_DATA)
DERIVED = tuple(name for name, parent in CATALOG_DATA.items() if parent)
VERSION = st.from_regex(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", fullmatch=True)
PAYLOADS = st.fixed_dictionaries({name: st.binary(min_size=1, max_size=64) for name in NAMES})


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_valid(directory: Path, version: str, payloads: dict[str, bytes]) -> tuple[Path, dict[str, dict]]:
    images = {}
    for name, parent in CATALOG_DATA.items():
        (directory / f"{name}.qcow2").write_bytes(payloads[name])
        images[name] = {
            "version": version,
            "sha256": sha256(payloads[name]),
            "base_sha256": sha256(payloads[parent]) if parent else None,
        }
    manifest = directory / "candidate.json"
    manifest.write_text(json.dumps({"schema": 1, "version": version, "images": images}))
    return manifest, images


def save_manifest(directory: Path, manifest: Path, version: str, images: dict[str, dict]) -> None:
    manifest.write_text(json.dumps({"schema": 1, "version": version, "images": images}))


@given(version=VERSION, payloads=PAYLOADS)
def test_valid_manifest_is_accepted_and_verification_is_idempotent(version: str, payloads: dict[str, bytes]):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, _ = write_valid(directory, version, payloads)
        verify(version, manifest, directory)
        verify(version, manifest, directory)


@given(version=VERSION, payloads=PAYLOADS, data=st.data())
def test_record_order_is_not_part_of_the_contract(version: str, payloads: dict[str, bytes], data):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, images = write_valid(directory, version, payloads)
        keys = data.draw(st.permutations(list(images)))
        save_manifest(directory, manifest, version, {key: images[key] for key in keys})
        verify(version, manifest, directory)


@given(
    version=VERSION,
    payloads=PAYLOADS,
    name=st.sampled_from(NAMES),
    replacement=st.binary(min_size=1, max_size=64),
)
def test_any_payload_change_is_rejected(version: str, payloads: dict[str, bytes], name: str, replacement: bytes):
    assume(replacement != payloads[name])
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, _ = write_valid(directory, version, payloads)
        (directory / f"{name}.qcow2").write_bytes(replacement)
        with pytest.raises(ValueError, match=rf"^{re.escape(name)}: image digest mismatch$"):
            verify(version, manifest, directory)


@given(version=VERSION, other=VERSION, payloads=PAYLOADS, name=st.sampled_from(NAMES))
def test_record_version_change_is_rejected(version: str, other: str, payloads: dict[str, bytes], name: str):
    assume(other != version)
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, images = write_valid(directory, version, payloads)
        images[name]["version"] = other
        save_manifest(directory, manifest, version, images)
        with pytest.raises(ValueError, match=rf"^{re.escape(name)}: unexpected image version$"):
            verify(version, manifest, directory)


@given(
    version=VERSION,
    payloads=PAYLOADS,
    name=st.sampled_from(DERIVED),
    wrong=st.from_regex(r"[0-9a-f]{64}", fullmatch=True),
)
def test_derived_base_digest_must_match_parent(version: str, payloads: dict[str, bytes], name: str, wrong: str):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, images = write_valid(directory, version, payloads)
        assume(wrong != images[name]["base_sha256"])
        images[name]["base_sha256"] = wrong
        save_manifest(directory, manifest, version, images)
        with pytest.raises(ValueError, match=rf"^{re.escape(name)}: unexpected base digest$"):
            verify(version, manifest, directory)


@given(version=VERSION, payloads=PAYLOADS, name=st.sampled_from(NAMES))
def test_missing_variant_is_rejected(version: str, payloads: dict[str, bytes], name: str):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, images = write_valid(directory, version, payloads)
        del images[name]
        save_manifest(directory, manifest, version, images)
        with pytest.raises(ValueError, match=r"^image set differs from the release catalog$"):
            verify(version, manifest, directory)


@given(version=VERSION, payloads=PAYLOADS)
def test_extra_variant_is_rejected(version: str, payloads: dict[str, bytes]):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, images = write_valid(directory, version, payloads)
        images["wlb-extra"] = images[NAMES[0]]
        save_manifest(directory, manifest, version, images)
        with pytest.raises(ValueError, match=r"^image set differs from the release catalog$"):
            verify(version, manifest, directory)


@given(version=VERSION, payloads=PAYLOADS, name=st.sampled_from(NAMES))
def test_empty_payload_is_rejected(version: str, payloads: dict[str, bytes], name: str):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, _ = write_valid(directory, version, payloads)
        (directory / f"{name}.qcow2").write_bytes(b"")
        with pytest.raises(ValueError, match=rf"^{re.escape(name)}: expected a nonempty regular image file$"):
            verify(version, manifest, directory)


@given(version=VERSION, payloads=PAYLOADS, name=st.sampled_from(NAMES))
def test_symlink_payload_is_rejected(version: str, payloads: dict[str, bytes], name: str):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest, _ = write_valid(directory, version, payloads)
        target = directory / "target.qcow2"
        target.write_bytes(payloads[name])
        path = directory / f"{name}.qcow2"
        path.unlink()
        path.symlink_to(target)
        with pytest.raises(ValueError, match=rf"^{re.escape(name)}: expected a nonempty regular image file$"):
            verify(version, manifest, directory)


MALFORMED = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda children: st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=10), children, max_size=5),
    max_leaves=20,
)


@given(payload=MALFORMED)
def test_malformed_candidate_shape_is_rejected_as_value_error(payload):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest = directory / "candidate.json"
        manifest.write_text(json.dumps(payload))
        with pytest.raises(ValueError):
            verify("1.2.0", manifest, directory)


INVALID_JSON_TEXT = st.one_of(
    st.text(max_size=200),
    st.binary(max_size=200).map(lambda raw: raw.decode("utf-8", errors="replace")),
    st.sampled_from(["{", "[", '{"schema":', "not json", '{"schema": 1,', "\x00"]),
)


@given(raw=INVALID_JSON_TEXT)
def test_broken_json_text_is_rejected_as_value_error(raw: str):
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        pass
    else:
        assume(False)
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        manifest = directory / "candidate.json"
        manifest.write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError):
            verify("1.2.0", manifest, directory)
