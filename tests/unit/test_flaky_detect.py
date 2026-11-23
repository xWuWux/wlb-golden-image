"""Testy lane'u detekcji niestabilności (#349).

Nie uruchamiają pytest/sieci: sprawdzają czystą logikę klasyfikacji, parsowania JUnit i raportu,
oraz orkiestrację main() z podmienionym run_suite. Kluczowy inwariant: test padający we WSZYSTKICH
przebiegach to `broken` (realna porażka), NIE `flaky` — nie wolno go ukryć ani kwarantannować.
"""

from conftest import REPO_ROOT, load_script

detect = load_script("wlb_flaky_detect", REPO_ROOT / "ci/flaky_detect.py")

JUNIT_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="{n}">{cases}</testsuite></testsuites>"""


def _junit(path, cases):
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
    path.write_text(JUNIT_TMPL.format(n=len(cases), cases="".join(body)), encoding="utf-8")
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


def test_parse_junit_duplicate_id_worst_wins(tmp_path):
    # pytest-repeat produkuje ten sam test_id wielokrotnie; jedno niepowodzenie nie może zniknąć.
    xml = _junit(tmp_path / "r.xml", [("m", "t", "pass"), ("m", "t", "fail"), ("m", "t", "pass")])
    assert detect.parse_junit(xml)["m::t"] == "fail"


def test_classify_flaky_when_results_differ():
    runs = [{"m::t": "pass"}, {"m::t": "fail"}, {"m::t": "pass"}]
    assert detect.classify(runs)["m::t"] == detect.VERDICT_FLAKY


def test_classify_broken_when_all_runs_fail():
    runs = [{"m::t": "fail"}, {"m::t": "error"}, {"m::t": "fail"}]
    # Inwariant: zawsze-padający to broken, nie flaky — realna porażka, nie wolno ukryć.
    assert detect.classify(runs)["m::t"] == detect.VERDICT_BROKEN


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


def test_classify_missing_in_some_runs_is_ignored():
    # różnice selekcji/kolekcji nie są same w sobie dowodem flaky.
    runs = [{"a::t": "pass"}, {}]
    assert detect.classify(runs)["a::t"] == detect.VERDICT_STABLE


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


def test_main_report_only_exit_zero_even_with_flaky(tmp_path, monkeypatch):
    # Inwariant: domyślnie report-only — flaky NIE daje kodu niezerowego (lane nie bramkuje).
    calls = []

    def fake_run_suite(target, seed, reports_dir, repeat=0):
        calls.append(seed)
        return _junit(reports_dir / f"s{seed}.xml", [("m", "t", "pass" if seed % 2 else "fail")])

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    out = tmp_path / "flaky-detect.json"
    rc = detect.main(["--runs", "2", "--seed-base", "0", "--out", str(out), "--reports", str(tmp_path)])
    assert rc == 0
    assert calls == [0, 1]
    import json

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["flaky"] == ["m::t"]


def test_main_gate_returns_two_on_flaky(tmp_path, monkeypatch):
    def fake_run_suite(target, seed, reports_dir, repeat=0):
        return _junit(reports_dir / f"s{seed}.xml", [("m", "t", "pass" if seed % 2 else "fail")])

    monkeypatch.setattr(detect, "run_suite", fake_run_suite)
    rc = detect.main(
        ["--runs", "2", "--seed-base", "0", "--gate", "--out", str(tmp_path / "o.json"), "--reports", str(tmp_path)]
    )
    assert rc == 2


def test_main_rejects_single_run(tmp_path):
    rc = detect.main(["--runs", "1", "--out", str(tmp_path / "o.json"), "--reports", str(tmp_path)])
    assert rc == 2
