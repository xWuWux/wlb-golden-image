"""Testy przygotowania raportów SARIF do publikacji w code scanning (#257)."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import sarif_report as sr

CANARY = "AKIAWLB257CANARY0000"
ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = object()


def make_doc(
    tool: str = "semgrep",
    results: list | None = None,
    *,
    rules: object = _DEFAULT,
    driver_name: str | None = None,
    version: str | None = "1.2.3",
    invocations: list | None = None,
    runs: list | None = None,
) -> dict:
    """Buduje minimalny poprawny dokument SARIF 2.1.0 (z regułami dla semgrepa)."""
    if runs is not None:
        return {"version": "2.1.0", "runs": runs}
    name = driver_name or ("Semgrep OSS" if tool == "semgrep" else "Checkov")
    driver: dict = {"name": name}
    if rules is _DEFAULT:
        rules = [{"id": "wlb.rule"}] if tool == "semgrep" else []
    if rules is not None:
        driver["rules"] = rules
    if version is not None:
        driver["version"] = version
    run: dict = {"tool": {"driver": driver}}
    if results is not None:
        run["results"] = results
    if invocations is not None:
        run["invocations"] = invocations
    return {"version": "2.1.0", "runs": [run]}


def make_run(tool: str = "semgrep", results: list | None = None, *, rules: object = _DEFAULT) -> dict:
    return make_doc(tool, results, rules=rules)["runs"][0]


def physical(text: str) -> dict:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": "a.py"},
            "region": {"startLine": 1, "snippet": {"text": text}},
            "contextRegion": {"snippet": {"text": text}},
        }
    }


def make_result(text: str = CANARY, *, suppressions: object = _DEFAULT) -> dict:
    item: dict = {
        "ruleId": "wlb.rule",
        "message": {"text": "znalezisko"},
        "fingerprints": {"matchBasedId/v1": "abc"},
        "locations": [physical(text)],
    }
    if suppressions is not _DEFAULT:
        item["suppressions"] = suppressions
    return item


def write_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_report(sca_dir: Path, tool: str = "semgrep", doc: dict | None = None) -> Path:
    return write_json(sca_dir / sr.REPORTS[tool].sarif, doc if doc is not None else make_doc(tool))


def write_exit(sca_dir: Path, tool: str, text: str) -> Path:
    sca_dir.mkdir(parents=True, exist_ok=True)
    path = sca_dir / f"{tool}.exit"
    path.write_text(text, encoding="utf-8")
    return path


def summary_env(tmp_path: Path) -> dict[str, str]:
    return {"GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}


def make_info(count: int = 0, *, suppressed: int = 0, tool: str = "semgrep") -> sr.ReportInfo:
    return sr.ReportInfo(
        tool=tool,
        category=tool,
        sha256="0" * 64,
        result_count=count,
        driver_version="",
        rules_digest="0" * 64,
        suppressed_count=suppressed,
    )


# --- kontrakt modułu (#257) ---


def test_reports_outcomes_i_limity():
    assert list(sr.REPORTS) == ["semgrep", "checkov"]
    assert [report.category for report in sr.REPORTS.values()] == ["semgrep", "checkov"]
    assert [report.driver for report in sr.REPORTS.values()] == ["semgrep", "checkov"]
    assert sr.REPORTS["semgrep"].requires_rules is True
    assert sr.REPORTS["checkov"].requires_rules is False
    assert sr.OUTCOMES == ("clean", "findings", "error", "not_run")
    assert sr.MAX_GZIP_BYTES == 10 * 1024 * 1024
    assert sr.MAX_RAW_BYTES == 100 * 1024 * 1024
    assert sr.MAX_RUNS == 20
    assert sr.MAX_RESULTS_PER_RUN == 25_000
    assert sr.MAX_RULES_PER_RUN == 25_000
    assert make_info().suppressed_count == 0


# --- load_report (#257) ---


def test_load_report_przyjmuje_semgrep_i_checkov(tmp_path):
    sem = write_report(tmp_path, "semgrep", make_doc(results=[], rules=[{"id": "r"}]))
    assert sr.load_report(sem, "semgrep")["version"] == "2.1.0"

    bez_wynikow = make_doc(driver_name="SEMGREP OSS")
    assert "results" not in bez_wynikow["runs"][0]
    assert sr.load_report(write_json(tmp_path / "semgrep.sarif", bez_wynikow), "semgrep")["runs"]

    checkov = make_doc(tool="checkov", results=[], rules=[])
    assert sr.load_report(write_json(tmp_path / "checkov.sarif", checkov), "checkov")["version"] == "2.1.0"


def test_load_report_nieznane_narzedzie(tmp_path):
    with pytest.raises(ValueError, match="nieznane"):
        sr.load_report(tmp_path / "x.sarif", "inne")


def test_load_report_odrzuca_zla_strukture(tmp_path):
    cases = [
        ([], "obiektem"),
        ({"version": "2.0.0", "runs": [make_run()]}, "2.1.0"),
        ({"version": "2.1.0", "runs": []}, "przebiegów"),
        ({"version": "2.1.0", "runs": {}}, "przebiegów"),
        ({"version": "2.1.0", "runs": [[]]}, "przebieg"),
        ({"version": "2.1.0", "runs": [{}]}, "narzędzia"),
        ({"version": "2.1.0", "runs": [{"tool": []}]}, "narzędzia"),
        ({"version": "2.1.0", "runs": [{"tool": {"driver": {"version": "1"}}}]}, "narzędzia"),
        (
            {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Checkov", "rules": [{"id": "r"}]}}}]},
            "narzędzia",
        ),
        (
            {
                "version": "2.1.0",
                "runs": [{"tool": {"driver": {"name": "semgrep", "rules": [{"id": "r"}]}}, "results": {}}],
            },
            "results",
        ),
        (
            {
                "version": "2.1.0",
                "runs": [{"tool": {"driver": {"name": "semgrep", "rules": {"id": "r"}}}, "results": []}],
            },
            "rules",
        ),
        (
            {
                "version": "2.1.0",
                "runs": [{"tool": {"driver": {"name": "semgrep", "rules": [{"id": "r"}]}}, "results": None}],
            },
            "results",
        ),
    ]
    for index, (doc, match) in enumerate(cases):
        path = write_json(tmp_path / f"zly-{index}.sarif", doc)
        with pytest.raises(sr.ReportError, match=match):
            sr.load_report(path, "semgrep")


def test_load_report_odrzuca_pliki_specjalne_i_uszkodzone(tmp_path):
    with pytest.raises(sr.ReportError, match="brak raportu"):
        sr.load_report(tmp_path / "semgrep.sarif", "semgrep")

    real = write_report(tmp_path / "real", "semgrep")
    link = tmp_path / "link.sarif"
    link.symlink_to(real)
    with pytest.raises(sr.ReportError, match="dowiązaniem"):
        sr.load_report(link, "semgrep")

    directory = tmp_path / "katalog.sarif"
    directory.mkdir()
    with pytest.raises(sr.ReportError, match="zwykłym plikiem"):
        sr.load_report(directory, "semgrep")

    fifo = tmp_path / "fifo.sarif"
    os.mkfifo(fifo)
    with pytest.raises(sr.ReportError, match="zwykłym plikiem"):
        sr.load_report(fifo, "semgrep")

    bad_utf8 = tmp_path / "utf8.sarif"
    bad_utf8.write_bytes(b"\xff\xfe")
    with pytest.raises(sr.ReportError, match="UTF-8"):
        sr.load_report(bad_utf8, "semgrep")


def test_load_report_bledy_io(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise PermissionError("odmowa")

    original_lstat = os.lstat
    monkeypatch.setattr(sr.os, "lstat", deny)
    with pytest.raises(sr.ReportError, match="nie można odczytać"):
        sr.load_report(tmp_path / "semgrep.sarif", "semgrep")
    assert sr.read_exit_code(tmp_path / "semgrep.exit") == -1

    monkeypatch.setattr(sr.os, "lstat", original_lstat)
    path = write_report(tmp_path, "semgrep")
    monkeypatch.setattr(sr.Path, "read_text", deny)
    with pytest.raises(sr.ReportError, match="nie można odczytać"):
        sr.load_report(path, "semgrep")


def test_load_report_blad_json_nie_ujawnia_tresci(tmp_path):
    path = tmp_path / "semgrep.sarif"
    path.write_text(f'{{"wynik": "{CANARY}"', encoding="utf-8")
    with pytest.raises(sr.ReportError, match="JSON") as exc:
        sr.load_report(path, "semgrep")
    assert CANARY not in str(exc.value)


def test_load_report_limity(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "MAX_RUNS", 1)
    dwa_runs = make_doc(runs=[make_run(), make_run()])
    with pytest.raises(sr.ReportError, match="przebiegów"):
        sr.load_report(write_json(tmp_path / "runs.sarif", dwa_runs), "semgrep")

    monkeypatch.setattr(sr, "MAX_RUNS", sr.MAX_RUNS)
    monkeypatch.setattr(sr, "MAX_RESULTS_PER_RUN", 1)
    dwa_wyniki = make_doc(results=[make_result("a"), make_result("b")])
    with pytest.raises(sr.ReportError, match="wyników"):
        sr.load_report(write_json(tmp_path / "results.sarif", dwa_wyniki), "semgrep")

    monkeypatch.setattr(sr, "MAX_RESULTS_PER_RUN", sr.MAX_RESULTS_PER_RUN)
    monkeypatch.setattr(sr, "MAX_RULES_PER_RUN", 1)
    dwie_reguly = make_doc(rules=[{"id": "a"}, {"id": "b"}])
    with pytest.raises(sr.ReportError, match="reguł"):
        sr.load_report(write_json(tmp_path / "rules.sarif", dwie_reguly), "semgrep")

    monkeypatch.setattr(sr, "MAX_RULES_PER_RUN", sr.MAX_RULES_PER_RUN)
    monkeypatch.setattr(sr, "MAX_RAW_BYTES", 10)
    with pytest.raises(sr.ReportError, match="limit rozmiaru"):
        sr.load_report(write_report(tmp_path, "semgrep"), "semgrep")


def test_load_report_wykrywa_nieudane_wykonanie(tmp_path):
    doc = make_doc(invocations=[{"executionSuccessful": True}, {"executionSuccessful": False}])
    with pytest.raises(sr.ReportError) as exc:
        sr.load_report(write_json(tmp_path / "semgrep.sarif", doc), "semgrep")
    assert str(exc.value) == "skaner zgłosił nieudane wykonanie"

    ok = make_doc(invocations=[{"executionSuccessful": True}, "nie-obiekt"])
    assert sr.load_report(write_json(tmp_path / "ok.sarif", ok), "semgrep")["version"] == "2.1.0"


def test_load_report_semgrep_wymaga_regul(tmp_path):
    with pytest.raises(sr.ReportError, match="reguł"):
        sr.load_report(write_json(tmp_path / "puste.sarif", make_doc(rules=[])), "semgrep")
    with pytest.raises(sr.ReportError, match="reguł"):
        sr.load_report(write_json(tmp_path / "brak.sarif", make_doc(rules=None)), "semgrep")
    # checkov przy czystym skanie legalnie wypisuje rules: []
    checkov = make_doc(tool="checkov", results=[], rules=[])
    assert sr.load_report(write_json(tmp_path / "checkov.sarif", checkov), "checkov")["runs"]


# --- classify (#257) ---


@pytest.mark.parametrize(
    ("exit_code", "info", "expected"),
    [
        (None, None, "not_run"),
        (None, make_info(0), "not_run"),
        (0, None, "error"),
        (0, make_info(0), "clean"),
        (0, make_info(1), "findings"),
        (1, None, "error"),
        (1, make_info(0), "error"),
        (1, make_info(1), "findings"),
        (2, make_info(1), "error"),
        (-1, make_info(0), "error"),
    ],
)
def test_classify(exit_code, info, expected):
    assert sr.classify(exit_code, info) == expected


# --- read_exit_code (#257) ---


def test_read_exit_code_przypadki(tmp_path):
    good = tmp_path / "good.exit"
    good.write_text("1\n", encoding="utf-8")
    assert sr.read_exit_code(good) == 1

    zero = tmp_path / "zero.exit"
    zero.write_text("0\n", encoding="utf-8")
    assert sr.read_exit_code(zero) == 0

    negative = tmp_path / "negative.exit"
    negative.write_text(" -1 \n", encoding="utf-8")
    assert sr.read_exit_code(negative) == -1

    empty = tmp_path / "empty.exit"
    empty.write_text("", encoding="utf-8")
    assert sr.read_exit_code(empty) == -1

    garbage = tmp_path / "garbage.exit"
    garbage.write_text("nie-liczba\n", encoding="utf-8")
    assert sr.read_exit_code(garbage) == -1

    assert sr.read_exit_code(tmp_path / "brak.exit") is None

    link = tmp_path / "link.exit"
    link.symlink_to(good)
    assert sr.read_exit_code(link) == -1

    directory = tmp_path / "katalog.exit"
    directory.mkdir()
    assert sr.read_exit_code(directory) == -1

    fifo = tmp_path / "fifo.exit"
    os.mkfifo(fifo)
    assert sr.read_exit_code(fifo) == -1

    bad_utf8 = tmp_path / "utf8.exit"
    bad_utf8.write_bytes(b"\xff")
    assert sr.read_exit_code(bad_utf8) == -1


# --- sanitize (#257) ---


def test_sanitize_usuwa_fragmenty_kodu_i_czysci_notyfikacje():
    rules = [{"id": "wlb.rule", "shortDescription": {"text": "opis reguły"}}]
    notifications = [
        {"message": {"text": "Syntax error at line 1:\n" + CANARY, "markdown": f"**{CANARY}**"}},
        {"message": {"text": "x" * 300 + CANARY}},
        {"message": "nie-obiekt"},
        {"message": {"text": 42, "markdown": "usunąć"}},
    ]
    doc = make_doc(
        results=[
            {
                "ruleId": "wlb.rule",
                "message": {"text": "znalezisko"},
                "fingerprints": {"matchBasedId/v1": "abc"},
                "suppressions": [{"kind": "inSource"}],
                "locations": [physical(CANARY + "-loc")],
                "relatedLocations": [physical(CANARY + "-rel")],
                "codeFlows": [{"threadFlows": [{"locations": [{"location": physical(CANARY + "-flow")}]}]}],
                "stacks": [{"frames": [{"location": physical(CANARY + "-stack")}]}],
                "fixes": [{"physicalLocation": physical(CANARY + "-fix")["physicalLocation"]}],
            }
        ],
        rules=rules,
        invocations=[
            {
                "toolExecutionNotifications": notifications,
                "toolConfigurationNotifications": notifications,
            },
            "nie-obiekt",
            {"toolExecutionNotifications": {"zły": "typ"}},
        ],
    )
    original = deepcopy(doc)
    clean = sr.sanitize(doc)

    assert doc == original
    assert clean is not doc
    serialized = json.dumps(clean, ensure_ascii=False)
    assert CANARY not in serialized

    result = clean["runs"][0]["results"][0]
    location = result["locations"][0]["physicalLocation"]
    assert location["region"] == {"startLine": 1}
    assert "contextRegion" not in location
    assert result["fingerprints"] == {"matchBasedId/v1": "abc"}
    assert result["message"] == {"text": "znalezisko"}
    assert result["ruleId"] == "wlb.rule"
    assert clean["runs"][0]["tool"]["driver"]["rules"] == rules

    first = clean["runs"][0]["invocations"][0]["toolExecutionNotifications"][0]["message"]
    assert first["text"] == "Syntax error at line 1:…"
    assert "markdown" not in first
    long_message = clean["runs"][0]["invocations"][0]["toolExecutionNotifications"][1]["message"]
    assert long_message["text"] == "x" * 200 + "…"
    assert "markdown" not in clean["runs"][0]["invocations"][0]["toolExecutionNotifications"][3]["message"]


def test_sanitize_nie_zmienia_wejscia_bez_runs():
    doc = {"version": "2.1.0", "runs": "nie-lista"}
    clean = sr.sanitize(doc)
    assert clean == doc
    assert clean is not doc


def test_sanitize_brzegowe_ksztalty_i_notyfikacje():
    doc = {
        "runs": [
            "nie-obiekt",
            {
                "results": "nie-lista",
                "invocations": [
                    {"toolExecutionNotifications": ["nie-obiekt", {"message": {"text": "ok"}}]},
                ],
            },
            {
                "results": [
                    {
                        "physicalLocation": {
                            "region": "nie-obiekt",
                            "contextRegion": {"snippet": {"text": CANARY}},
                        }
                    }
                ]
            },
        ]
    }
    clean = sr.sanitize(doc)
    assert CANARY not in json.dumps(clean, ensure_ascii=False)
    assert "contextRegion" not in clean["runs"][2]["results"][0]["physicalLocation"]


# --- wyciszone wyniki (#257) ---


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("nie-obiekt", False),
        ({}, False),
        ({"suppressions": None}, False),
        ({"suppressions": {}}, False),
        ({"suppressions": []}, False),
        ({"suppressions": [{"kind": "inSource"}]}, True),
        ({"suppressions": [{"status": "accepted"}]}, True),
        ({"suppressions": [{"status": "rejected"}]}, False),
        ({"suppressions": [{"status": "underReview"}]}, False),
        ({"suppressions": [{"kind": "inSource"}, {"status": "rejected"}]}, False),
        ({"suppressions": ["nie-obiekt"]}, True),
    ],
)
def test_is_suppressed(result, expected):
    assert sr._is_suppressed(result) is expected


def test_prepare_same_wyciszone_wyniki_to_clean(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(
        sca,
        "semgrep",
        make_doc(
            results=[
                make_result(suppressions=[{"kind": "inSource"}]),
                make_result(suppressions=[{"status": "accepted"}]),
            ]
        ),
    )
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "clean"
    assert entry["publish"] is True
    assert entry["result_count"] == 0
    assert entry["suppressed_count"] == 2


def test_prepare_wyciszone_i_aktywne_to_findings(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "1\n")
    write_report(
        sca,
        "semgrep",
        make_doc(
            results=[
                make_result("ukryty", suppressions=[{"kind": "inSource"}]),
                make_result("aktywny", suppressions=[{"status": "rejected"}]),
            ]
        ),
    )
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "findings"
    assert entry["result_count"] == 1
    assert entry["suppressed_count"] == 1
    # GitHub ignoruje `suppressions` — wyciszony wynik nie może stać się otwartym alertem (PR #324)
    published = json.loads((out / "semgrep.sarif").read_text(encoding="utf-8"))
    (result,) = published["runs"][0]["results"]
    assert result["suppressions"] == [{"status": "rejected"}]
    assert "ukryty" not in json.dumps(published)


def test_drop_suppressed_nie_zmienia_wejscia_i_pomija_nieliste():
    doc = make_doc(results=[make_result(suppressions=[{"kind": "inSource"}]), make_result()])
    doc["runs"].append({"tool": {"driver": {"name": "Semgrep OSS"}}, "results": "nie-lista"})
    doc["runs"].append("nie-obiekt")
    before = deepcopy(doc)
    kept = sr.drop_suppressed(doc)
    assert doc == before
    assert len(kept["runs"][0]["results"]) == 1
    assert "suppressions" not in kept["runs"][0]["results"][0]
    assert kept["runs"][1]["results"] == "nie-lista"
    assert sr.drop_suppressed({"version": "2.1.0"}) == {"version": "2.1.0"}


# --- prepare: ścieżka szczęśliwa i publikacja (#257) ---


def test_prepare_czysty_semgrep_i_manifest(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    rules = [{"id": "wlb.rule", "shortDescription": {"text": "Opis"}}]
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[], rules=rules, version="1.2.3"))

    manifest = sr.prepare(sca, out, summary_env(tmp_path))
    semgrep = manifest["reports"][0]
    assert semgrep["outcome"] == "clean"
    assert semgrep["publish"] is True
    assert semgrep["exit_code"] == 0
    assert semgrep["result_count"] == 0
    assert semgrep["suppressed_count"] == 0
    assert semgrep["driver_version"] == "1.2.3"
    expected_digest = hashlib.sha256(
        json.dumps([rules], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert semgrep["rules_digest"] == expected_digest

    payload = (out / "semgrep.sarif").read_bytes()
    assert semgrep["sha256"] == hashlib.sha256(payload).hexdigest()
    assert json.loads(payload)["runs"][0]["results"] == []
    assert manifest["reports"][1]["outcome"] == "not_run"
    assert not (out / "checkov.sarif").exists()
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_prepare_bez_wersji_drivera(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[], version=None))
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "clean"
    assert entry["driver_version"] == ""


def test_prepare_findings_sanityzuje_plik_i_podsumowanie(tmp_path, capsys):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "1\n")
    write_report(
        sca,
        "semgrep",
        make_doc(
            results=[make_result()],
            invocations=[{"toolExecutionNotifications": [{"message": {"text": "błąd\n" + CANARY}}]}],
        ),
    )
    env = summary_env(tmp_path)
    manifest = sr.prepare(sca, out, env)

    entry = manifest["reports"][0]
    assert entry["outcome"] == "findings"
    assert entry["publish"] is True
    assert entry["result_count"] == 1
    output = (out / "semgrep.sarif").read_text(encoding="utf-8")
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert CANARY not in output
    assert CANARY not in summary
    assert CANARY not in json.dumps(manifest, ensure_ascii=False)
    assert "snippet" not in output
    assert "contextRegion" not in output
    assert capsys.readouterr().out == ""


def test_prepare_exit_0_z_aktywnymi_wynikami_to_findings(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[make_result()]))
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "findings"
    assert entry["publish"] is True
    assert entry["result_count"] == 1
    assert (out / "semgrep.sarif").is_file()


def test_prepare_niespojny_kod_wyjscia_nie_publikuje(tmp_path):
    cases = [
        ("1\n", [], "nie zawiera wyników"),
        ("2\n", [make_result()], "błąd narzędzia"),
        ("-2\n", [make_result()], "błąd narzędzia"),
        ("1\n", [make_result(suppressions=[{"kind": "inSource"}])], "nie zawiera wyników"),
    ]
    for index, (exit_text, results, reason) in enumerate(cases):
        sca = tmp_path / f"sca-{index}"
        out = tmp_path / f"out-{index}"
        write_exit(sca, "semgrep", exit_text)
        write_report(sca, "semgrep", make_doc(results=results))
        entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
        assert entry["outcome"] == "error"
        assert entry["publish"] is False
        assert reason in entry["reason"]
        assert "sha256" not in entry
        assert "result_count" not in entry
        assert "suppressed_count" not in entry
        assert not (out / "semgrep.sarif").exists()


def test_prepare_brak_exit_nie_czyta_sarif(tmp_path, monkeypatch):
    sca = tmp_path / "sca"
    sca.mkdir()
    (sca / "semgrep.sarif").write_text("to nie jest JSON", encoding="utf-8")

    def fail(*args, **kwargs):
        raise AssertionError("nie wolno czytać SARIF bez pliku .exit")

    monkeypatch.setattr(sr, "load_report", fail)
    manifest = sr.prepare(sca, tmp_path / "out", summary_env(tmp_path))
    assert [entry["outcome"] for entry in manifest["reports"]] == ["not_run", "not_run"]
    assert "reason" not in manifest["reports"][0]
    assert not (tmp_path / "out" / "semgrep.sarif").exists()


def test_prepare_smieciowy_exit_to_error(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "nie-liczba\n")
    write_report(sca, "semgrep", make_doc(results=[]))
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "error"
    assert entry["exit_code"] == -1
    assert "błąd narzędzia" in entry["reason"]
    assert not (out / "semgrep.sarif").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "brak",
        "symlink",
        "katalog",
        "fifo",
        "uszkodzony-json",
        "zla-wersja",
        "puste-runs",
        "zly-driver",
        "results-nie-lista",
        "bez-regul",
        "nieudane-wykonanie",
    ],
)
def test_prepare_blad_raportu_nie_tworzy_pliku(tmp_path, kind):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    sca.mkdir()
    write_exit(sca, "semgrep", "0\n")
    target = sca / "semgrep.sarif"
    if kind == "symlink":
        real = write_report(tmp_path / "real", "semgrep")
        target.symlink_to(real)
    elif kind == "katalog":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)
    elif kind == "uszkodzony-json":
        target.write_text(f'{{"wynik": "{CANARY}"', encoding="utf-8")
    elif kind == "zla-wersja":
        doc = make_doc(results=[])
        doc["version"] = "2.0.0"
        write_json(target, doc)
    elif kind == "puste-runs":
        write_json(target, {"version": "2.1.0", "runs": []})
    elif kind == "zly-driver":
        write_json(target, make_doc(tool="checkov", results=[]))
    elif kind == "results-nie-lista":
        doc = make_doc(results=[])
        doc["runs"][0]["results"] = {}
        write_json(target, doc)
    elif kind == "bez-regul":
        write_json(target, make_doc(results=[], rules=[]))
    elif kind == "nieudane-wykonanie":
        write_json(target, make_doc(results=[], invocations=[{"executionSuccessful": False}]))
    # kind == "brak": plik celowo nie powstaje

    manifest = sr.prepare(sca, out, summary_env(tmp_path))
    entry = manifest["reports"][0]
    assert entry["outcome"] == "error"
    assert entry["publish"] is False
    assert entry["reason"]
    assert CANARY not in entry["reason"]
    assert CANARY not in json.dumps(manifest, ensure_ascii=False)
    assert CANARY not in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert not (out / "semgrep.sarif").exists()


def test_prepare_limity_i_gzip(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "MAX_RESULTS_PER_RUN", 1)
    sca = tmp_path / "sca-results"
    out = tmp_path / "out-results"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[make_result("a"), make_result("b")]))
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "error"
    assert "wyników" in entry["reason"]
    assert not (out / "semgrep.sarif").exists()

    monkeypatch.setattr(sr, "MAX_RESULTS_PER_RUN", sr.MAX_RESULTS_PER_RUN)
    monkeypatch.setattr(sr, "MAX_GZIP_BYTES", 1)
    sca = tmp_path / "sca-gzip"
    out = tmp_path / "out-gzip"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[]))
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "error"
    assert "gzip" in entry["reason"]
    assert not (out / "semgrep.sarif").exists()


# --- prepare: porządki i artefakty CI (#257) ---


def test_prepare_blad_zapisu_raportu(tmp_path, monkeypatch):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[]))

    def deny(self, data):
        raise PermissionError("brak miejsca")

    monkeypatch.setattr(sr.Path, "write_bytes", deny)
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "error"
    assert "nie udało się zapisać raportu" in entry["reason"]
    assert not (out / "semgrep.sarif").exists()


def test_prepare_czysci_tylko_oczekiwane_pliki(tmp_path):
    out = tmp_path / "a" / "b"
    out.mkdir(parents=True)
    (out / "semgrep.sarif").write_text("stary", encoding="utf-8")
    (out / "checkov.sarif").write_text("stary", encoding="utf-8")
    (out / "manifest.json").write_text("stary", encoding="utf-8")
    keep = out / "inny.txt"
    keep.write_text("zostaw", encoding="utf-8")

    sr.prepare(tmp_path / "brak-sca", out, summary_env(tmp_path))
    assert not (out / "semgrep.sarif").exists()
    assert not (out / "checkov.sarif").exists()
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["schema"] == 1
    assert keep.read_text(encoding="utf-8") == "zostaw"


def test_prepare_github_output_i_summary_oraz_metadane(tmp_path, capsys):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[], version="9.9.9"))
    output = tmp_path / "github-output"
    output.write_text("poprzedni=1\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("## poprzedni\n", encoding="utf-8")
    env = {
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_SHA": "abc123",
        "GITHUB_REF": "refs/pull/257/merge",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "3",
    }
    manifest = sr.prepare(sca, out, env)

    assert manifest["run"] == {
        "repository": "owner/repo",
        "sha": "abc123",
        "ref": "refs/pull/257/merge",
        "event": "pull_request",
        "run_id": "42",
        "run_attempt": "3",
    }
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "poprzedni=1"
    assert lines[-2:] == ["semgrep=clean", "checkov=not_run"]

    text = summary.read_text(encoding="utf-8")
    assert "## poprzedni" in text
    assert "| Narzędzie | Kategoria | Wynik skanu | Wyników | Wersja | Reguły | Publikacja |" in text
    digest = manifest["reports"][0]["rules_digest"][:12]
    assert f"| semgrep | semgrep | clean | 0 | 9.9.9 | {digest} | tak |" in text
    assert "| checkov | checkov | not_run | — | — | — | nie |" in text
    assert capsys.readouterr().out == ""


def test_prepare_bez_summary_pisze_tabele_na_stdout(tmp_path, capsys):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[]))
    sr.prepare(sca, out, {})
    stdout = capsys.readouterr().out
    assert "| Narzędzie |" in stdout
    assert "| semgrep | semgrep | clean | 0 |" in stdout
    assert "| checkov | checkov | not_run |" in stdout


def test_rules_digest_jest_stabilny_i_zalezy_od_regul(tmp_path):
    rules_a = [{"id": "r", "help": {"text": "x", "uri": "u"}}]
    rules_b = [{"help": {"uri": "u", "text": "x"}, "id": "r"}]
    rules_c = [{"id": "inna"}]

    def digest(name, rules):
        sca = tmp_path / name / "sca"
        out = tmp_path / name / "out"
        write_exit(sca, "semgrep", "0\n")
        write_report(sca, "semgrep", make_doc(results=[], rules=rules))
        return sr.prepare(sca, out, summary_env(tmp_path / name))["reports"][0]["rules_digest"]

    assert digest("a", rules_a) == digest("b", rules_b)  # sort_keys ujednolica kolejność pól
    assert digest("c", rules_a) != digest("d", rules_c)


# --- CLI (#257) ---


def test_main_przez_cli_i_bledy_uzycia(tmp_path, monkeypatch, capsys):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[]))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    assert sr.main(["prepare", "--sca-dir", str(sca), "--out-dir", str(out)]) == 0
    assert (out / "manifest.json").is_file()

    monkeypatch.setattr(sys, "argv", ["sarif_report.py", "prepare", "--sca-dir", str(sca), "--out-dir", str(out)])
    assert sr.main() == 0

    assert sr.main([]) == 2
    assert sr.main(["prepare", "--sca-dir", str(sca)]) == 2
    capsys.readouterr()


def test_skrypt_uruchomiony_jako_main(tmp_path, monkeypatch):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[]))
    monkeypatch.setattr(
        sys,
        "argv",
        ["sarif_report.py", "prepare", "--sca-dir", str(sca), "--out-dir", str(out)],
    )
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "ci" / "sarif_report.py"), run_name="__main__")
    assert exc.value.code == 0
    assert (out / "manifest.json").is_file()


def test_skrypt_jest_wykonywalny_i_dziala_w_subprocessie(tmp_path):
    script = ROOT / "ci" / "sarif_report.py"
    assert os.access(script, os.X_OK)
    assert script.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3")

    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[]))
    env = os.environ.copy()
    env.pop("GITHUB_STEP_SUMMARY", None)
    env.pop("GITHUB_OUTPUT", None)
    done = subprocess.run(  # noqa: S603 - uruchamiamy lokalny skrypt repozytorium
        [str(script), "prepare", "--sca-dir", str(sca), "--out-dir", str(out)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0
    assert "| Narzędzie |" in done.stdout
    assert (out / "manifest.json").is_file()


def test_prepare_wersja_semgrep_z_semantic_version(tmp_path):
    # semgrep 1.178.0 nie ma driver.version, tylko semanticVersion (#257)
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    doc = make_doc(results=[], version=None)
    doc["runs"][0]["tool"]["driver"]["semanticVersion"] = "1.178.0"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", doc)
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["driver_version"] == "1.178.0"
