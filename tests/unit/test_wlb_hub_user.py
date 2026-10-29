"""wlb-hub-user na prawdziwej bazie JupyterHub (ta sama główna wersja co w TLJH 2.0)."""

import io
import sqlite3
import threading
import time

import bcrypt
import pytest
from jupyterhub import orm
from nativeauthenticator.orm import UserInfo
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
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
    hub_user.main(["a01"])
    original = capsys.readouterr().out.strip()
    hub_user.main(["a01", "--if-missing"])
    assert capsys.readouterr().out == ""
    assert bcrypt.checkpw(original.encode(), user_info(hub_db, "a01").password)


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


# --- Blokada zapisu SQLite przy działającym hubie (#31) ---------------------------------------


def _hold_write_lock(path, seconds, ready):
    """Trzyma blokadę zapisu (BEGIN IMMEDIATE) przez `seconds`, jak hub w trakcie zapisu/kopii."""
    conn = sqlite3.connect(path, isolation_level=None, timeout=seconds + 5)
    conn.execute("BEGIN IMMEDIATE")
    ready.set()
    time.sleep(seconds)
    conn.execute("ROLLBACK")
    conn.close()


def test_czeka_na_blokade_zapisu_i_konczy_sukcesem(hub_user, hub_db, tmp_path, monkeypatch):
    path = str(tmp_path / "jupyterhub.sqlite")
    ready = threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(path, 1.5, ready))
    holder.start()
    ready.wait()
    monkeypatch.setattr(hub_user, "LOCK_TIMEOUT", 3)
    hub_user.main(["anna"])  # czeka ~1,5 s na zwolnienie blokady, potem sukces
    holder.join()
    assert user_info(hub_db, "anna").is_authorized


def test_blokada_dluzsza_niz_timeout_daje_blad(hub_user, hub_db, tmp_path, monkeypatch):
    path = str(tmp_path / "jupyterhub.sqlite")
    ready = threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(path, 1.5, ready))
    holder.start()
    ready.wait()
    monkeypatch.setattr(hub_user, "LOCK_TIMEOUT", 0.5)
    with pytest.raises(OperationalError, match="database is locked"):
        hub_user.main(["anna"])
    holder.join()


def test_dwa_rownolegle_wywolania_nie_tworza_duplikatu(hub_user, hub_db):
    # BEGIN IMMEDIATE serializuje odczyt+zapis, więc drugie wywołanie widzi już wstawiony wiersz
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        hub_user.main(["anna"])

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with Session(create_engine(hub_db)) as db:
        assert db.query(UserInfo).filter_by(username="anna").count() == 1
