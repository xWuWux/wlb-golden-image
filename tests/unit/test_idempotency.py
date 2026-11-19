"""Testy bramki idempotencji Ansible (#288): parsowanie PLAY RECAP i nazw zmienionych tasków."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("idempotency", ROOT / "ci" / "idempotency.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


idempotency = _load()

RECAP_OK = """\
PLAY RECAP *********************************************************************
wlb-test                  : ok=27   changed=0    unreachable=0    failed=0    skipped=12   rescued=0    ignored=0
"""


def test_changed_zero_is_ok():
    r = idempotency.parse(RECAP_OK)
    assert r["changed"] == 0 and r["failed"] == 0 and r["unreachable"] == 0
    assert r["changed_tasks"] == []


def test_changed_task_is_reported():
    text = """\
TASK [Odśwież cache apt (#288 — cache to nie stan systemu)] ********************
changed: [wlb-test] => {"changed": true}
TASK [Konfiguracja Javy dla R] *************************************************
ok: [wlb-test]
PLAY RECAP *********************************************************************
wlb-test                  : ok=27   changed=1    unreachable=0    failed=0    skipped=12   rescued=0    ignored=0
"""
    r = idempotency.parse(text)
    assert r["changed"] == 1
    assert r["changed_tasks"] == ["Odśwież cache apt (#288 — cache to nie stan systemu)"]


def test_multiple_hosts_are_summed():
    text = """\
PLAY RECAP *********************************************************************
a : ok=1 changed=1 unreachable=0 failed=0
b : ok=1 changed=2 unreachable=0 failed=1
"""
    r = idempotency.parse(text)
    assert r["changed"] == 3 and r["failed"] == 1


def test_missing_recap_returns_error(tmp_path):
    log = tmp_path / "log"
    log.write_text("TASK [x]\nok: [wlb-test]\n")
    assert idempotency.main(["idempotency.py", str(log)]) == 2


def test_clean_run_returns_zero(tmp_path):
    log = tmp_path / "log"
    log.write_text(RECAP_OK)
    assert idempotency.main(["idempotency.py", str(log)]) == 0


def test_changed_run_returns_one(tmp_path, capsys):
    log = tmp_path / "log"
    log.write_text(
        "TASK [Strefa czasowa]\nchanged: [wlb-test]\n"
        "PLAY RECAP *********************************************************************\n"
        "wlb-test : ok=1 changed=1 unreachable=0 failed=0\n"
    )
    assert idempotency.main(["idempotency.py", str(log)]) == 1
    out = capsys.readouterr().out
    assert "ZMIANA: Strefa czasowa" in out


@pytest.mark.parametrize("line", ["PLAY RECAP ***", "wlb-test : ok=1 changed=0"])
def test_incomplete_recap_is_not_parsed(line):
    assert idempotency.parse(line)["recaps"] == []
