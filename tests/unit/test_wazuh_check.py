"""Walidator wyniku wazuh-logtest względem kontraktu obserwowalności (#17) — bez dockera."""

import json

import pytest

import observability_contract as oc
import wazuh_check as wc

# --- walidator wyników logtest (#17) ---

ROOT = '[wlb@32473 input="imuxsock" uid="0" gid="0" pid="99"]'
R1 = '[wlb@32473 input="imuxsock" uid="10000" gid="10001" pid="4242"]'
SHA = "a" * 64
EXPORT = (
    f"<85>1 2026-10-30T10:00:00Z lab-test01 wlb-sluza-out - - {ROOT}  export_request user=jupyter-u01 "
    f"uid=10000 entry=wynik.csv sha256={SHA} queued_as=20261030T090000Z_jupyter-u01_wynik.csv"
)
EXPORT_FIELDS = {"user": "jupyter-u01", "uid": "10000", "entry": "wynik.csv", "sha256": SHA, "queued_as": "x"}
DONE = f"<13>1 2026-10-30T10:00:00Z lab-test01 wlb-firstboot - - {ROOT}  Laboratorium lab-test01 skonfigurowane"
AUDIT = (
    f"<14>1 2026-10-30T10:00:00Z lab-test01 audisp-syslog - - {ROOT}  type=SYSCALL msg=audit(1:2): "
    'success=no key="wlb_access_denied"'
)


def result(line, groups=(), fields=None, rule_id="100100", decoder="wlb"):
    out = {"decoder": {"name": decoder}, "rule": {"id": rule_id, "groups": ["wlb", *groups]}}
    out["data"] = {"wlb": fields or {}}
    return {"line": line, "output": out}


@pytest.fixture
def contract():
    return oc.load_contract(oc.REPO_ROOT)


def run(contract, results):
    tally, ours, decoded = wc.check(contract, results)
    return tally, ours, decoded


def test_zdarzenie_z_grupa_i_polami(contract):
    tally, ours, decoded = run(contract, [result(EXPORT, ["wlb_ev_sluza_out.export_request"], EXPORT_FIELDS)])
    assert tally.ok["sluza_out.export_request"] == 1
    assert not tally.errors
    assert (ours, decoded) == (1, 1)


def test_zdarzenie_bez_grupy(contract):
    tally, *_ = run(contract, [result(EXPORT, [], EXPORT_FIELDS)])
    assert "brak grupy wlb_ev_sluza_out.export_request" in tally.errors["sluza_out.export_request"][0]


def test_zdarzenie_bez_nazwanego_pola(contract):
    fields = {k: v for k, v in EXPORT_FIELDS.items() if k != "sha256"}
    tally, *_ = run(contract, [result(EXPORT, ["wlb_ev_sluza_out.export_request"], fields)])
    assert "brak pól wlb.sha256" in tally.errors["sluza_out.export_request"][0]


def test_podrobiony_wpis_musi_trafic_w_regule_podszycia(contract):
    forged = EXPORT.replace(ROOT, R1)
    tally, *_ = run(contract, [result(forged, ["wlb_spoof"], EXPORT_FIELDS)])
    assert tally.untrusted["sluza_out.export_request"] == 1
    assert not tally.errors
    tally, *_ = run(contract, [result(forged, ["wlb_ev_sluza_out.export_request"], EXPORT_FIELDS)])
    assert "nie trafił w regułę podszycia" in tally.errors["sluza_out.export_request"][0]


def test_wiersz_wielu_zdarzen_wystarczy_jedna_grupa(contract):
    """firstboot.done to też firstboot.message (wzorzec .+) — reguła szczegółowa jest poprawna."""
    tally, *_ = run(contract, [result(DONE, ["wlb_ev_firstboot.done"], {"lab": "lab-test01"})])
    assert tally.ok["firstboot.done"] == 1
    assert "firstboot.message" not in tally.ok
    assert not tally.errors


def test_audyt_klucz_w_polu(contract):
    tally, *_ = run(contract, [result(AUDIT, ["wlb_audit"], {"audit_key": "wlb_access_denied"})])
    assert tally.ok["audit:wlb_access_denied"] == 1
    tally, *_ = run(contract, [result(AUDIT, ["wlb_audit"], {})])
    assert "audit:wlb_access_denied" in tally.errors
    tally, *_ = run(contract, [result(AUDIT.replace(ROOT, R1), [], {})])
    assert not tally.errors and not tally.ok  # audyt od niezaufanego nadawcy nie jest liczony


def test_niepoprawne_wartosci_nie_wymagaja_reguly(contract):
    bad = EXPORT.replace(SHA, "abc")
    tally, *_ = run(contract, [result(bad)])
    assert not tally.errors and not tally.ok


def test_wiersze_obce_sa_pomijane(contract):
    _, ours, _ = run(contract, [result("śmieci"), result("<13>1 t h app - - - bez pól zaufanych")])
    assert ours == 0


def test_raport_wymagane_brakujace_i_dekoder(contract):
    tally, ours, decoded = run(contract, [result(EXPORT, decoder="inny")])
    rows, failures = wc.report(contract, tally, ours, decoded, require_all=False, untrusted=())
    table = {name: status for name, status, _ in rows}
    assert table["hub.login"] == "BRAK"  # acceptance: true
    assert "shell.command" not in table  # acceptance: false i --require-all wyłączone
    assert table["dekoder wlb"] == "BŁĄD"
    assert failures >= 2
    rows, _ = wc.report(contract, tally, ours, decoded, require_all=True, untrusted=("shell.command",))
    table = {name: status for name, status, _ in rows}
    assert table["shell.command"] == "BRAK"
    assert table["shell.command (podrobione)"] == "BRAK"


def test_raport_podrobione_ok(contract):
    tally, ours, decoded = run(contract, [result(EXPORT.replace(ROOT, R1), ["wlb_spoof"])])
    rows, _ = wc.report(contract, tally, ours, decoded, False, ("sluza_out.export_request",))
    assert ("sluza_out.export_request (podrobione)", "OK", "1 w regule podszycia") in rows


def test_main(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    path = tmp_path / "wynik.jsonl"
    path.write_text(json.dumps(result(EXPORT, ["wlb_ev_sluza_out.export_request"], EXPORT_FIELDS)) + "\n\n")
    assert wc.main([str(path)]) == 1  # brakuje pozostałych zdarzeń z acceptance: true
    out = capsys.readouterr().out
    assert "| sluza_out.export_request | OK |" in out
    assert "| hub.login | BRAK |" in out
