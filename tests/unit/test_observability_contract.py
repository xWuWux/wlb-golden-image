"""Kontrakt obserwowalności: zgodność z kodem (statycznie) i weryfikacja logu z SIEM (dynamicznie)."""

import shutil
from pathlib import Path

import pytest
import yaml

import observability_contract as oc

REPO_ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 64


@pytest.fixture
def repo(tmp_path):
    """Kopia obrazu (ansible/) i kontraktu, którą testy mogą psuć."""
    shutil.copytree(REPO_ROOT / "ansible", tmp_path / "ansible")
    shutil.copytree(REPO_ROOT / "observability", tmp_path / "observability")
    return tmp_path


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def contract(repo: Path) -> dict:
    return oc.load_contract(repo)


def save(repo: Path, data: dict) -> None:
    (repo / "observability/contract.yml").write_text(yaml.safe_dump(data, allow_unicode=True))


def test_repozytorium_jest_zgodne_z_kontraktem():
    assert oc.check_static(REPO_ROOT, oc.load_contract(REPO_ROOT)) == []


def test_kod_przestal_emitowac_pole(repo):
    edit(repo / "ansible/roles/storage/files/wlb-sluza-out-mover", " sha256=$sha", "")
    errors = oc.check_static(repo, contract(repo))
    assert any("sluza_out.export_request: kod nie emituje pól sha256" in e for e in errors)


def test_kod_emituje_pole_spoza_kontraktu(repo):
    edit(
        repo / "ansible/roles/storage/files/wlb-sluza-out-mover",
        "reason=unsupported_type",
        "reason=unsupported_type size=1",
    )
    errors = oc.check_static(repo, contract(repo))
    assert any("sluza_out.rejected: kod emituje pola spoza kontraktu: size" in e for e in errors)


def test_nowe_zrodlo_logow_bez_opisu(repo):
    (repo / "ansible/roles/base/files").mkdir(parents=True, exist_ok=True)
    (repo / "ansible/roles/base/files/nowy").write_text('logger -t wlb-nowy -- "cos"\n')
    errors = oc.check_static(repo, contract(repo))
    assert any("tag syslog 'wlb-nowy'" in e for e in errors)


def test_klucze_audytu_w_obie_strony(repo):
    rules = repo / "ansible/roles/audit/templates/50-wlb.rules.j2"
    rules.write_text(rules.read_text().replace("-k wlb_docs_write", "-k wlb_docs_nowy"))
    errors = oc.check_static(repo, contract(repo))
    assert any("klucz audytu wlb_docs_nowy (reguły) nie jest opisany" in e for e in errors)
    assert any("klucz audytu wlb_docs_write z kontraktu nie występuje" in e for e in errors)


def test_prefiksy_logow_zapory_w_obie_strony(repo):
    edit(repo / "ansible/roles/lab_config/files/wlb-firstboot", 'log prefix "wlb-in-deny "', 'log prefix "wlb-inne "')
    errors = oc.check_static(repo, contract(repo))
    assert any("prefiks logu zapory 'wlb-inne '" in e for e in errors)
    assert any("prefiks logu zapory 'wlb-in-deny ' z kontraktu nie występuje" in e for e in errors)


def test_brak_przekazywania_wszystkich_zdarzen_do_siem(repo):
    edit(repo / "ansible/roles/lab_config/files/wlb-firstboot", '*.* action(type="omfwd"', 'auth.* action(type="omfwd"')
    assert any(e.startswith("SIEM:") for e in oc.check_static(repo, contract(repo)))


def test_bledy_samego_kontraktu(repo):
    data = contract(repo)
    ev = data["events"]
    ev.append(dict(ev[0]))  # duplikat nazwy
    ev.append({"name": "ZlaNazwa", "source": {"tag": "ZLY_TAG"}, "format": "kv", "fields": {"Zle-Pole": ".+"}})
    ev.append({"name": "x.brak_formatu", "source": {}, "format": "json", "acceptance": False})
    ev.append({"name": "x.kv_bez_pol", "source": {}, "format": "kv", "acceptance": False})
    ev.append({"name": "x.text_bez_wzorca", "source": {}, "format": "text", "acceptance": False})
    ev.append({"name": "x.brak_pliku", "source": {"file": "nie/ma.sh"}, "format": "kernel", "acceptance": False})
    ev.append(
        {
            "name": "x.brak_markera",
            "source": {
                "tag": "wlb-firstboot",
                "marker": "nie ma takiego",
                "file": "ansible/roles/lab_config/files/wlb-firstboot",
            },
            "format": "text",
            "pattern": ".",
            "acceptance": False,
        }
    )
    ev.append(
        {
            "name": "x.brak_emisji",
            "source": {
                "tag": "wlb-firstboot",
                "marker": "nie_ma",
                "file": "ansible/roles/lab_config/files/wlb-firstboot",
            },
            "format": "kv",
            "fields": {"a": "."},
            "acceptance": False,
        }
    )
    ev.append(
        {
            "name": "x.zly_tag_w_pliku",
            "source": {"tag": "wlb-inny", "file": "ansible/roles/lab_config/files/wlb-firstboot"},
            "format": "text",
            "pattern": ".",
            "acceptance": False,
        }
    )
    data["audit"]["keys"].append({"key": "ZLY_KLUCZ", "acceptance": False})
    save(repo, data)
    text = "\n".join(oc.check_static(repo, contract(repo)))
    for expected in [
        "zduplikowana nazwa",
        "ZlaNazwa: nazwa niezgodna",
        "ZlaNazwa: brak pola acceptance",
        "pole 'Zle-Pole' niezgodne",
        "tag 'ZLY_TAG' niezgodny",
        "nieznany format 'json'",
        "format kv wymaga listy pól",
        "format text wymaga wzorca",
        "plik nie/ma.sh nie istnieje",
        "brak komunikatu z 'nie ma takiego'",
        "nie znaleziono miejsca emisji",
        "nie loguje z tagiem wlb-inny",
        "klucz audytu ZLY_KLUCZ niezgodny z konwencją",
    ]:
        assert expected in text, expected


# --- log z SIEM -------------------------------------------------------------------------------

ROOT = '[wlb@32473 input="imuxsock" uid="0" gid="0" pid="99"]'
KERNEL = '[wlb@32473 input="imklog" uid="" gid="" pid=""]'
R1 = '[wlb@32473 input="imuxsock" uid="10000" gid="10000" pid="4242"]'  # proces badacza
FORGED_EXPORT = (
    "export_request user=jupyter-tester2 uid=0 entry=podrobiony.csv "
    f"sha256={SHA} queued_as=20260101T000000Z_jupyter-tester2_podrobiony.csv"
)

GOOD = [
    f"<85>1 2026-09-25T12:00:00Z lab-test01 wlb-sluza-out - - {ROOT}  export_request user=jupyter-tester1 "
    f"uid=10000 entry=wynik.csv sha256={SHA} queued_as=20260925T120000Z_jupyter-tester1_wynik.csv",
    f"<85>1 2026-09-25T12:00:00Z lab-test01 wlb-sluza-out - - {ROOT}  rejected user=jupyter-tester1 "
    "entry=link-test reason=unsupported_type",
    f"<13>1 2026-09-25T12:00:00Z lab-test01 wlb-firstboot 12 - {ROOT}  Laboratorium lab-test01 skonfigurowane",
    f"<30>1 2026-09-25T12:00:00Z lab-test01 python3 99 - {ROOT}  [I 2026 JupyterHub base:931] User logged in: tester1",
    f"<14>1 2026-09-25T12:00:00Z lab-test01 traefik 77 - {ROOT}  "
    '{"ClientHost":"127.0.0.1","DownstreamStatus":403,"RequestPath":"/user/tester1/files/dane.csv",'
    '"RouterName":"wlb-block-download@file","level":"info"}',
    f"<4>1 2026-09-25T12:00:00Z lab-test01 kernel - - {KERNEL}  [ 12.3] wlb-egress-deny IN= OUT=eth0 DST=93.184.216.34",
    *[
        f"<14>1 2026-09-25T12:00:00Z lab-test01 audisp-syslog - - {ROOT}  type=SYSCALL msg=audit(1:2): "
        f'success=no key="{k}"'
        for k in (
            "wlb_sluza_in",
            "wlb_sluza_out",
            "wlb_export_queue",
            "wlb_exec",
            "wlb_access_denied",
            "wlb_account_change",
            "wlb_mac_config",
        )
    ],
    "śmieci, które nie są syslogiem",
]


def rows_of(lines, *expect_untrusted):
    rows, failures = oc.verify_log(oc.load_contract(REPO_ROOT), lines, expect_untrusted)
    return {name: (status, detail) for name, status, detail in rows}, failures


def test_log_ze_wszystkimi_zdarzeniami():
    rows, failures = rows_of(GOOD)
    assert failures == 0
    assert all(status == "OK" for status, _ in rows.values())


def test_niepoprawne_wartosci_i_brakujace_zdarzenia():
    bad = [line.replace(SHA, "abc") for line in GOOD if "wlb_exec" not in line and "User logged in" not in line]
    rows, _ = rows_of(bad)
    assert rows["sluza_out.export_request"] == ("BRAK", "niepoprawne wartości: sha256='abc'")
    assert rows["hub.login"] == ("BRAK", "nie dotarło do SIEM")
    assert rows["audit:wlb_exec"][0] == "BRAK"


def test_zdarzenie_podrobione_przez_badacza_nie_jest_liczone():
    # badacz: logger -t wlb-sluza-out ... — tag i treść jak prawdziwe, ale uid nadawcy z jądra = 10000
    lines = [line for line in GOOD if "export_request" not in line and "User logged in" not in line] + [
        f"<85>1 2026-09-25T12:00:00Z lab-test01 wlb-sluza-out - - {R1}  {FORGED_EXPORT}",
        f"<14>1 2026-09-25T12:00:00Z lab-test01 python3 - - {R1}  User logged in: tester2",
    ]
    rows, failures = rows_of(lines)
    assert failures == 2
    assert rows["sluza_out.export_request"] == (
        "BRAK",
        "nie dotarło do SIEM; niezaufane (odrzucone): 1, np. uid='10000'",
    )
    assert rows["hub.login"][0] == "BRAK"


def test_podszycie_przez_pola_zaufane_w_tresci_nie_dziala():
    # pola wpisane przez nadawcę w treść stoją po spacji — nie są structured data z rsyslog
    line = f"<85>1 2026-09-25T12:00:00Z lab-test01 wlb-sluza-out - - {R1}  {ROOT} {FORGED_EXPORT}"
    rec = oc.parse_syslog([line])[0]
    assert rec["sd"]["wlb@32473"]["uid"] == "10000"
    assert rec["msg"].startswith("[wlb@32473")
    no_sd = f"<85>1 2026-09-25T12:00:00Z lab-test01 wlb-sluza-out - - - {ROOT} {FORGED_EXPORT}"
    assert oc.parse_syslog([no_sd])[0]["sd"] == {}
    rows, _ = rows_of([line, no_sd])
    assert rows["sluza_out.export_request"] == ("BRAK", "nie dotarło do SIEM")  # żaden nie liczy się jako zdarzenie


def test_test_podszycia_wymaga_rozpoznania_wpisu():
    rows, failures = rows_of(GOOD, "sluza_out.export_request")
    assert failures == 1
    assert rows["sluza_out.export_request (podrobione)"][0] == "BRAK"


def test_pochodzenie_zdarzen_regula_po_regule():
    ev = next(e for e in oc.load_contract(REPO_ROOT)["events"] if e["name"] == "shell.command")
    msg = "user=jupyter-tester1 uid=10000 session=1-2 cwd=/w cmd=ls"
    ok = oc.parse_syslog([f"<182>1 2026-09-25T12:00:00Z h wlb-shell - - {R1}  {msg}"])[0]
    assert oc.event_matches(ev, ok, "wlb@32473") == (True, "", "")
    other_uid = oc.parse_syslog(
        [f"<182>1 2026-09-25T12:00:00Z h wlb-shell - - {R1}  {msg.replace('uid=10000', 'uid=10001')}"]
    )[0]
    assert "uid=" in oc.event_matches(ev, other_uid, "wlb@32473")[2]  # uid w treści ≠ uid nadawcy
    as_root = oc.parse_syslog([f"<182>1 2026-09-25T12:00:00Z h wlb-shell - - {ROOT}  {msg}"])[0]
    assert oc.event_matches(ev, as_root, "wlb@32473")[2] == "uid='0'"
    kernel_rule = {"input": "imklog"}
    assert oc.untrusted_reason(kernel_rule, ok, {}, "wlb@32473") == "input='imuxsock'"
    assert oc.untrusted_reason(kernel_rule, {"sd": {}}, {}, "wlb@32473") == "brak pól zaufanych [wlb@32473]"


def test_parse_sd_z_wieloma_elementami_i_escapowaniem():
    sd = '[timeQuality isSynced="1"][wlb@32473 input="imuxsock" uid="0" note="a\\"b\\]c"]'
    assert oc.parse_sd(sd) == {
        "timeQuality": {"isSynced": "1"},
        "wlb@32473": {"input": "imuxsock", "uid": "0", "note": 'a"b]c'},
    }
    assert oc.parse_sd("-") == {}


def test_kontrakt_wymaga_regul_pochodzenia(repo):
    data = contract(repo)
    del data["events"][0]["trusted"]
    data["events"][1]["trusted"] = {"input": "imuxsock", "uid": "(", "uid_field": "nie_ma", "inne": 1}
    del data["audit"]["trusted"]
    save(repo, data)
    text = "\n".join(oc.check_static(repo, contract(repo)))
    for expected in [
        f"{data['events'][0]['name']}: brak reguły trusted",
        "nieznany klucz reguły trusted: inne",
        "trusted.uid: błędne wyrażenie",
        "trusted.uid_field: pola 'nie_ma' nie ma",
        "audyt: brak reguły trusted",
    ]:
        assert expected in text, expected


def test_siem_bez_tls(repo):
    edit(repo / "ansible/roles/lab_config/files/wlb-firstboot", 'StreamDriverAuthMode=\\"x509/name\\"', "")
    assert any("nie wymusza TLS z weryfikacją nazwy" in e for e in oc.check_static(repo, contract(repo)))


def test_siem_bez_pol_zaufanych(repo):
    edit(repo / "ansible/roles/lab_config/files/wlb-firstboot", 'uid=\\"%\\$!uid%\\"', "")
    tasks = repo / "ansible/roles/logging/tasks/main.yml"
    tasks.write_text(tasks.read_text().replace('SysSock.ParseTrusted="on"', ""))
    text = "\n".join(oc.check_static(repo, contract(repo)))
    assert "nie dopisuje pól zaufanych" in text
    assert "rsyslog bez pól zaufanych nadawcy" in text
    edit(repo / "ansible/roles/lab_config/files/wlb-firstboot", 'template="WLB_SyslogProtocol23Trusted"', "")
    assert any("nie przekazuje zdarzeń szablonem" in e for e in oc.check_static(repo, contract(repo)))


def test_parse_kv_wartosc_ze_spacjami():
    assert oc.parse_kv("user=jupyter-a session=1-2 cwd=/w cmd=cat /data-mart/a b.csv") == {
        "user": "jupyter-a",
        "session": "1-2",
        "cwd": "/w",
        "cmd": "cat /data-mart/a b.csv",
    }


def test_main(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert oc.main(["static"]) == 0
    assert "Wszystko zgodne z kodem" in capsys.readouterr().out
    log = tmp_path / "siem.log"
    log.write_text("\n".join(GOOD))
    assert oc.main(["verify-log", str(log)]) == 0
    log.write_text(GOOD[0])
    assert oc.main(["verify-log", str(log)]) == 1


def test_main_static_z_bledami(repo, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    edit(repo / "ansible/roles/storage/files/wlb-sluza-out-mover", " sha256=$sha", "")
    assert oc.main(["--repo-root", str(repo), "static"]) == 1
    assert "Niezgodności:" in capsys.readouterr().out
