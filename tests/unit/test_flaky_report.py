"""Testy jednostkowe parsera i normalizatora raportów JUnit (ci/flaky_report.py, #349)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import flaky_report as fr
import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "junit"


def test_parse_pytest_subtests_multi_failure() -> None:
    """Weryfikuje, że wiele znaczników <failure> w jednym <testcase> nie gubi komunikatów (#349)."""
    fixture_path = FIXTURES_DIR / "pytest-subtests-multi-failure.xml"
    results = fr.parse_junit(fixture_path)

    assert len(results) == 1
    r = results[0]
    assert r.test_id == "tests.unit.test_demo::test_sub[0]"
    assert r.status == "fail"
    assert r.time == 0.012
    assert r.source_stage == "stage4:unit"
    assert r.skip_reason is None
    assert r.failure_message is not None
    assert "Subtest 1 failed: assert 0 == 1" in r.failure_message
    assert "Subtest 2 failed: assert 2 == 3" in r.failure_message


def test_parse_acceptance_sample() -> None:
    """Weryfikuje kontrakt acceptance-stage5: test_id = name, rozróżnienie pass/fail/skip (#349)."""
    fixture_path = FIXTURES_DIR / "acceptance-sample.xml"
    results = fr.parse_junit(fixture_path)

    assert len(results) == 3

    # Pass
    r_pass = results[0]
    assert r_pass.test_id == "AppArmor włączony (aa-enabled)"
    assert r_pass.status == "pass"
    assert r_pass.time == 0.045
    assert r_pass.source_stage == "stage5:acceptance"
    assert r_pass.skip_reason is None
    assert r_pass.failure_message is None

    # Fail
    r_fail = results[1]
    assert r_fail.test_id == "Dropin GRUB 60-wlb-apparmor.cfg istnieje"
    assert r_fail.status == "fail"
    assert r_fail.time == 0.012
    assert r_fail.source_stage == "stage5:acceptance"
    assert r_fail.failure_message is not None
    assert "test -f /etc/default/grub.d/60-wlb-apparmor.cfg exited with 1" in r_fail.failure_message

    # Skip
    r_skip = results[2]
    assert r_skip.test_id == "Faktyczne wylogowanie po limicie sesji — test ręczny"
    assert r_skip.status == "skip"
    assert r_skip.time == 0.0
    assert r_skip.source_stage == "stage5:acceptance"
    assert r_skip.skip_reason == "test ręczny (zob. README)"
    assert r_skip.failure_message is None


def test_parse_skipped_with_reason() -> None:
    """Weryfikuje parsowanie testów pominiętych z powodem w pytest JUnit (#349)."""
    fixture_path = FIXTURES_DIR / "skipped-with-reason.xml"
    results = fr.parse_junit(fixture_path)

    assert len(results) == 2
    assert results[0].test_id == "tests.unit.test_features::test_proxy_allowlist"
    assert results[0].status == "skip"
    assert results[0].skip_reason == "Brak testowego proxy na hoście (brak proxy)"
    assert results[0].source_stage == "stage4:unit"

    assert results[1].test_id == "tests.unit.test_features::test_ntp_sync"
    assert results[1].status == "skip"
    assert results[1].skip_reason == "Wymaga serwera NTP (wymaga ntp)"


def test_parse_malformed_fail_closed() -> None:
    """Weryfikuje zachowanie fail-closed przy niepełnym/uszkodzonym XML (#349)."""
    fixture_path = FIXTURES_DIR / "malformed.xml"
    with pytest.raises(fr.MalformedReportError, match="Niepoprawny lub ucięty plik XML"):
        fr.parse_junit(fixture_path)


def test_parse_missing_file_fail_closed(tmp_path: Path) -> None:
    """Weryfikuje fail-closed przy nieistniejącym pliku (#349)."""
    non_existent = tmp_path / "non_existent.xml"
    with pytest.raises(FileNotFoundError, match="nie istnieje"):
        fr.parse_junit(non_existent)


def test_parse_empty_file_fail_closed(tmp_path: Path) -> None:
    """Weryfikuje fail-closed przy pustym pliku (#349)."""
    empty_file = tmp_path / "empty.xml"
    empty_file.write_text("   \n", encoding="utf-8")
    with pytest.raises(fr.MalformedReportError, match="jest pusty"):
        fr.parse_junit(empty_file)


def test_parse_invalid_root_element_fail_closed(tmp_path: Path) -> None:
    """Weryfikuje fail-closed gdy element główny XML nie jest testsuite ani testsuites (#349)."""
    invalid_root = tmp_path / "invalid_root.xml"
    invalid_root.write_text("<catalog><book id='1'/></catalog>", encoding="utf-8")
    with pytest.raises(fr.MalformedReportError, match="Oczekiwano elementu głównego"):
        fr.parse_junit(invalid_root)


def test_parse_missing_testcase_name_fail_closed(tmp_path: Path) -> None:
    """Weryfikuje fail-closed gdy <testcase> nie posiada atrybutu name (#349)."""
    no_name = tmp_path / "no_name.xml"
    no_name.write_text("<testsuite name='ts'><testcase time='0.1'/></testsuite>", encoding="utf-8")
    with pytest.raises(fr.MalformedReportError, match="bez atrybutu 'name'"):
        fr.parse_junit(no_name)


def test_parse_error_status_distinguished(tmp_path: Path) -> None:
    """Weryfikuje, że znacznik <error> daje status 'error', a nie 'fail' ani 'skip' (#349)."""
    err_xml = tmp_path / "error_sample.xml"
    err_xml.write_text(
        '<testsuite name="pytest"><testcase classname="test_pkg" name="test_err">'
        '<error message="Crash in fixture">Traceback</error></testcase></testsuite>',
        encoding="utf-8",
    )
    results = fr.parse_junit(err_xml)
    assert len(results) == 1
    assert results[0].status == "error"
    assert results[0].failure_message is not None
    assert "Crash in fixture" in results[0].failure_message


def test_parse_testsuites_hierarchy(tmp_path: Path) -> None:
    """Weryfikuje obsługę pliku z kontenerem nadrzędnym <testsuites> i wieloma <testsuite> (#349)."""
    multi_xml = tmp_path / "multi.xml"
    multi_xml.write_text(
        '<testsuites><testsuite name="suite1"><testcase name="t1"/></testsuite>'
        '<testsuite name="acceptance-stage5"><testcase name="t2"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    results = fr.parse_junit(multi_xml)
    assert len(results) == 2
    assert results[0].test_id == "t1"
    assert results[0].source_stage == "stage4:unit"
    assert results[1].test_id == "t2"
    assert results[1].source_stage == "stage5:acceptance"


def test_parse_explicit_source_stage(tmp_path: Path) -> None:
    """Weryfikuje jawne nadpisanie source_stage (#349)."""
    custom_xml = tmp_path / "custom.xml"
    custom_xml.write_text('<testsuite name="custom"><testcase name="c1"/></testsuite>', encoding="utf-8")
    results = fr.parse_junit(custom_xml, source_stage="custom_stage")
    assert len(results) == 1
    assert results[0].source_stage == "custom_stage"


def test_parse_time_fallback(tmp_path: Path) -> None:
    """Weryfikuje fallback czasu gdy brak atrybutu time lub jest nieprawidłowy (#349)."""
    time_xml = tmp_path / "time.xml"
    time_xml.write_text(
        '<testsuite name="ts">'
        '<testcase name="t1"/>'
        '<testcase name="t2" time="invalid"/>'
        '<testcase name="t3" time="-1.5"/>'
        "</testsuite>",
        encoding="utf-8",
    )
    results = fr.parse_junit(time_xml)
    assert len(results) == 3
    assert results[0].time == 0.0
    assert results[1].time == 0.0
    assert results[2].time == 0.0


def test_cli_parse_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Weryfikuje działanie CLI flaky_report.py parse na poprawnych plikach (#349)."""
    f1 = FIXTURES_DIR / "acceptance-sample.xml"
    f2 = FIXTURES_DIR / "skipped-with-reason.xml"
    out_file = tmp_path / "out" / "flaky-raw.json"

    stdout_capture = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_capture)

    rc = fr.main(["parse", str(f1), str(f2), "--output", str(out_file)])
    assert rc == 0

    assert out_file.exists()
    saved_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(saved_data) == 5  # 3 z f1 + 2 z f2

    stdout_data = json.loads(stdout_capture.getvalue())
    assert saved_data == stdout_data


def test_cli_parse_fail_closed_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Weryfikuje, że CLI kończy się kodem != 0 przy braku pliku (#349)."""
    non_existent = str(tmp_path / "missing.xml")
    stderr_capture = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_capture)

    rc = fr.main(["parse", non_existent])
    assert rc == 1
    assert "BŁĄD parsowania JUnit XML" in stderr_capture.getvalue()


def test_cli_parse_fail_closed_on_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Weryfikuje, że CLI kończy się kodem != 0 przy uszkodzonym XML (#349)."""
    malformed = str(FIXTURES_DIR / "malformed.xml")
    stderr_capture = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_capture)

    rc = fr.main(["parse", malformed])
    assert rc == 1
    assert "BŁĄD parsowania JUnit XML" in stderr_capture.getvalue()


def test_cli_output_write_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Weryfikuje obsługę błędu zapisu pliku wyjściowego w CLI (#349)."""
    f1 = FIXTURES_DIR / "acceptance-sample.xml"
    # Utwórz plik zamiast katalogu, aby wywołać błąd zapisu
    blocked_path = tmp_path / "blocked"
    blocked_path.write_text("file")
    out_file = blocked_path / "sub" / "out.json"

    stderr_capture = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_capture)

    rc = fr.main(["parse", str(f1), "--output", str(out_file)])
    assert rc == 1
    assert "BŁĄD zapisu" in stderr_capture.getvalue()


def test_direct_execution_subprocess() -> None:
    """Weryfikuje wywołanie skryptu jako modułu przez subprocess (#349)."""
    f1 = FIXTURES_DIR / "acceptance-sample.xml"
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "ci" / "flaky_report.py"

    proc = subprocess.run(  # noqa: S603 # nosec B603
        [sys.executable, str(script), "parse", str(f1)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert len(data) == 3
    assert data[0]["test_id"] == "AppArmor włączony (aa-enabled)"


def test_parse_oserror_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Weryfikuje obsługę błędu OSError przy odczycie pliku (#349)."""
    p = tmp_path / "sample.xml"
    p.write_text("<testsuite name='ts'><testcase name='t'/></testsuite>", encoding="utf-8")

    def fake_read_bytes(self: Path) -> bytes:
        raise OSError("Symulowany błąd I/O dysku")

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
    with pytest.raises(fr.MalformedReportError, match="Nie udało się odczytać pliku"):
        fr.parse_junit(p)


def test_parse_direct_testcase_under_testsuites(tmp_path: Path) -> None:
    """Weryfikuje obsługę <testcase> bezpośrednio pod <testsuites> (#349)."""
    p = tmp_path / "direct.xml"
    p.write_text("<testsuites><testcase name='direct_case'/></testsuites>", encoding="utf-8")
    results = fr.parse_junit(p)
    assert len(results) == 1
    assert results[0].test_id == "direct_case"


def test_parse_error_and_failure_text_only_and_empty(tmp_path: Path) -> None:
    """Weryfikuje fallbacki komunikatów gdy znacznik nie ma atrybutu message (#349)."""
    p = tmp_path / "fallback.xml"
    p.write_text(
        '<testsuite name="ts">'
        "<testcase name='t_err'><error>Tylko tekst błędu</error></testcase>"
        "<testcase name='t_fail_empty'><failure/></testcase>"
        "<testcase name='t_skip_text'><skipped>Tylko tekst skip</skipped></testcase>"
        "</testsuite>",
        encoding="utf-8",
    )
    results = fr.parse_junit(p)
    assert len(results) == 3
    assert results[0].status == "error"
    assert results[0].failure_message == "Tylko tekst błędu"
    assert results[1].status == "fail"
    assert results[1].failure_message == "Assertion failed"
    assert results[2].status == "skip"
    assert results[2].skip_reason == "Tylko tekst skip"
