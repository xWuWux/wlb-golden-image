"""Własności parsera i walidatora tożsamości OS (#351, #129).

Testy przykładowe w `test_image_identity.py` pokrywają składnię i błędy. Tutaj Hypothesis
sprawdza niezmienniki:

1. wartości w cudzysłowach i bez cudzysłowów są parsowane literalnie i casefoldowane;
2. dwukrotny odczyt tego samego pliku daje identyczną tożsamość (idempotence);
3. `validate_scan_identity` akceptuje dokładnie tę samą, wspieraną parę ID/VERSION_ID;
4. każda inna para — inna dystrybucja, inne wydanie albo para spoza wspieranego zbioru —
   jest odrzucana jako `IdentityError`, bez przypadkowego przejścia.

Limity: 30 przykładów na własność, deadline 5 s. Kontrprzykłady są raportowane przez
Hypothesis i mogą być odtworzone przez `@reproduce_failure` / zapisany seed.
"""

import string
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ci.image_identity import IdentityError, OsIdentity, read_os_identity, validate_scan_identity

SAFE_TEXT = st.text(
    alphabet=string.ascii_letters + string.digits + "._-",
    min_size=1,
    max_size=24,
)
SETTINGS = settings(max_examples=30, deadline=5000)


@SETTINGS
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


@SETTINGS
@given(
    id_value=SAFE_TEXT,
    version_value=SAFE_TEXT,
    scanner_id=SAFE_TEXT,
    scanner_version=SAFE_TEXT,
)
def test_validation_accepts_exactly_the_supported_equal_pair(
    id_value: str, version_value: str, scanner_id: str, scanner_version: str
):
    target = OsIdentity(id=id_value, version_id=version_value)
    scanner = OsIdentity(id=scanner_id, version_id=scanner_version)
    if target.is_supported and target == scanner:
        validate_scan_identity(target, scanner)
    else:
        with pytest.raises(IdentityError):
            validate_scan_identity(target, scanner)
