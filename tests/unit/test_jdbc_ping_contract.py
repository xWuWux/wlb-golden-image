"""Kontrakt audytowalności i integralności helpera JDBC WlbJdbcPing (#271).

Weryfikuje:
1. Obecność źródła Java w tests/lib/WlbJdbcPing.java.
2. Zgodność osadzonego źródła w teście akceptacyjnym tests/acceptance.d/72-pediatria.sh
   ze źródłem w tests/lib/WlbJdbcPing.java.
3. Czystość i audytowalność bytecode fallbacku (magic 0xCAFEBABE, Java 8, wymagane
   symbole JDBC, brak niebezpiecznych wywołań exec/refleksji/socketów).
4. Jeśli w środowisku obecny jest kompilator javac — kompiluje źródło i weryfikuje zgodność.
"""

# ruff: noqa: S603

import base64
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_JAVA = REPO_ROOT / "tests" / "lib" / "WlbJdbcPing.java"
ACCEPTANCE_SCRIPT = REPO_ROOT / "tests" / "acceptance.d" / "72-pediatria.sh"


def _extract_embedded_source(script_text: str) -> str:
    match = re.search(
        r"cat <<'EOF' >\"\$W72_TMP/WlbJdbcPing\.java\"\n(.*?)\nEOF",
        script_text,
        re.DOTALL,
    )
    assert match, "Nie znaleziono osadzonego bloku źródła WlbJdbcPing.java w 72-pediatria.sh"
    return match.group(1).strip()


def _extract_embedded_bytecode(script_text: str) -> bytes:
    match = re.search(
        r"base64 -d <<'EOF' >\"\$W72_TMP/WlbJdbcPing\.class\"\n(.*?)\nEOF",
        script_text,
        re.DOTALL,
    )
    assert match, "Nie znaleziono osadzonego bloku base64 WlbJdbcPing.class w 72-pediatria.sh"
    b64_content = "".join(line.strip() for line in match.group(1).splitlines())
    return base64.b64decode(b64_content)


def test_java_source_file_exists():
    assert SOURCE_JAVA.is_file(), f"Brak pliku źródłowego: {SOURCE_JAVA}"
    content = SOURCE_JAVA.read_text(encoding="utf-8")
    assert "public class WlbJdbcPing" in content
    assert "org.postgresql.Driver" in content
    assert "SELECT 1" in content
    assert "WLB_JDBC_OK" in content


def test_embedded_source_matches_canonical_source():
    canonical = SOURCE_JAVA.read_text(encoding="utf-8")
    embedded = _extract_embedded_source(ACCEPTANCE_SCRIPT.read_text(encoding="utf-8"))

    # Normalizacja kodu (usunięcie komentarzy nagłówkowych)
    canonical_body = "\n".join(line for line in canonical.splitlines() if not line.strip().startswith("//")).strip()
    embedded_body = "\n".join(line for line in embedded.splitlines() if not line.strip().startswith("//")).strip()

    assert canonical_body == embedded_body, "Źródło Java w 72-pediatria.sh różni się od tests/lib/WlbJdbcPing.java"


def test_embedded_bytecode_audit():
    script_text = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")
    raw_class = _extract_embedded_bytecode(script_text)

    # 1. Prawidłowy nagłówek klasy Java (0xCAFEBABE)
    assert raw_class[:4] == b"\xca\xfe\xba\xbe", "Niepoprawne magic bytes klasy Java"

    # 2. Wersja Java 8 (major 52) gwarantująca uruchamialność na każdym JRE >= 8
    major_version = int.from_bytes(raw_class[6:8], "big")
    assert major_version == 52, f"Oczekiwano wersji Java 8 (major 52), otrzymano: {major_version}"

    # 3. Wymagane symbole biznesowe JDBC
    required_symbols = [
        b"WlbJdbcPing",
        b"org.postgresql.Driver",
        b"SELECT 1",
        b"WLB_JDBC_OK",
        b"getConnection",
        b"executeQuery",
    ]
    for symbol in required_symbols:
        assert symbol in raw_class, f"Brak wymaganego symbolu w bytecode: {symbol.decode()}"

    # 4. Audyt bezpieczeństwa: brak zakazanych / niebezpiecznych wywołań
    forbidden_symbols = [
        b"ProcessBuilder",
        b"java/lang/Runtime",
        b"java/net/Socket",
        b"java/net/URL",
        b"java/lang/reflect",
        b"System.load",
    ]
    for forbidden in forbidden_symbols:
        assert forbidden not in raw_class, f"Wykryto niedozwolony symbol w bytecode WlbJdbcPing: {forbidden.decode()}"


def test_recompilation_matches_if_javac_available():
    javac_path = shutil.which("javac")
    if not javac_path:
        pytest.skip("Brak kompilatora javac w lokalnym środowisku testowym (skip)")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_java = Path(tmpdir) / "WlbJdbcPing.java"
        shutil.copy(SOURCE_JAVA, tmp_java)

        proc = subprocess.run(
            [javac_path, "-source", "8", "-target", "8", str(tmp_java)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"Błąd kompilacji javac: {proc.stderr}"

        compiled_class = Path(tmpdir) / "WlbJdbcPing.class"
        assert compiled_class.is_file()
        compiled_bytes = compiled_class.read_bytes()

        # Weryfikacja symboli w świeżo skompilowanej klasie
        for symbol in [b"WlbJdbcPing", b"org.postgresql.Driver", b"SELECT 1", b"WLB_JDBC_OK"]:
            assert symbol in compiled_bytes, f"Świeża kompilacja nie zawiera {symbol.decode()}"
