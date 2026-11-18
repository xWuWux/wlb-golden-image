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
    tmp_path.mkdir(parents=True, exist_ok=True)
    return {"GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}


def make_info(count: int = 0, *, suppressed: int = 0, tool: str = "semgrep") -> sr.ReportInfo:
    return sr.ReportInfo(
        tool=tool,
        category=tool,
        sha256="0" * 64,
        result_count=count,
        driver_version="",
        sarif_rules_metadata_digest="0" * 64,
        suppressed_count=suppressed,
    )


# --- kontrakt modułu (#257) ---


def test_reports_outcomes_i_limity():
    assert list(sr.REPORTS) == ["semgrep", "checkov"]
    assert [report.category for report in sr.REPORTS.values()] == ["semgrep", "checkov"]
    assert [report.drivers for report in sr.REPORTS.values()] == [("Semgrep OSS", "Semgrep"), ("Checkov",)]
    assert sr.REPORTS["semgrep"].requires_rules is True
    assert sr.REPORTS["checkov"].requires_rules is False
    assert sr.OUTCOMES == ("clean", "findings", "error", "not_run")
    assert sr.MAX_GZIP_BYTES == 10 * 1024 * 1024
    assert sr.MAX_RAW_BYTES == 50 * 1024 * 1024
    assert sr.MAX_JSON_DEPTH == 64
    assert sr.RUNS_PER_REPORT == 1
    assert sr.MAX_RESULTS_PER_RUN == 25_000
    assert sr.MAX_RULES_PER_RUN == 25_000
    assert make_info().suppressed_count == 0


# --- load_report (#257) ---


def test_load_report_przyjmuje_semgrep_i_checkov(tmp_path):
    sem = write_report(tmp_path, "semgrep", make_doc(results=[], rules=[{"id": "r"}]))
    assert sr.load_report(sem, "semgrep")["version"] == "2.1.0"

    bez_wynikow = make_doc(driver_name="Semgrep")
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
                "runs": [{"tool": {"driver": {"name": "Semgrep OSS", "rules": [{"id": "r"}]}}, "results": {}}],
            },
            "results",
        ),
        (
            {
                "version": "2.1.0",
                "runs": [{"tool": {"driver": {"name": "Semgrep OSS", "rules": {"id": "r"}}}, "results": []}],
            },
            "rules",
        ),
        (
            {
                "version": "2.1.0",
                "runs": [{"tool": {"driver": {"name": "Semgrep OSS", "rules": [{"id": "r"}]}}, "results": None}],
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
    # GitHub odrzuca wiele przebiegów tej samej kategorii w jednym pliku (zmiana z 07.2025)
    dwa_runs = make_doc(runs=[make_run(), make_run()])
    with pytest.raises(sr.ReportError, match="dokładnie jeden przebieg"):
        sr.load_report(write_json(tmp_path / "runs.sarif", dwa_runs), "semgrep")

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

    bad = make_doc(invocations=[{"executionSuccessful": True}, "nie-obiekt"])
    with pytest.raises(sr.ReportError, match="element invocations nie jest obiektem"):
        sr.load_report(write_json(tmp_path / "bad.sarif", bad), "semgrep")


def test_load_report_walidacja_invocations_i_notyfikacji(tmp_path):
    bad_inv = make_doc(invocations="nie-lista")
    with pytest.raises(sr.ReportError, match="invocations nie jest listą"):
        sr.load_report(write_json(tmp_path / "bad_inv.sarif", bad_inv), "semgrep")

    bad_exec_notifs = make_doc(invocations=[{"toolExecutionNotifications": "nie-lista"}])
    with pytest.raises(sr.ReportError, match="toolExecutionNotifications nie jest listą"):
        sr.load_report(write_json(tmp_path / "bad_exec_notifs.sarif", bad_exec_notifs), "semgrep")

    bad_cfg_notifs = make_doc(invocations=[{"toolConfigurationNotifications": "nie-lista"}])
    with pytest.raises(sr.ReportError, match="toolConfigurationNotifications nie jest listą"):
        sr.load_report(write_json(tmp_path / "bad_cfg_notifs.sarif", bad_cfg_notifs), "semgrep")

    bad_notif = make_doc(invocations=[{"toolExecutionNotifications": ["nie-obiekt"]}])
    with pytest.raises(sr.ReportError, match="notyfikacja nie jest obiektem"):
        sr.load_report(write_json(tmp_path / "bad_notif.sarif", bad_notif), "semgrep")

    error_exec_notif = make_doc(invocations=[{"toolExecutionNotifications": [{"level": "error"}]}])
    with pytest.raises(sr.ReportError, match="notyfikacja level=error"):
        sr.load_report(write_json(tmp_path / "error_exec.sarif", error_exec_notif), "semgrep")

    error_cfg_notif = make_doc(invocations=[{"toolConfigurationNotifications": [{"level": "error"}]}])
    with pytest.raises(sr.ReportError, match="notyfikacja level=error"):
        sr.load_report(write_json(tmp_path / "error_cfg.sarif", error_cfg_notif), "semgrep")

    ok_notifs = make_doc(
        invocations=[
            {
                "executionSuccessful": True,
                "toolExecutionNotifications": [{"level": "warning"}, {"level": "note"}, {}],
                "toolConfigurationNotifications": [{"level": "warning"}],
            }
        ]
    )
    assert sr.load_report(write_json(tmp_path / "ok_notifs.sarif", ok_notifs), "semgrep")["version"] == "2.1.0"


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


# --- export_sarif (#257) ---


def test_export_sarif_usuwa_fragmenty_kodu_i_czysci_notyfikacje():
    rules = [
        {
            "id": "wlb.rule",
            "name": "wlb-name",
            "shortDescription": {"text": "opis reguły"},
            "fullDescription": {"text": "pełny opis reguły"},
            "help": {"text": "pomoc", "markdown": "**pomoc**"},
            "helpUri": "https://example.com/rule",
            "defaultConfiguration": {"level": "warning"},
            "properties": {
                "tags": ["security", "cwe-798"],
                "precision": "high",
                "security-severity": "8.0",
                "problem.severity": "warning",
            },
        }
    ]
    notifications = [
        {
            "descriptor": {"id": "Syntax error"},
            "level": "warning",
            "message": {"text": "Syntax error at line 1:\n" + CANARY, "markdown": f"**{CANARY}**"},
        },
        {"descriptor": "nie-obiekt", "message": {"text": "unexpected token " + CANARY}},
        {"message": "nie-obiekt"},
    ]
    doc = make_doc(
        results=[
            {
                "ruleId": "wlb.rule",
                "ruleIndex": 0,
                "level": "warning",
                "message": {"text": "znalezisko z kodem " + CANARY, "markdown": f"**{CANARY}**", "arguments": [CANARY]},
                "fingerprints": {"matchBasedId/v1": "abc"},
                "partialFingerprints": {"primaryLocationLineHash": "hash123"},
                "properties": {"tag": CANARY},
                "suppressions": [{"kind": "weird"}],
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": "a.py", "uriBaseId": "%SRCROOT%"},
                            "region": {
                                "startLine": 1,
                                "startColumn": 5,
                                "endLine": 1,
                                "endColumn": 10,
                                "snippet": {"text": CANARY},
                            },
                            "contextRegion": {"snippet": {"text": CANARY}},
                        }
                    }
                ],
                "relatedLocations": [physical(CANARY + "-rel")],
                "codeFlows": [{"threadFlows": [{"locations": [{"location": physical(CANARY + "-flow")}]}]}],
                "stacks": [{"frames": [{"location": physical(CANARY + "-stack")}]}],
                "fixes": [{"physicalLocation": physical(CANARY + "-fix")["physicalLocation"]}],
            }
        ],
        rules=rules,
        invocations=[
            {
                "executionSuccessful": True,
                "toolExecutionNotifications": notifications,
            },
            "nie-obiekt",
            {"toolExecutionNotifications": "nie-lista"},
        ],
    )
    doc["runs"][0]["automationDetails"] = {"id": "run-id-1"}
    doc["runs"][0]["tool"]["driver"]["informationUri"] = "https://semgrep.dev"
    doc["runs"][0]["artifacts"] = [{"location": {"uri": "a.py"}, "contents": {"text": CANARY}}]
    doc["runs"][0]["originalUriBaseIds"] = {"%SRCROOT%": {"uri": f"file:///{CANARY}"}}

    original = deepcopy(doc)
    clean = sr.export_sarif(doc)

    assert doc == original
    serialized = json.dumps(clean, ensure_ascii=False)
    assert CANARY not in serialized
    assert clean["$schema"] == "https://json.schemastore.org/sarif-2.1.0.json"
    assert clean["version"] == "2.1.0"

    run = clean["runs"][0]
    # kategorię ustala workflow, nie raport
    assert "automationDetails" not in run
    driver = run["tool"]["driver"]
    assert driver["informationUri"] == "https://semgrep.dev"
    assert driver["rules"][0]["id"] == "wlb.rule"
    assert driver["rules"][0]["properties"]["tags"] == ["security", "cwe-798"]
    assert driver["rules"][0]["properties"]["security-severity"] == "8.0"

    result = run["results"][0]
    assert result["ruleId"] == "wlb.rule"
    # indeks reguły nie jest przenoszony (eksport może pominąć reguły bez id)
    assert "ruleIndex" not in result
    assert result["level"] == "warning"
    assert result["message"] == {"text": "opis reguły"}
    assert result["partialFingerprints"] == {"primaryLocationLineHash": "hash123"}
    assert "fingerprints" not in result
    assert "properties" not in result
    assert "suppressions" not in result
    assert "relatedLocations" not in result
    assert "codeFlows" not in result

    location = result["locations"][0]["physicalLocation"]
    assert location["artifactLocation"] == {"uri": "a.py", "uriBaseId": "%SRCROOT%"}
    assert location["region"] == {"startLine": 1, "startColumn": 5, "endLine": 1, "endColumn": 10}
    assert "snippet" not in location["region"]
    assert "contextRegion" not in location

    notifs = run["invocations"][0]["toolExecutionNotifications"]
    assert notifs[0]["descriptor"] == {"id": "Syntax error"}
    assert notifs[0]["message"] == {"text": "Syntax error (szczegóły: skan lokalny, make security)"}
    assert notifs[0]["level"] == "warning"
    assert notifs[1]["message"] == {"text": "komunikat narzędzia (szczegóły: skan lokalny, make security)"}
    assert "descriptor" not in notifs[1]


def test_export_sarif_puste_runs_i_brzegowe_ksztalty():
    assert sr.export_sarif({"runs": []}) == {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [],
    }
    assert sr.export_sarif({}) == {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [],
    }
    doc = {
        "runs": [
            "nie-obiekt",
            {
                "tool": "nie-obiekt",
                "results": [],
            },
        ]
    }
    exported = sr.export_sarif(doc)
    assert len(exported["runs"]) == 1
    assert exported["runs"][0]["tool"]["driver"]["name"] == ""


def test_export_sarif_odrzuca_brak_reguly_lub_lokalizacji():
    cases = [
        "nie-obiekt",
        {},
        {"ruleId": ""},
        {"ruleId": "r", "locations": []},
        {"ruleId": "r", "locations": "nie-lista"},
        {"ruleId": "r", "locations": ["nie-obiekt"]},
        {"ruleId": "r", "locations": [{"physicalLocation": {}}]},
        {"ruleId": "r", "locations": [{"physicalLocation": {"artifactLocation": {}}}]},
        {"ruleId": "r", "locations": [{"physicalLocation": {"artifactLocation": {"uri": ""}}}]},
        {"ruleId": "r", "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}}}]},
        {"ruleId": "r", "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}, "region": {}}}]},
        {
            "ruleId": "r",
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}, "region": {"startLine": 0}}}],
        },
        {
            "ruleId": "r",
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}, "region": {"startLine": "1"}}}],
        },
        {
            "ruleId": "r",
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a.py"}, "region": {"startLine": True}}}],
        },
    ]
    for result in cases:
        doc = make_doc(results=[result])
        with pytest.raises(sr.ReportError, match="wynik"):
            sr.export_sarif(doc)


def test_prepare_notyfikacja_error_nie_publikuje_a_warning_daje_clean(tmp_path):
    sca_err = tmp_path / "sca_err"
    out_err = tmp_path / "out_err"
    write_exit(sca_err, "semgrep", "0\n")
    write_report(
        sca_err,
        "semgrep",
        make_doc(
            results=[],
            invocations=[{"executionSuccessful": True, "toolExecutionNotifications": [{"level": "error"}]}],
        ),
    )
    manifest_err = sr.prepare(sca_err, out_err, summary_env(tmp_path / "err"))
    entry_err = manifest_err["reports"][0]
    assert entry_err["outcome"] == "error", "contract:scanner-error"  # 341
    assert entry_err["publish"] is False
    assert "notyfikacja level=error" in entry_err["reason"]
    assert not (out_err / "semgrep.sarif").exists()

    sca_warn = tmp_path / "sca_warn"
    out_warn = tmp_path / "out_warn"
    write_exit(sca_warn, "semgrep", "0\n")
    write_report(
        sca_warn,
        "semgrep",
        make_doc(
            results=[],
            invocations=[
                {
                    "executionSuccessful": True,
                    "toolExecutionNotifications": [
                        {"descriptor": {"id": "Syntax error"}, "level": "warning", "message": {"text": "błąd pliku"}}
                    ],
                }
            ],
        ),
    )
    manifest_warn = sr.prepare(sca_warn, out_warn, summary_env(tmp_path / "warn"))
    entry_warn = manifest_warn["reports"][0]
    assert entry_warn["outcome"] == "clean"
    assert entry_warn["publish"] is True
    assert (out_warn / "semgrep.sarif").is_file()


# --- wyciszone wyniki (#257) ---


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("nie-obiekt", False),
        ({}, False),
        ({"suppressions": None}, False),
        ({"suppressions": {}}, False),
        ({"suppressions": []}, False),
        ({"suppressions": [{}]}, False),
        ({"suppressions": [{"status": "accepted"}]}, False),
        ({"suppressions": [{"kind": "weird"}]}, False),
        ({"suppressions": [{"kind": "inSource", "status": "rejected"}]}, False),
        ({"suppressions": [{"kind": "inSource", "status": "underReview"}]}, False),
        ({"suppressions": [{"kind": "inSource", "status": "bogus"}]}, False),
        ({"suppressions": [{"kind": "inSource"}, {}]}, False),
        ({"suppressions": [{"kind": "inSource"}]}, True),
        ({"suppressions": [{"kind": "external", "status": "accepted"}]}, True),
        ({"suppressions": ["nie-obiekt"]}, False),
        ({"suppressions": [{"kind": "inSource"}, None]}, False),
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
                make_result(suppressions=[{"kind": "external", "status": "accepted"}]),
            ]
        ),
    )
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "clean"
    assert entry["publish"] is True
    assert entry["result_count"] == 0
    assert entry["suppressed_count"] == 2


def test_prepare_puste_suppressions_to_findings_i_jest_w_pliku(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "1\n")
    write_report(
        sca,
        "semgrep",
        make_doc(
            results=[
                make_result(suppressions=[{}]),
            ]
        ),
    )
    entry = sr.prepare(sca, out, summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "findings"
    assert entry["publish"] is True
    assert entry["result_count"] == 1
    assert entry["suppressed_count"] == 0
    published = json.loads((out / "semgrep.sarif").read_text(encoding="utf-8"))
    assert len(published["runs"][0]["results"]) == 1
    assert published["runs"][0]["results"][0]["ruleId"] == "wlb.rule"


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
                make_result("aktywny", suppressions=[{"kind": "inSource", "status": "rejected"}]),
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
    assert "suppressions" not in result
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
    assert sr.drop_suppressed("nie-obiekt") == "nie-obiekt"


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
    assert semgrep["sarif_rules_metadata_digest"] == expected_digest

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


def test_prepare_awaria_narzedzia_powod_z_kodu_wyjscia(tmp_path):
    # semgrep 1.178.0 z nieistniejącym zestawem reguł: kod 7 i poprawny SARIF bez reguł (#257)
    sca = tmp_path / "sca"
    write_exit(sca, "semgrep", "7\n")
    write_report(sca, "semgrep", make_doc(results=[], rules=[]))
    entry = sr.prepare(sca, tmp_path / "out", summary_env(tmp_path))["reports"][0]
    assert entry["outcome"] == "error"
    assert entry["reason"] == "kod wyjścia skanera 7 oznacza błąd narzędzia"


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
    assert "| Narzędzie | Kategoria | Wynik skanu | Wyników | Wersja | Metadane reguł | Publikacja |" in text
    digest = manifest["reports"][0]["sarif_rules_metadata_digest"][:12]
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


def test_sarif_rules_metadata_digest_jest_stabilny_i_zalezy_od_regul(tmp_path):
    rules_a = [{"id": "r", "help": {"text": "x", "uri": "u"}}]
    rules_b = [{"help": {"uri": "u", "text": "x"}, "id": "r"}]
    rules_c = [{"id": "inna"}]

    def digest(name, rules):
        sca = tmp_path / name / "sca"
        out = tmp_path / name / "out"
        write_exit(sca, "semgrep", "0\n")
        write_report(sca, "semgrep", make_doc(results=[], rules=rules))
        return sr.prepare(sca, out, summary_env(tmp_path / name))["reports"][0]["sarif_rules_metadata_digest"]

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


# --- walidacja elementów i oba narzędzia naraz (#257) ---


@pytest.mark.parametrize(
    ("doc", "match"),
    [
        (make_doc(results=[None]), "wynik nie jest obiektem"),
        (make_doc(results=["tekst"]), "wynik nie jest obiektem"),
        (make_doc(rules=["reguła"]), "reguła nie jest obiektem"),
    ],
)
def test_load_report_odrzuca_nieobiekty(tmp_path, doc, match):
    with pytest.raises(sr.ReportError, match=match):
        sr.load_report(write_json(tmp_path / "semgrep.sarif", doc), "semgrep")


def test_prepare_oba_narzedzia_checkov_clean_i_findings(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(results=[]))
    write_exit(sca, "checkov", "1\n")
    write_report(sca, "checkov", make_doc("checkov", results=[make_result()], version="3.4.0"))
    env = summary_env(tmp_path)
    manifest = sr.prepare(sca, out, env)
    semgrep, checkov = manifest["reports"]
    assert (semgrep["outcome"], checkov["outcome"]) == ("clean", "findings")
    assert semgrep["publish"] and checkov["publish"]
    assert checkov["category"] == "checkov"
    assert checkov["driver_version"] == "3.4.0"
    assert (out / "semgrep.sarif").is_file() and (out / "checkov.sarif").is_file()
    published = json.loads((out / "checkov.sarif").read_text(encoding="utf-8"))
    assert published["runs"][0]["tool"]["driver"]["name"] == "Checkov"
    assert CANARY not in json.dumps(published)

    write_exit(sca, "checkov", "0\n")
    write_report(sca, "checkov", make_doc("checkov", results=[]))
    assert sr.prepare(sca, out, env)["reports"][1]["outcome"] == "clean"


def test_prepare_nieoczekiwany_blad_nie_zostawia_pliku(tmp_path, monkeypatch):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    out.mkdir()
    write_report(sca, "semgrep", make_doc(results=[]))

    def boom(*args, **kwargs):
        raise TypeError("nieoczekiwany kształt")

    monkeypatch.setattr(sr, "_report_info", boom)
    with pytest.raises(TypeError):
        sr._prepare_report(sr.REPORTS["semgrep"], sca / "semgrep.sarif", out / "semgrep.sarif")
    assert not (out / "semgrep.sarif").exists()


# --- allowlist i ochrona eksportu (#257) ---


def test_rule_text_fallback_i_obcinanie():
    rule_full = {
        "shortDescription": {"text": "   "},
        "fullDescription": {"text": "opis z full"},
        "name": "nazwa",
    }
    assert sr._rule_text(rule_full, "r.id") == "opis z full"

    rule_name = {
        "shortDescription": {"text": ""},
        "fullDescription": {"text": "   "},
        "name": "tylko nazwa",
    }
    assert sr._rule_text(rule_name, "r.id") == "tylko nazwa"

    rule_id_fallback = {
        "shortDescription": {"text": ""},
        "name": "   ",
    }
    assert sr._rule_text(rule_id_fallback, "r.id") == "r.id"
    assert sr._rule_text(None, "r.id") == "r.id"

    long_text = "a" * 600
    rule_long = {"shortDescription": {"text": long_text}}
    assert len(sr._rule_text(rule_long, "r.id")) == 500


def test_export_rule_galezie_i_wlasciwosci():
    rule = {
        "id": "r1",
        "help": {"markdown": "**tylko md**"},
        "defaultConfiguration": {"level": "nieznany"},
        "properties": {
            "tags": "nie-lista",
            "precision": 123,
            "security-severity": 7.5,
            "problem.severity": None,
        },
    }
    exported = sr._export_rule(rule)
    assert exported["help"] == {"markdown": "**tylko md**"}
    assert "defaultConfiguration" not in exported
    assert exported["properties"] == {"security-severity": "7.5"}

    empty_props_rule = {"id": "r2", "help": {}, "properties": {"tags": []}}
    exported_empty = sr._export_rule(empty_props_rule)
    assert "help" not in exported_empty
    assert "properties" not in exported_empty


def test_export_location_i_result_galezie():
    bad_phys = {"physicalLocation": "nie-obiekt"}
    assert sr._export_location(bad_phys) is None

    only_start_line = {
        "physicalLocation": {
            "artifactLocation": {"uri": "main.py"},
            "region": {"startLine": 10},
        }
    }
    exported_loc = sr._export_location(only_start_line)
    assert exported_loc["physicalLocation"]["region"] == {"startLine": 10}

    rules_list = [{"id": "r1", "name": "reguła 1"}]
    result_by_index = {
        "ruleId": "nieznana.id",
        "ruleIndex": 0,
        "locations": [only_start_line],
        "level": "nieznany",
        "partialFingerprints": {"zły_klucz": 123},
    }
    exported_res = sr._export_result(result_by_index, {}, rules_list)
    assert exported_res["message"]["text"] == "reguła 1"
    assert "level" not in exported_res
    assert "partialFingerprints" not in exported_res


def test_export_sarif_struktury_wejsciowe():
    doc = {
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Tool",
                        "rules": ["nie-obiekt", {"bez": "id"}, {"id": "r1"}],
                    }
                },
                "automationDetails": {"id": 123},
                "invocations": [{"toolExecutionNotifications": []}],
            }
        ]
    }
    exported = sr.export_sarif(doc)
    run = exported["runs"][0]
    assert len(run["tool"]["driver"]["rules"]) == 1
    assert "automationDetails" not in run
    assert run["results"] == []
    assert "invocations" not in run


def test_canary_wszystkie_wektory_wycieku(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    output_file = tmp_path / "github_output"
    summary_file = tmp_path / "summary.md"
    write_exit(sca, "semgrep", "1\n")

    rules = [
        {
            "id": "leak.rule",
            "name": "Bezpieczna reguła",
            "shortDescription": {"text": "Bezpieczny opis reguły"},
            "help": {"text": "Bezpieczna pomoc"},
        }
    ]
    leaky_doc = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "Semgrep OSS", "version": "1.0", "rules": rules}},
                "automationDetails": {"id": "run-id"},
                "artifacts": [{"contents": {"text": CANARY}, "location": {"uri": "leak.py"}}],
                "properties": {"canary": CANARY},
                "originalUriBaseIds": {"%SRCROOT%": {"uri": f"file:///{CANARY}"}},
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "toolExecutionNotifications": [
                            {
                                "descriptor": {"id": "Syntax error"},
                                "level": "warning",
                                "message": {"text": f"{CANARY}\nline 2", "markdown": f"**{CANARY}**"},
                            }
                        ],
                    }
                ],
                "results": [
                    {
                        "ruleId": "leak.rule",
                        "level": "error",
                        "message": {
                            "text": f"wyciek: {CANARY}",
                            "markdown": f"**{CANARY}**",
                            "arguments": [CANARY],
                        },
                        "fingerprints": {"matchBasedId/v1": CANARY},
                        "partialFingerprints": {"lineHash": "clean_hash"},
                        "properties": {"detail": CANARY},
                        "suppressions": [{"kind": "weird", "justification": CANARY}],
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "src/leak.py", "uriBaseId": "%SRCROOT%"},
                                    "region": {
                                        "startLine": 42,
                                        "startColumn": 1,
                                        "snippet": {"text": f"token = '{CANARY}'"},
                                    },
                                    "contextRegion": {"snippet": {"text": CANARY}},
                                }
                            }
                        ],
                        "relatedLocations": [{"message": {"text": CANARY}, "physicalLocation": physical(CANARY)}],
                        "codeFlows": [{"threadFlows": [{"locations": [{"location": {"message": {"text": CANARY}}}]}]}],
                        "stacks": [{"frames": [{"location": physical(CANARY)}]}],
                        "fixes": [{"description": {"text": CANARY}}],
                        "graphs": [{"description": {"text": CANARY}}],
                        "attachments": [{"description": {"text": CANARY}}],
                    }
                ],
            }
        ],
    }
    write_report(sca, "semgrep", leaky_doc)

    env = {
        "GITHUB_OUTPUT": str(output_file),
        "GITHUB_STEP_SUMMARY": str(summary_file),
    }
    manifest = sr.prepare(sca, out, env)

    entry = manifest["reports"][0]
    assert entry["outcome"] == "findings"
    assert entry["publish"] is True
    assert entry["result_count"] == 1

    published_bytes = (out / "semgrep.sarif").read_bytes()
    published_text = published_bytes.decode("utf-8")
    manifest_text = (out / "manifest.json").read_text(encoding="utf-8")
    summary_text = summary_file.read_text(encoding="utf-8")
    output_text = output_file.read_text(encoding="utf-8")

    assert CANARY not in published_text
    assert CANARY not in manifest_text
    assert CANARY not in summary_text
    assert CANARY not in output_text

    published_doc = json.loads(published_text)
    published_result = published_doc["runs"][0]["results"][0]
    assert published_result["message"] == {"text": "Bezpieczny opis reguły"}
    assert published_result["partialFingerprints"] == {"lineHash": "clean_hash"}
    assert "fingerprints" not in published_result
    assert "snippet" not in published_result["locations"][0]["physicalLocation"]["region"]
    assert "contextRegion" not in published_result["locations"][0]["physicalLocation"]
    assert "artifacts" not in published_doc["runs"][0]
    assert "originalUriBaseIds" not in published_doc["runs"][0]


def test_export_sarif_wymogi_githuba_i_opis_reguly():
    rules = [
        {
            "id": "SEC001",
            "name": "SecRule",
            "shortDescription": {"text": "Krótki opis"},
            "fullDescription": {"text": "Długi opis"},
            "help": {"text": "Pomoc", "markdown": "**Pomoc**"},
            "helpUri": "https://rules.example.com/sec001",
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["security", "owasp-a1"],
                "precision": "high",
                "security-severity": "9.5",
                "problem.severity": "error",
            },
        }
    ]
    doc = make_doc(
        results=[
            {
                "ruleId": "SEC001",
                "ruleIndex": 0,
                "level": "error",
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": "app.py", "uriBaseId": "%SRCROOT%"},
                            "region": {
                                "startLine": 10,
                                "startColumn": 4,
                                "endLine": 10,
                                "endColumn": 20,
                            },
                        }
                    }
                ],
                "partialFingerprints": {"primaryLocationLineHash": "hash_xyz"},
            }
        ],
        rules=rules,
    )
    exported = sr.export_sarif(doc)
    run = exported["runs"][0]
    res = run["results"][0]

    assert res["ruleId"] == "SEC001"
    assert res["level"] == "error"
    assert res["message"] == {"text": "Krótki opis"}
    assert res["partialFingerprints"] == {"primaryLocationLineHash": "hash_xyz"}

    loc = res["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"] == {"uri": "app.py", "uriBaseId": "%SRCROOT%"}
    assert loc["region"] == {"startLine": 10, "startColumn": 4, "endLine": 10, "endColumn": 20}

    r = run["tool"]["driver"]["rules"][0]
    assert r["id"] == "SEC001"
    assert r["name"] == "SecRule"
    assert r["shortDescription"] == {"text": "Krótki opis"}
    assert r["fullDescription"] == {"text": "Długi opis"}
    assert r["help"] == {"text": "Pomoc", "markdown": "**Pomoc**"}
    assert r["helpUri"] == "https://rules.example.com/sec001"
    assert r["defaultConfiguration"] == {"level": "error"}
    assert r["properties"]["tags"] == ["security", "owasp-a1"]
    assert r["properties"]["precision"] == "high"
    assert r["properties"]["security-severity"] == "9.5"
    assert r["properties"]["problem.severity"] == "error"


def test_hermetyczny_fixture_semgrep_i_checkov(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"

    # Semgrep fixture (jak realny wynik z repo)
    write_exit(sca, "semgrep", "1\n")
    semgrep_doc = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Semgrep OSS",
                        "semanticVersion": "1.178.0",
                        "rules": [
                            {
                                "id": "generic.secrets.security.detected-aws-access-key-id-value",
                                "name": "AWS Access Key ID Value detected",
                                "shortDescription": {"text": "Semgrep Finding: AWS Access Key ID Value"},
                                "fullDescription": {"text": "AWS Access Key ID Value detected in source code."},
                                "help": {"text": "Do not hardcode secrets."},
                                "helpUri": "https://semgrep.dev/r/generic.secrets",
                                "defaultConfiguration": {"level": "error"},
                                "properties": {"precision": "very-high", "tags": ["CWE-798", "security"]},
                            }
                        ],
                    }
                },
                "results": [
                    {
                        "ruleId": "generic.secrets.security.detected-aws-access-key-id-value",
                        "fingerprints": {"matchBasedId/v1": "requires login"},
                        "properties": {},
                        "message": {"text": "Hardcoded secret: secret_value"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "leak.py", "uriBaseId": "%SRCROOT%"},
                                    "region": {
                                        "startLine": 2,
                                        "startColumn": 15,
                                        "endLine": 2,
                                        "endColumn": 35,
                                        "snippet": {"text": 'aws_secret = "secret_value"'},
                                    },
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }
    write_report(sca, "semgrep", semgrep_doc)

    # Checkov fixture (jak realny wynik z repo)
    write_exit(sca, "checkov", "1\n")
    checkov_doc = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Checkov",
                        "version": "3.3.19",
                        "informationUri": "https://checkov.io",
                        "rules": [],
                    }
                },
                "results": [
                    {
                        "ruleId": "CKV_AWS_20",
                        "level": "error",
                        "message": {"text": "Ensure S3 bucket policy is secure"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "s3.tf"},
                                    "region": {"startLine": 1, "endLine": 5},
                                }
                            }
                        ],
                        "partialFingerprints": {"primaryLocationLineHash": "hash123"},
                    }
                ],
            }
        ],
    }
    write_report(sca, "checkov", checkov_doc)

    manifest = sr.prepare(sca, out, summary_env(tmp_path))
    assert [r["outcome"] for r in manifest["reports"]] == ["findings", "findings"]
    assert all(r["publish"] for r in manifest["reports"])

    pub_semgrep = json.loads((out / "semgrep.sarif").read_text(encoding="utf-8"))
    sem_res = pub_semgrep["runs"][0]["results"][0]
    assert sem_res["message"]["text"] == "Semgrep Finding: AWS Access Key ID Value"
    assert "fingerprints" not in sem_res
    assert "snippet" not in sem_res["locations"][0]["physicalLocation"]["region"]

    pub_checkov = json.loads((out / "checkov.sarif").read_text(encoding="utf-8"))
    chk_res = pub_checkov["runs"][0]["results"][0]
    assert chk_res["ruleId"] == "CKV_AWS_20"
    assert chk_res["message"]["text"] == "CKV_AWS_20"  # fallback do ruleId przy pustych rules
    assert chk_res["partialFingerprints"] == {"primaryLocationLineHash": "hash123"}


# --- limity zasobów, dokładne nazwy driverów i weryfikacja sha256 (#257) ---


@pytest.mark.parametrize(
    "driver_name",
    [
        "semgrep",
        "SEMGREP OSS",
        "semgrep-fork",
        "Semgrep-Pro",
        "checkov",
        "Checkov2",
    ],
)
def test_load_report_odrzuca_niezgodne_nazwy_drivera(tmp_path, driver_name):
    doc = make_doc(tool="semgrep", driver_name=driver_name)
    path = write_json(tmp_path / "driver.sarif", doc)
    with pytest.raises(sr.ReportError, match="nie pochodzi z narzędzia"):
        sr.load_report(path, "semgrep")


def test_load_report_przyjmuje_dokladne_nazwy_driverow(tmp_path):
    sem1 = write_json(tmp_path / "sem1.sarif", make_doc(tool="semgrep", driver_name="Semgrep OSS"))
    assert sr.load_report(sem1, "semgrep")["runs"]
    sem2 = write_json(tmp_path / "sem2.sarif", make_doc(tool="semgrep", driver_name="Semgrep"))
    assert sr.load_report(sem2, "semgrep")["runs"]
    chk = write_json(tmp_path / "chk.sarif", make_doc(tool="checkov", driver_name="Checkov"))
    assert sr.load_report(chk, "checkov")["runs"]


def test_check_json_depth_galezie():
    assert sr._check_json_depth('{"str": "quote \\" and backslash \\\\"}', 64) is True
    assert sr._check_json_depth("[" * 64 + "]" * 64, 64) is True
    assert sr._check_json_depth("[" * 65 + "]" * 65, 64) is False


def test_prepare_zagniezdzenie_100k_zglasza_error_i_nie_ujawnia_tresci(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    # Zagnieżdżenie 100 000 nawiasów z tokenem CANARY w środku
    payload = (
        f'{{"version": "2.1.0", "runs": [{{"tool": {{"driver": {{"name": "Semgrep"}}}}, "extra": {CANARY!r}, "nested": '
        + ("[" * 100_000)
        + ("0" * 1)
        + ("]" * 100_000)
        + "}]}"
    )
    (sca / "semgrep.sarif").write_text(payload, encoding="utf-8")
    env = summary_env(tmp_path)
    manifest = sr.prepare(sca, out, env)
    entry = manifest["reports"][0]
    assert entry["outcome"] == "error"
    assert entry["publish"] is False
    assert "limit zagnieżdżenia" in entry["reason"]
    assert CANARY not in entry["reason"]
    assert CANARY not in json.dumps(manifest, ensure_ascii=False)
    assert CANARY not in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert not (out / "semgrep.sarif").exists()


def test_prepare_normalna_glebokosc_semgrepa_przechodzi(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(tool="semgrep", driver_name="Semgrep OSS"))
    manifest = sr.prepare(sca, out, summary_env(tmp_path))
    assert manifest["reports"][0]["outcome"] == "clean"
    assert (out / "semgrep.sarif").is_file()


def test_load_report_obsluga_recursion_i_memory_error(tmp_path, monkeypatch):
    path = write_report(tmp_path, "semgrep")

    def raise_recursion(*args, **kwargs):
        raise RecursionError("stos")

    monkeypatch.setattr(sr.json, "loads", raise_recursion)
    with pytest.raises(sr.ReportError, match="limit zagnieżdżenia") as exc:
        sr.load_report(path, "semgrep")
    assert "stos" not in str(exc.value)

    def raise_memory(*args, **kwargs):
        raise MemoryError("brak ram")

    monkeypatch.setattr(sr.json, "loads", raise_memory)
    with pytest.raises(sr.ReportError, match="limit pamięci") as exc:
        sr.load_report(path, "semgrep")
    assert "brak ram" not in str(exc.value)


def test_manifest_sha256_jest_dokladnym_hashem_pliku_na_dysku(tmp_path):
    sca = tmp_path / "sca"
    out = tmp_path / "out"
    write_exit(sca, "semgrep", "0\n")
    write_report(sca, "semgrep", make_doc(tool="semgrep", driver_name="Semgrep OSS"))
    write_exit(sca, "checkov", "0\n")
    write_report(sca, "checkov", make_doc(tool="checkov", driver_name="Checkov"))
    manifest = sr.prepare(sca, out, summary_env(tmp_path))
    for rep in manifest["reports"]:
        if rep["publish"]:
            file_path = out / sr.REPORTS[rep["tool"]].sarif
            assert file_path.is_file()
            expected_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            assert rep["sha256"] == expected_hash
