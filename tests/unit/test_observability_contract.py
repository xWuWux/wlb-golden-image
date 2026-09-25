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

GOOD = [
    f"<85>1 2026-09-25T12:00:00Z lab-test01 wlb-sluza-out - - - export_request user=jupyter-tester1 uid=10000 "
    f"entry=wynik.csv sha256={SHA} queued_as=20260925T120000Z_jupyter-tester1_wynik.csv",
    '<13>1 2026-09-25T12:00:00Z lab-test01 wlb-firstboot 12 - [timeQuality isSynced="1"] '
    "Laboratorium lab-test01 skonfigurowane",
    "<30>1 2026-09-25T12:00:00Z lab-test01 python3 99 - - [I 2026 JupyterHub base:931] User logged in: tester1",
    "<4>Sep 25 12:00:00 lab-test01 kernel: [ 12.3] wlb-egress-deny IN= OUT=eth0 DST=93.184.216.34",
    *[
        f'<14>1 2026-09-25T12:00:00Z lab-test01 audisp-syslog - - - type=SYSCALL msg=audit(1:2): success=no key="{k}"'
        for k in ("wlb_sluza_in", "wlb_sluza_out", "wlb_export_queue", "wlb_exec", "wlb_access_denied")
    ],
    "śmieci, które nie są syslogiem",
]


def test_log_ze_wszystkimi_zdarzeniami():
    rows, failures = oc.verify_log(oc.load_contract(REPO_ROOT), GOOD)
    assert failures == 0
    assert all(status == "OK" for _, status, _ in rows)


def test_niepoprawne_wartosci_i_brakujace_zdarzenia():
    bad = [line.replace(SHA, "abc") for line in GOOD if "wlb_exec" not in line and "User logged in" not in line]
    rows = {name: (status, detail) for name, status, detail in oc.verify_log(oc.load_contract(REPO_ROOT), bad)[0]}
    assert rows["sluza_out.export_request"] == ("BRAK", "niepoprawne wartości: sha256='abc'")
    assert rows["hub.login"] == ("BRAK", "nie dotarło do SIEM")
    assert rows["audit:wlb_exec"][0] == "BRAK"


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
