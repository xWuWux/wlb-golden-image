"""wlb-hub-user na prawdziwej bazie JupyterHub (ta sama główna wersja co w TLJH 2.0)."""

import io

import bcrypt
import pytest
from jupyterhub import orm
from nativeauthenticator.orm import UserInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def hub_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/jupyterhub.sqlite"
    orm.new_session_factory(url)  # inicjalizacja schematu jak przy pierwszym starcie huba
    monkeypatch.setenv("WLB_HUB_DB_URL", url)
    return url


def user_info(url, login):
    with Session(create_engine(url)) as db:
        return db.query(UserInfo).filter_by(username=login).first()


def test_tworzy_zatwierdzone_konto_z_wygenerowanym_haslem(hub_user, hub_db, capsys):
    hub_user.main(["Anna.Kowalska"])
    password = capsys.readouterr().out.strip()
    assert len(password) >= hub_user.MIN_PASSWORD_LENGTH

    info = user_info(hub_db, "anna.kowalska")  # login znormalizowany do małych liter
    assert info.is_authorized
    assert bcrypt.checkpw(password.encode(), info.password)


def test_ponowne_wywolanie_resetuje_haslo(hub_user, hub_db, capsys):
    hub_user.main(["anna"])
    first = capsys.readouterr().out.strip()
    hub_user.main(["anna"])
    second = capsys.readouterr().out.strip()

    info = user_info(hub_db, "anna")
    assert first != second
    assert bcrypt.checkpw(second.encode(), info.password)
    assert not bcrypt.checkpw(first.encode(), info.password)


def test_ponowne_wywolanie_zatwierdza_wniosek_o_konto(hub_user, hub_db, capsys):
    with Session(create_engine(hub_db)) as db:
        db.add(UserInfo(username="piotr", password=b"x", is_authorized=False))
        db.commit()
    hub_user.main(["piotr"])
    assert user_info(hub_db, "piotr").is_authorized


def test_if_missing_nie_zmienia_istniejacego_konta(hub_user, hub_db, capsys):
    hub_user.main(["admin-klienta"])
    original = capsys.readouterr().out.strip()
    hub_user.main(["admin-klienta", "--if-missing"])
    assert capsys.readouterr().out == ""
    assert bcrypt.checkpw(original.encode(), user_info(hub_db, "admin-klienta").password)


def test_if_missing_zaklada_brakujace_konto(hub_user, hub_db, capsys):
    hub_user.main(["nowy", "--if-missing"])
    assert capsys.readouterr().out.strip()
    assert user_info(hub_db, "nowy").is_authorized


def test_haslo_ze_stdin(hub_user, hub_db, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("bardzo-dlugie-haslo\n"))
    hub_user.main(["ewa", "--password-stdin"])
    assert capsys.readouterr().out == ""  # hasło podane przez użytkownika nie jest wypisywane
    assert bcrypt.checkpw(b"bardzo-dlugie-haslo", user_info(hub_db, "ewa").password)


def test_za_krotkie_haslo_ze_stdin(hub_user, hub_db, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("krotkie\n"))
    with pytest.raises(SystemExit, match="co najmniej 12"):
        hub_user.main(["ewa", "--password-stdin"])
    assert user_info(hub_db, "ewa") is None


@pytest.mark.parametrize("login", ["_root", "Zły login", "a" * 33, "", "../etc"])
def test_nieprawidlowy_login(hub_user, hub_db, login):
    with pytest.raises(SystemExit, match="Nieprawidłowy login"):
        hub_user.main([login])


def test_niezainicjalizowana_baza(hub_user, tmp_path, monkeypatch):
    monkeypatch.setenv("WLB_HUB_DB_URL", f"sqlite:///{tmp_path}/pusta.sqlite")
    with pytest.raises(SystemExit, match="nie jest zainicjalizowana"):
        hub_user.main(["anna"])


def test_domyslna_baza_na_dysku_roboczym(hub_user):
    assert hub_user.DEFAULT_DB_URL == "sqlite:////workspace/.wlb-hub/jupyterhub.sqlite"
