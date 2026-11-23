"""Testy lane'u detekcji niestabilności (#349).

Sprawdzają czystą logikę klasyfikacji, parsowania JUnit i raportu,
obsługę błędów wykonawcy, limitów czasu i orkiestrację main().
Kluczowe inwarianty:
- test padający we WSZYSTKICH przebiegach to `broken` (realna porażka, nie wolno kwarantannować),
- błędy kolekcji / środowiska (kod wyjścia != 0/1) lub zero zebranych testów NIE mogą dawać fałszywego GREEN,
- stary plik raportu jest usuwany przed uruchomieniem,
- raport z przestrzenią nazw XML (xmlns) jest poprawnie parsowany.
"""

import signal
import subprocess
from pathlib import Path

import pytest
from conftest import REPO_ROOT, load_script

detect = load_script("wlb_flaky_detect", REPO_ROOT / "ci/flaky_detect.py")

JUNIT_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="{n}">{cases}</testsuite></testsuites>"""

JUNIT_NS_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<testsuites xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <testsuite name="pytest" tests="{n}">{cases}</testsuite>
</testsuites>"""


def _junit(path: Path, cases, tmpl: str = JUNIT_TMPL) -> Path:
    """cases: list (classname, name, status in {pass,fail,error,skip})."""
    body = []
    for classname, name, status in cases:
        attrs = f'classname="{classname}" name="{name}"'
        if status == "pass":
            body.append(f"<testcase {attrs}/>")
        elif status == "fail":
            body.append(f'<testcase {attrs}><failure message="x">boom</failure></testcase>')
        elif status == "error":
            body.append(f'<testcase {attrs}><error message="x">boom</error></testcase>')
        elif status == "skip":
            body.append(f'<testcase {attrs}><skipped message="x"/></testcase>')
    path.write_text(tmpl.format(n=len(cases), cases="".join(body)), encoding="utf-8")
    return path


def test_parse_junit_maps_status_and_test_id(tmp_path):
    xml = _junit(
        tmp_path / "r.xml",
        [("tests.m", "test_ok", "pass"), ("tests.m", "test_bad", "fail"), ("tests.m", "test_sk", "skip")],
    )
    parsed = detect.parse_junit(xml)
    assert parsed["tests.m::test_ok"] == "pass"
    assert parsed["tests.m::test_bad"] == "fail"
    assert parsed["tests.m::test_sk"] == "skip"


def test_parse_junit_with_xml_namespace(tmp_path):
    """Weryfikuje, że raport z deklaracją xmlns (przestrzeń nazw) jest poprawnie parsowany."""
    xml = _junit(
        tmp_path / "ns.xml",
        [("tests.m", "test_ns", "pass")],
        tmpl=JUNIT_NS_TMPL,
    )
    parsed = detect.parse_junit(xml)
    assert parsed["tests.m::test_ns"] == "pass"


def test_parse_junit_malformed_xml_raises_value_error(tmp_path):
    """Weryfikuje fail-closed przy uszkodzonym pliku XML."""
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<testsuites><broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Niepoprawny lub nieczytelny plik"):
        detect.parse_junit(bad_xml)


def test_parse_junit_duplicate_id_worst_wins(tmp_path):
    # pytest-repeat produkuje ten sam test_id wielokrotnie; jedno niepowodzenie nie może zniknąć.
    xml = _junit(tmp_path / "r.xml", [("m", "t", "pass"), ("m", "t", "fail"), ("m", "t", "pass")])
    assert detect.parse_junit(xml)["m::t"] == "fail"


def test_classify_flaky_when_results_differ():
    runs = [{"m::t": "pass"}, {"m::t": "fail"}, {"m::t": "pass"}]
    res = detect.classify(runs)
    assert res["m::t"] == detect.VERDICT_FLAKY
    assert res.details["m::t"]["fail_seeds"] == [1]


def test_classify_broken_when_all_runs_fail():
    runs = [{"m::t": "fail"}, {"m::t": "error"}, {"m::t": "fail"}]
    res = detect.classify(runs)
    # Inwariant: zawsze-padający to broken, nie flaky — realna porażka, nie wolno ukryć.
    assert res["m::t"] == detect.VERDICT_BROKEN


def test_classify_stable_pass():
    runs = [{"m::t": "pass"}, {"m::t": "pass"}]
    assert detect.classify(runs)["m::t"] == detect.VERDICT_STABLE


def test_classify_skip_only_is_skipped():
    runs = [{"m::t": "skip"}, {"m::t": "skip"}]
    assert detect.classify(runs)["m::t"] == detect.VERDICT_SKIPPED


def test_classify_skip_plus_pass_is_stable():
    # skip w części przebiegów nie czyni testu niestabilnym, jeśli pozostałe to pass.
    runs = [{"m::t": "skip"}, {"m::t": "pass"}]
    assert detect.classify(runs)["m::t"] == detect.VERDICT_STABLE


def test_classify_missing_in_some_runs_marked_flaky():
    # Jeśli test nie wystąpił we wszystkich przebiegach, kolekcja/wykonanie jest niespójne.
    runs = [{"a::t": "pass"}, {}]
    res = detect.classify(runs, [1000, 1001])
    assert res["a::t"] == detect.VERDICT_FLAKY
    assert res.details["a::t"]["missing_seeds"] == [1001]


def test_build_payload_counts_and_lists():
    verdicts = {
        "a": detect.VERDICT_FLAKY,
        "b": detect.VERDICT_BROKEN,
        "c": detect.VERDICT_STABLE,
        "d": detect.VERDICT_SKIPPED,
    }
    payload = detect.build_payload(verdicts, [1, 2], "tests/unit")
    assert payload["counts"] == {"stable_pass": 1, "flaky": 1, "broken": 1, "skipped": 1}
    assert payload["flaky"] == ["a"]
    assert payload["broken"] == ["b"]
    assert payload["seeds"] == [1, 2]


def test_render_summary_marks_broken_as_real_failure():
    payload = detect.build_payload({"a": detect.VERDICT_BROKEN}, [7], "tests/unit")
    out = detect.render_summary(payload)
    assert "nie kwarantannować" in out
    assert "`a`" in out


def test_render_summary_gives_reproduce_hint_for_flaky():
    payload = detect.build_payload({"x::t": detect.VERDICT_FLAKY}, [42], "tests/unit")
    out = detect.render_summary(payload)
    assert "PYTEST_RANDOMLY_SEED=42" in out


def test_render_summary_uses_actual_failing_seed():
    """Weryfikuje, że wskazówka odtworzenia podaje ziarno, przy którym test faktycznie padł."""
    runs = [
        {"x::t": "pass"},
        {"x::t": "pass"},
        {"x::t": "fail"},
    ]
    seeds = [1000, 1001, 1002]
    verdicts = detect.classify(runs, seeds)
    payload = detect.build_payload(verdicts, seeds, "tests/unit")
    out = detect.render_summary(payload)
    assert "PYTEST_RANDOMLY_SEED=1002" in out
    assert "padł przy ziarnie: 1002" in out


def test_render_summary_handles_empty_seeds():
    payload = {"counts": {}, "seeds": [], "runs": 0, "target": "tests/unit", "flaky": [], "broken": []}
    out = detect.render_summary(payload)
    assert "Brak niestabilnych i zepsutych testów" in out


def test_run_suite_unlinks_stale_xml_before_run(tmp_path, monkeypatch):
    """Weryfikuje, że stary raport JUnit XML jest usuwany przed startem przebiegu."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stale_xml = reports_dir / "flaky-detect-seed42.xml"
    stale_xml.write_text("<stale/>", encoding="utf-8")

    class FakeProc:
        pid = 1234
        returncode = 0

        def communicate(self, timeout=None):
            # Tworzymy świeży raport w trakcie
            _junit(stale_xml, [("m", "t", "pass")])
            return ("", "")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProc())
    res = detect.run_suite("tests/unit", 42, reports_dir, timeout=10)
    assert res.tests == 1
    assert res.exit_code == 0
    assert not res.timed_out


def test_run_suite_handles_timeout(tmp_path, monkeypatch):
    """Weryfikuje zachowanie przy przekroczeniu limitu czasu (zabicie grupy procesów)."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    class TimeoutProc:
        pid = 9999
        returncode = None

        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=timeout)
            return ("", "")

    killed_pids = []

    def fake_killpg(pid, sig):
        killed_pids.append((pid, sig))

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: TimeoutProc())
    monkeypatch.setattr(detect.os, "killpg", fake_killpg)

    res = detect.run_suite("tests/unit", 100, reports_dir, timeout=1)
    assert res.timed_out is True
    assert res.exit_code == -signal.SIGKILL
    assert killed_pids == [(9999, signal.SIGKILL)]


def test_main_report_only_exit_zero_even_with_flaky(tmp_path, monkeypatch):
    # Inwariant: domyślnie report-only — flaky NIE daje kodu niezerowego (lane nie bramkuje).
    calls = []

    def fake_run_suite(target, seed, reports_dir, repeat=0, timeout=600, cwd=None):
        calls.append(seed)
        xml = _junit(reports_dir / f"flaky-detect-seed{seed}.xml", [("m", "t", "pass" if seed % 2 else "fail")])
        return detect.RunResult(seed=seed, xml=xml, exit_code=0 if seed % 2 else 1, tests=1, duration_s=0.1)

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    out = tmp_path / "flaky-detect.json"
    rc = detect.main(["--runs", "2", "--seed-base", "0", "--out", str(out), "--reports", str(tmp_path)])
    assert rc == 0
    assert calls == [0, 1]
    import json

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["flaky"] == ["m::t"]


def test_main_gate_returns_two_on_flaky(tmp_path, monkeypatch):
    def fake_run_suite(target, seed, reports_dir, repeat=0, timeout=600, cwd=None):
        xml = _junit(reports_dir / f"flaky-detect-seed{seed}.xml", [("m", "t", "pass" if seed % 2 else "fail")])
        return detect.RunResult(seed=seed, xml=xml, exit_code=0 if seed % 2 else 1, tests=1, duration_s=0.1)

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    rc = detect.main(
        ["--runs", "2", "--seed-base", "0", "--gate", "--out", str(tmp_path / "o.json"), "--reports", str(tmp_path)]
    )
    assert rc == 2


def test_main_gate_returns_one_on_broken(tmp_path, monkeypatch):
    """Weryfikuje, że przy włączonej bramce realna porażka (broken) zwraca kod 1."""

    def fake_run_suite(target, seed, reports_dir, repeat=0, timeout=600, cwd=None):
        xml = _junit(reports_dir / f"flaky-detect-seed{seed}.xml", [("m", "t", "fail")])
        return detect.RunResult(seed=seed, xml=xml, exit_code=1, tests=1, duration_s=0.1)

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    rc = detect.main(
        ["--runs", "2", "--seed-base", "0", "--gate", "--out", str(tmp_path / "o.json"), "--reports", str(tmp_path)]
    )
    assert rc == 1


def test_main_rejects_pytest_exit_code_error(tmp_path, monkeypatch):
    """Weryfikuje, że kod błędu wykonania pytest (np. 5=no tests, 2=interrupted) kończy się kodem 2."""

    def fake_run_suite(target, seed, reports_dir, repeat=0, timeout=600, cwd=None):
        xml = _junit(reports_dir / f"flaky-detect-seed{seed}.xml", [])
        return detect.RunResult(seed=seed, xml=xml, exit_code=5, tests=0, duration_s=0.1)

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    rc = detect.main(["--runs", "2", "--reports", str(tmp_path)])
    assert rc == 2


def test_main_rejects_zero_tests(tmp_path, monkeypatch):
    """Weryfikuje, że zebranie 0 testów kończy się kodem 2 (nie fałszywym GREEN)."""

    def fake_run_suite(target, seed, reports_dir, repeat=0, timeout=600, cwd=None):
        xml = _junit(reports_dir / f"flaky-detect-seed{seed}.xml", [])
        return detect.RunResult(seed=seed, xml=xml, exit_code=0, tests=0, duration_s=0.1)

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    rc = detect.main(["--runs", "2", "--reports", str(tmp_path), "--min-tests", "1"])
    assert rc == 2


def test_main_rejects_timeout(tmp_path, monkeypatch):
    """Weryfikuje, że timeout kończy się kodem 2."""

    def fake_run_suite(target, seed, reports_dir, repeat=0, timeout=600, cwd=None):
        xml = reports_dir / f"flaky-detect-seed{seed}.xml"
        return detect.RunResult(seed=seed, xml=xml, exit_code=-9, tests=0, duration_s=1.0, timed_out=True)

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    rc = detect.main(["--runs", "2", "--reports", str(tmp_path)])
    assert rc == 2


def test_main_rejects_single_run(tmp_path):
    rc = detect.main(["--runs", "1", "--out", str(tmp_path / "o.json"), "--reports", str(tmp_path)])
    assert rc == 2


def test_main_rejects_negative_repeat(tmp_path):
    rc = detect.main(["--repeat", "-1", "--reports", str(tmp_path)])
    assert rc == 2


def test_main_rejects_invalid_timeout(tmp_path):
    rc = detect.main(["--timeout", "0", "--reports", str(tmp_path)])
    assert rc == 2
