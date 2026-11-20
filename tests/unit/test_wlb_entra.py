"""Logowanie przez Entra ID (#18): rejestr przypisań i WlbEntraAuthenticator.

Authenticator testujemy na prawdziwym oauthenticator 17 / JupyterHub 5 (te same główne wersje
co w TLJH 2.0) przez publiczną ścieżkę JupyterHub `get_authenticated_user`; z sieci podmieniamy
wyłącznie wymianę kodu na token (`get_token_info`).
"""

import asyncio
import json
import logging
import sys
import time
from types import SimpleNamespace

import jwt
import pytest
from conftest import REPO_ROOT
from tornado import web
from traitlets.config import Config

sys.path.insert(0, str(REPO_ROOT / "ansible/roles/tljh/files"))
import wlb_entra_accounts as accounts
import wlb_entra_auth

TENANT = "3f1c2b4a-0000-4000-8000-000000000001"
OTHER_TENANT = "3f1c2b4a-0000-4000-8000-000000000002"
OID_ANNA = "9a8b7c6d-0000-4000-8000-0000000000a1"
OID_JAN = "9a8b7c6d-0000-4000-8000-0000000000a2"
OID_OBCY = "9a8b7c6d-0000-4000-8000-0000000000ff"
CLIENT = "6c3e2f10-0000-4000-8000-0000000000c1"
ROLE = "WLB.Lab.lab-test01"

REGISTRY = f"""# tid oid konto
{TENANT} {OID_ANNA} u01
{TENANT.upper()} {OID_JAN.upper()} jkowalski   # stare konto nazwane sprzed IMG-002
"""


# --- rejestr przypisań ----------------------------------------------------------------------------


def test_rejestr_poprawny_z_komentarzami_i_wielkimi_literami():
    reg = accounts.parse(REGISTRY, TENANT)
    assert reg.login_for(TENANT, OID_ANNA) == "u01"
    assert reg.login_for(TENANT.upper(), OID_JAN.upper()) == "jkowalski"
    assert reg.login_for(TENANT, OID_OBCY) is None
    assert reg.identity_for("jkowalski") == (TENANT, OID_JAN)
    assert reg.identity_for("u02") is None
    assert reg.logins == {"u01", "jkowalski"}


@pytest.mark.parametrize(
    "line, fragment",
    [
        (f"{TENANT} {OID_ANNA}", "oczekiwano trzech pól"),
        (f"{TENANT} {OID_ANNA} u01 nadmiar", "oczekiwano trzech pól"),
        (f"nie-guid {OID_ANNA} u01", "tid nie jest identyfikatorem GUID"),
        (f"{TENANT} nie-guid u01", "oid nie jest identyfikatorem GUID"),
        (f"{OTHER_TENANT} {OID_ANNA} u01", "tid spoza tenantu"),
        (f"{TENANT} {OID_ANNA} U01", "niepoprawny login"),
        (f"{TENANT} {OID_ANNA} ../root", "niepoprawny login"),
    ],
)
def test_rejestr_bledny_wiersz(line, fragment):
    with pytest.raises(accounts.AccountsError, match=fragment) as exc:
        accounts.parse(line + "\n", TENANT)
    assert "wiersz 1" in str(exc.value)


def test_rejestr_jedna_osoba_jedno_konto():
    with pytest.raises(accounts.AccountsError, match=r"ta sama osoba .* w wierszu 1"):
        accounts.parse(f"{TENANT} {OID_ANNA} u01\n{TENANT} {OID_ANNA} u02\n", TENANT)
    with pytest.raises(accounts.AccountsError, match="to samo konto przypisane już w wierszu 1"):
        accounts.parse(f"{TENANT} {OID_ANNA} u01\n{TENANT} {OID_JAN} u01\n", TENANT)


def test_rejestr_pusty_jest_bledem():
    with pytest.raises(accounts.AccountsError, match="nie zawiera żadnego przypisania"):
        accounts.parse("# tylko komentarz\n\n", TENANT)


def test_rejestr_bez_tenantu_przyjmuje_dowolny_tid():
    assert accounts.parse(f"{OTHER_TENANT} {OID_ANNA} u01\n").login_for(OTHER_TENANT, OID_ANNA) == "u01"


def test_rejestr_brak_pliku(tmp_path):
    with pytest.raises(accounts.AccountsError, match="nie można odczytać rejestru"):
        accounts.load(tmp_path / "brak", TENANT)


def test_cli_check(tmp_path, capsys):
    path = tmp_path / "entra-accounts"
    path.write_text(REGISTRY)
    assert accounts.main(["--check", str(path), "--tenant", TENANT]) == 0
    out = capsys.readouterr().out
    assert "2 przypisań" in out
    # wynik trafia do dziennika firstboot: bez loginów (stare konta nazwane) i identyfikatorów
    assert "jkowalski" not in out and OID_ANNA not in out
    path.write_text(f"{OTHER_TENANT} {OID_ANNA} u01\n")
    assert accounts.main(["--check", str(path), "--tenant", TENANT]) == 1
    assert "tid spoza tenantu" in capsys.readouterr().err


# --- WlbEntraAuthenticator ------------------------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "entra-accounts"
    path.write_text(REGISTRY)
    # plik powiązań zakłada wlb-firstboot przy przejściu na Entra (pusty: nikt jeszcze się nie logował)
    (tmp_path / "entra-bindings").write_text("{}")
    return path


def make_auth(registry, **extra):
    c = Config()
    c.WlbEntraAuthenticator.tenant_id = TENANT
    c.WlbEntraAuthenticator.client_id = CLIENT
    c.WlbEntraAuthenticator.client_secret = "sekret"
    c.WlbEntraAuthenticator.oauth_callback_url = "https://portal.wlb.local/hub/oauth_callback"
    c.WlbEntraAuthenticator.required_role = ROLE
    c.WlbEntraAuthenticator.accounts_file = str(registry)
    c.WlbEntraAuthenticator.bindings_file = str(registry.parent / "entra-bindings")
    for key, value in extra.items():
        setattr(c.WlbEntraAuthenticator, key, value)
    return wlb_entra_auth.WlbEntraAuthenticator(config=c)


def id_token(**overrides):
    claims = {
        "aud": CLIENT,
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "tid": TENANT,
        "oid": OID_ANNA,
        "exp": int(time.time()) + 3600,
        "roles": [ROLE],
        "name": "Anna Nowak",
        "preferred_username": "anna.nowak@gumed.edu.pl",
        "email": "anna.nowak@gumed.edu.pl",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, "klucz-testowy-bez-znaczenia-dla-weryfikacji", algorithm="HS256")


def login(auth, monkeypatch, token):
    async def fake_token_info(handler, params):
        return {"access_token": "a", "token_type": "Bearer", "id_token": token}

    monkeypatch.setattr(auth, "get_token_info", fake_token_info)
    monkeypatch.setattr(auth, "build_access_tokens_request_params", lambda handler, data: {})
    return asyncio.run(auth.get_authenticated_user(handler=None, data={}))


def test_domyslne_punkty_koncowe_v2_i_minimalny_scope(registry):
    auth = make_auth(registry)
    assert auth.authorize_url == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize"
    assert auth.token_url == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
    assert auth.scope == ["openid", "profile"]  # Entra wysyła oid dopiero z profile
    assert auth.login_service == "Microsoft Entra ID"
    assert auth.allow_all is False and auth.manage_groups is False


def test_logowanie_przypisanej_osoby_z_rola(registry, monkeypatch, caplog):
    auth = make_auth(registry)
    model = login(auth, monkeypatch, id_token())
    assert model["name"] == "u01"
    # do modelu nie trafiają dane osobowe z tokenu — tylko identyfikatory i role
    assert model["auth_state"]["user"] == {"tid": TENANT, "oid": OID_ANNA, "roles": [ROLE]}
    for key in ("id_token", "token_response", "access_token", "refresh_token"):
        assert key not in model["auth_state"]
    assert "gumed.edu.pl" not in repr(model)
    assert "Anna" not in caplog.text and "gumed.edu.pl" not in caplog.text


def test_stare_konto_nazwane_bez_migracji(registry, monkeypatch):
    model = login(make_auth(registry), monkeypatch, id_token(oid=OID_JAN))
    assert model["name"] == "jkowalski"


def test_brak_przypisania_to_403_z_oid_w_dzienniku(registry, monkeypatch, caplog):
    with pytest.raises(web.HTTPError) as exc:
        login(make_auth(registry), monkeypatch, id_token(oid=OID_OBCY))
    assert exc.value.status_code == 403
    assert exc.value.log_message == wlb_entra_auth.DENIED
    assert OID_OBCY in caplog.text and "Anna" not in caplog.text


def test_bez_roli_laboratorium_brak_dostepu(registry, monkeypatch, caplog):
    assert login(make_auth(registry), monkeypatch, id_token(roles=["WLB.Lab.inny"])) is None
    assert login(make_auth(registry), monkeypatch, id_token(roles=None)) is None
    assert login(make_auth(registry), monkeypatch, id_token(roles=ROLE)) is None  # string, nie lista
    assert "kod=BRAK_ROLI" in caplog.text


@pytest.mark.parametrize(
    "extra",
    [
        {"allow_all": True},
        {"allowed_users": {"u01"}},
        {"admin_users": {"u01"}},
    ],
)
def test_allow_all_allowed_users_i_admin_nie_omijaja_roli(registry, monkeypatch, extra):
    auth = make_auth(registry, **extra)
    assert login(auth, monkeypatch, id_token(roles=[])) is None


def test_allow_all_nie_da_sie_wlaczyc(registry, caplog):
    assert make_auth(registry, allow_all=True).allow_all is False
    assert "allow_all ignorowane" in caplog.text


def test_brak_required_role_wstrzymuje_logowanie(registry, monkeypatch, caplog):
    assert login(make_auth(registry, required_role=""), monkeypatch, id_token()) is None
    assert "kod=BRAK_KONFIGURACJI_ROLI" in caplog.text


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"tid": OTHER_TENANT}, "tid"),
        ({"iss": f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0"}, "iss"),
        ({"iss": f"https://sts.windows.net/{TENANT}/"}, "iss"),  # token v1
        ({"aud": "inna-aplikacja"}, "aud"),
        ({"exp": int(time.time()) - 10}, "exp"),
        ({"exp": None}, "exp"),
        ({"oid": "nie-guid"}, "oid"),
        ({"oid": None}, "oid"),  # brak claimu oid (np. bez zakresu profile) = odmowa, nie UPN
    ],
)
def test_odrzucony_id_token(registry, monkeypatch, caplog, overrides, field):
    with pytest.raises(web.HTTPError) as exc:
        login(make_auth(registry), monkeypatch, id_token(**overrides))
    assert exc.value.status_code == 403
    assert f"niezgodne: {field}" in caplog.text


def test_aud_jako_lista(registry, monkeypatch):
    model = login(make_auth(registry), monkeypatch, id_token(aud=["inna", CLIENT]))
    assert model["name"] == "u01"


def test_przejecie_konta_w_trakcie_logowania(registry, monkeypatch, caplog):
    """Rejestr zmienia się między mapowaniem a autoryzacją — decyduje stan bieżący."""
    auth = make_auth(registry)
    original = auth.user_info_to_username

    def swap_then_map(user_info):
        login_name = original(user_info)
        registry.write_text(f"{TENANT} {OID_JAN} u01\n")  # konto przejęła inna osoba
        return login_name

    monkeypatch.setattr(auth, "user_info_to_username", swap_then_map)
    assert login(auth, monkeypatch, id_token()) is None
    assert "kod=PRZYPISANIE_ZMIENIONE" in caplog.text


def test_bledny_rejestr_wstrzymuje_logowanie(registry, monkeypatch, caplog):
    registry.write_text(f"{TENANT} {OID_ANNA} u01\n{TENANT} {OID_JAN} u01\n")
    with pytest.raises(web.HTTPError) as exc:
        login(make_auth(registry), monkeypatch, id_token())
    assert exc.value.status_code == 403
    assert "kod=REJESTR_NIEPOPRAWNY" in caplog.text


def test_check_allowed_bez_modelu_odmawia(registry):
    assert asyncio.run(make_auth(registry).check_allowed("u01", None)) is False


def refresh(auth, name):
    return asyncio.run(auth.refresh_user(SimpleNamespace(name=name)))


def bindings(registry):
    return json.loads((registry.parent / "entra-bindings").read_text())


def test_pierwsze_logowanie_wiaze_konto_z_osoba(registry, monkeypatch):
    auth = make_auth(registry)
    assert login(auth, monkeypatch, id_token())["name"] == "u01"
    assert bindings(registry) == {"u01": f"{TENANT} {OID_ANNA}"}
    assert (registry.parent / "entra-bindings").stat().st_mode & 0o777 == 0o600
    assert refresh(auth, "u01") is True
    login(auth, monkeypatch, id_token())  # kolejne logowanie tej samej osoby niczego nie zmienia
    assert bindings(registry) == {"u01": f"{TENANT} {OID_ANNA}"}


def test_przekazanie_konta_zablokowane_bez_powrotu_starej_sesji(registry, monkeypatch, caplog):
    """Przegląd #330: A zalogowana, u01 przepisane na B, B się loguje — stara sesja A nie może wrócić."""
    caplog.set_level(logging.INFO)
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())  # A
    registry.write_text(f"{TENANT} {OID_OBCY} u01\n")
    assert refresh(auth, "u01") is False  # żądania A podlegające odświeżeniu odrzucone
    assert login(auth, monkeypatch, id_token(oid=OID_OBCY)) is None  # B nie przejmie konta
    assert "kod=KONTO_INNEJ_OSOBY" in caplog.text
    assert bindings(registry) == {"u01": f"{TENANT} {OID_ANNA}"}  # powiązanie bez zmian
    assert refresh(auth, "u01") is False  # i stara sesja A nadal odrzucana


def test_usuniecie_z_rejestru_odrzuca_zadania(registry, monkeypatch):
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())
    login(auth, monkeypatch, id_token(oid=OID_JAN))
    registry.write_text(f"{TENANT} {OID_JAN} jkowalski\n")
    assert refresh(auth, "u01") is False
    assert refresh(auth, "jkowalski") is True
    registry.write_text("zepsuty\n")
    assert refresh(auth, "jkowalski") is False


def test_sesja_sprzed_migracji_bez_powiazania_odrzucona(registry):
    # konto w rejestrze, ale nikt nie logował się na nie przez Entra (np. sesja hasłem przed migracją)
    assert refresh(make_auth(registry), "u01") is False


def test_odswiezenie_niezalezne_od_enable_auth_state(registry, monkeypatch):
    # bazowy refresh_user przy auth_state wymienia tokeny z token_response, którego nie przechowujemy
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())
    auth.enable_auth_state = True
    assert refresh(auth, "u01") is True


def test_brak_zapisu_powiazania_to_odmowa(registry, monkeypatch, caplog):
    auth = make_auth(registry)

    def fail(*args):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(wlb_entra_auth.os, "replace", fail)
    assert login(auth, monkeypatch, id_token()) is None
    assert "kod=POWIAZANIA_ZAPIS" in caplog.text
    assert bindings(registry) == {}


def test_brak_pliku_powiazan_wstrzymuje_logowanie_i_zadania(registry, monkeypatch, caplog):
    """Przegląd #330: utrata pliku nie może wyzerować historii i odblokować przekazania konta."""
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())  # A wiąże u01
    registry.write_text(f"{TENANT} {OID_OBCY} u01\n")  # rejestr wskazuje B
    assert login(auth, monkeypatch, id_token(oid=OID_OBCY)) is None  # B odrzucona
    (registry.parent / "entra-bindings").unlink()  # utrata pliku / niepełne odtworzenie
    assert login(auth, monkeypatch, id_token(oid=OID_OBCY)) is None  # B nadal odrzucona
    assert refresh(auth, "u01") is False  # stare sesje konta też
    assert "kod=POWIAZANIA_BRAK" in caplog.text
    assert not (registry.parent / "entra-bindings").exists()  # authenticator nie zakłada pliku sam


def test_dziennik_bez_loginow_i_bez_mapowania_login_osoba(registry, monkeypatch, caplog):
    """Przegląd #330 (P2): stare konta nazwane to dane osobowe."""
    caplog.set_level(logging.INFO)
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token(oid=OID_JAN))  # konto nazwane jkowalski: POWIAZANO
    login(auth, monkeypatch, id_token(oid=OID_JAN, roles=[]))  # BRAK_ROLI
    registry.write_text(f"{TENANT} {OID_ANNA} u01\n")
    refresh(auth, "jkowalski")  # SESJA_ODRZUCONA
    ref = wlb_entra_auth.account_ref("jkowalski")
    wlb = [r.getMessage() for r in caplog.records if r.getMessage().startswith("WLB Entra:")]
    assert wlb
    for message in wlb:
        assert "jkowalski" not in message, message
        assert not (OID_JAN in message and ref in message), message
    # standardowe logi JupyterHub („User '…' not allowed.") zawierają login — poza tym modułem (RB-entra)
    assert f"konto={ref}" in caplog.text and f"oid={OID_JAN}" in caplog.text
    with pytest.raises(ValueError):
        auth._event(logging.INFO, "X", oid=OID_JAN, login="jkowalski")


@pytest.mark.parametrize("content", ["{nie-json", "[]", '{"u01": 1}'])
def test_uszkodzone_powiazania_wstrzymuja_logowanie_i_zadania(registry, monkeypatch, caplog, content):
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())
    (registry.parent / "entra-bindings").write_text(content)
    assert refresh(auth, "u01") is False
    assert login(auth, monkeypatch, id_token()) is None
    assert "kod=POWIAZANIA_NIECZYTELNE" in caplog.text
