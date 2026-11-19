"""wlb-hub-revoke na prawdziwej bazie JupyterHub (ta sama główna wersja co w TLJH 2.0, #18).

Sprawdzamy odwołanie tak, jak widzi je hub: ciasteczko huba wskazuje użytkownika przez
`users.cookie_id` (handlers/base.py: `User.cookie_id == cookie`), a token przez `APIToken.find`.
"""

import pytest
from conftest import REPO_ROOT, load_script
from jupyterhub import orm
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def tool():
    return load_script("wlb_hub_revoke", REPO_ROOT / "ansible/roles/tljh/files/wlb-hub-revoke")


@pytest.fixture
def hub(tmp_path, monkeypatch):
    """Baza huba z kontami u01 i u02: ciasteczko, token API, token usługi i kod OAuth na konto."""
    url = f"sqlite:///{tmp_path}/jupyterhub.sqlite"
    db = orm.new_session_factory(url)()
    service = orm.Service(name="cull-idle")
    db.add(service)
    db.add(orm.OAuthClient(identifier="jupyterhub", secret="s", redirect_uri="https://x/hub/oauth_callback"))
    client = orm.OAuthClient(identifier="jupyterhub-user-u01", secret="s", redirect_uri="https://x/cb")
    db.add(client)
    db.commit()
    state = {}
    for name in ("u01", "u02"):
        user = orm.User(name=name)
        db.add(user)
        db.commit()
        state[name] = {
            "cookie": user.cookie_id,
            "token": user.new_api_token(note="serwer"),
            "oauth": user.new_api_token(note="oauth", client_id=client.identifier),
        }
        db.add(orm.OAuthCode(client_id=client.identifier, code=f"kod-{name}", user_id=user.id, expires_at=0))
    state["service_token"] = service.new_api_token(note="usluga")
    db.commit()
    db.close()
    monkeypatch.setenv("WLB_HUB_DB_URL", url)
    return url, state


def cookie_valid(url, cookie):
    with Session(create_engine(url)) as db:
        return db.query(orm.User).filter(orm.User.cookie_id == cookie).first() is not None


def token_valid(url, token):
    with Session(create_engine(url)) as db:
        return orm.APIToken.find(db, token) is not None


def codes(url):
    with Session(create_engine(url)) as db:
        return sorted(c.code for c in db.query(orm.OAuthCode))


def test_przed_odwolaniem_poswiadczenia_dzialaja(hub):
    url, state = hub
    assert cookie_valid(url, state["u01"]["cookie"]) and token_valid(url, state["u01"]["token"])


def test_all_odwoluje_ciasteczka_tokeny_i_kody_wszystkich_kont(tool, hub, capsys):
    url, state = hub
    assert tool.main(["--all", "--no-hub-control"]) == 0
    for name in ("u01", "u02"):
        assert not cookie_valid(url, state[name]["cookie"])
        assert not token_valid(url, state[name]["token"])
        assert not token_valid(url, state[name]["oauth"])
    assert codes(url) == []
    assert token_valid(url, state["service_token"])  # usługi huba (culler) działają dalej
    out = capsys.readouterr().out
    assert "kont: 2, tokeny: 4, kody OAuth: 2" in out
    assert "u01" not in out  # bez loginów w dzienniku


def test_user_odwoluje_tylko_wskazane_konto(tool, hub):
    url, state = hub
    assert tool.main(["--user", "u02", "--no-hub-control"]) == 0
    assert not cookie_valid(url, state["u02"]["cookie"]) and not token_valid(url, state["u02"]["token"])
    assert cookie_valid(url, state["u01"]["cookie"]) and token_valid(url, state["u01"]["token"])
    assert codes(url) == ["kod-u01"]


def test_konta_zostaja_po_odwolaniu(tool, hub):
    url, _ = hub
    tool.main(["--all", "--no-hub-control"])
    with Session(create_engine(url)) as db:
        assert sorted(u.name for u in db.query(orm.User)) == ["u01", "u02"]


def test_baza_niezainicjalizowana_to_nic_do_odwolania(tool, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WLB_HUB_DB_URL", f"sqlite:///{tmp_path}/pusta.sqlite")
    assert tool.main(["--all", "--no-hub-control"]) == 0
    assert "kont: 0" in capsys.readouterr().out


def test_kolejnosc_stop_hub_serwery_odwolanie_start(tool, hub, tmp_path, monkeypatch):
    log = tmp_path / "systemctl.log"
    stub = tmp_path / "systemctl"
    stub.write_text(f'#!/bin/sh\necho "$*" >>{log}\n')
    stub.chmod(0o755)
    monkeypatch.setenv("WLB_SYSTEMCTL", str(stub))
    assert tool.main(["--user", "u01"]) == 0
    assert log.read_text().splitlines() == [
        "stop jupyterhub.service",
        "stop jupyter-u01.service",
        "start jupyterhub.service",
    ]
    log.unlink()
    assert tool.main(["--all"]) == 0
    assert log.read_text().splitlines()[1] == "stop jupyter-*.service"


def test_blad_zatrzymania_nie_odwoluje_i_nie_startuje_huba(tool, hub, tmp_path, monkeypatch, capsys):
    url, state = hub
    monkeypatch.setenv("WLB_SYSTEMCTL", "false")
    assert tool.main(["--all"]) == 1
    assert "odwołanie niepotwierdzone, hub zostaje zatrzymany" in capsys.readouterr().err
    assert token_valid(url, state["u01"]["token"])  # bez zatrzymania huba baza nie jest zmieniana


def test_blad_startu_huba_po_odwolaniu(tool, hub, tmp_path, monkeypatch, capsys):
    url, state = hub
    stub = tmp_path / "systemctl"
    stub.write_text('#!/bin/sh\n[ "$1" = start ] && exit 1\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("WLB_SYSTEMCTL", str(stub))
    assert tool.main(["--all"]) == 1
    assert not token_valid(url, state["u01"]["token"])
    assert "hub nie wystartował" in capsys.readouterr().err


def test_bledny_login(tool):
    with pytest.raises(SystemExit):
        tool.main(["--user", "../root"])
