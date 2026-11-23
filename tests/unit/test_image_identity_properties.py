"""Własności parsera i walidatora tożsamości OS (#351, #129).

Testy przykładowe w `test_image_identity.py` pokrywają składnię i błędy. Tutaj Hypothesis
sprawdza niezmienniki:

1. wartości w cudzysłowach i bez cudzysłowów są parsowane literalnie i casefoldowane;
2. dwukrotny odczyt tego samego pliku daje identyczną tożsamość (idempotence);
3. każda reprezentacja wspieranej pary ID/VERSION_ID (wielkość liter, cudzysłowy, whitespace)
   po normalizacji parsera jest akceptowana przez `validate_scan_identity`;
4. wspierany target z innym skanerem jest odrzucany jako `IdentityError`;
5. target spoza wspieranego zbioru jest odrzucany jako `IdentityError`.

Limity są w profilu Hypothesis (`tests/conftest.py`): CI 50 przykładów bez deadline,
lokalnie 15 przykładów z deadline 5 s. Kontrprzykłady są raportowane przez Hypothesis
i mogą być odtworzone przez `--hypothesis-seed` lub `@reproduce_failure`.
"""

import string
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from ci.image_identity import SUPPORTED, IdentityError, OsIdentity, read_os_identity, validate_scan_identity

SAFE_TEXT = st.text(
    alphabet=string.ascii_letters + string.digits + "._-",
    min_size=1,
    max_size=24,
)


@given(id_value=SAFE_TEXT, version_value=SAFE_TEXT)
def test_quoted_values_round_trip_and_reading_is_idempotent(id_value: str, version_value: str):
    with TemporaryDirectory() as temp:
        path = Path(temp) / "os-release"
        path.write_text(f"ID=\"{id_value}\"\nVERSION_ID='{version_value}'\n", encoding="utf-8")
        first = read_os_identity(str(path))
        second = read_os_identity(str(path))
        assert first == second
        assert first.id == id_value.casefold()
        assert first.version_id == version_value.casefold()


@given(
    pair=st.sampled_from(sorted(SUPPORTED)),
    quote=st.sampled_from([("", ""), ('"', '"'), ("'", "'")]),
    whitespace=st.text(alphabet=" \t", max_size=3),
    normalize=st.sampled_from([str.lower, str.upper, str.capitalize]),
)
def test_supported_pair_is_accepted_after_parser_normalization(
    pair: tuple[str, str], quote: tuple[str, str], whitespace: str, normalize: Callable[[str], str]
):
    distro_id, version_id = pair
    left, right = quote
    body = (
        f"{whitespace}ID={left}{normalize(distro_id)}{right}{whitespace}\n"
        f"{whitespace}VERSION_ID={left}{normalize(version_id)}{right}{whitespace}\n"
    )
    with TemporaryDirectory() as temp:
        path = Path(temp) / "os-release"
        path.write_text(body, encoding="utf-8")
        identity = read_os_identity(str(path))
    assert identity == OsIdentity(id=distro_id, version_id=version_id)
    assert identity.is_supported
    validate_scan_identity(identity, identity)


@given(
    pair=st.sampled_from(sorted(SUPPORTED)),
    scanner_id=SAFE_TEXT,
    scanner_version=SAFE_TEXT,
)
def test_validation_rejects_supported_target_with_different_scanner(
    pair: tuple[str, str], scanner_id: str, scanner_version: str
):
    distro_id, version_id = pair
    target = OsIdentity(id=distro_id, version_id=version_id)
    scanner = OsIdentity(id=scanner_id, version_id=scanner_version)
    assume(scanner != target)
    with pytest.raises(IdentityError, match="srodowisko skanera"):
        validate_scan_identity(target, scanner)


@given(id_value=SAFE_TEXT, version_value=SAFE_TEXT)
def test_validation_rejects_unsupported_target(id_value: str, version_value: str):
    target = OsIdentity(id=id_value, version_id=version_value)
    assume(not target.is_supported)
    with pytest.raises(IdentityError, match="poza wspieranym"):
        validate_scan_identity(target, target)
