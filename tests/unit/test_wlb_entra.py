"""Logowanie przez Entra ID (#18): rejestr przypisań i WlbEntraAuthenticator.

Authenticator testujemy na prawdziwym oauthenticator 17 / JupyterHub 5 (te same główne wersje
co w TLJH 2.0) przez publiczną ścieżkę JupyterHub `get_authenticated_user`; z sieci podmieniamy
wyłącznie wymianę kodu na token (`get_token_info`).
"""

import asyncio
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
    return path


def make_auth(registry, **extra):
    c = Config()
    c.WlbEntraAuthenticator.tenant_id = TENANT
    c.WlbEntraAuthenticator.client_id = CLIENT
    c.WlbEntraAuthenticator.client_secret = "sekret"
    c.WlbEntraAuthenticator.oauth_callback_url = "https://portal.wlb.local/hub/oauth_callback"
    c.WlbEntraAuthenticator.required_role = ROLE
    c.WlbEntraAuthenticator.accounts_file = str(registry)
    c.WlbEntraAuthenticator.logins_file = str(registry.parent / "entra-logins")
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
    assert auth.scope == ["openid"]
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
    assert "bez roli aplikacji" in caplog.text


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
    assert "brak required_role" in caplog.text


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
    assert "nie jest przypisane" in caplog.text


def test_bledny_rejestr_wstrzymuje_logowanie(registry, monkeypatch, caplog):
    registry.write_text(f"{TENANT} {OID_ANNA} u01\n{TENANT} {OID_JAN} u01\n")
    with pytest.raises(web.HTTPError) as exc:
        login(make_auth(registry), monkeypatch, id_token())
    assert exc.value.status_code == 403
    assert "rejestr przypisań niepoprawny" in caplog.text


def test_check_allowed_bez_modelu_odmawia(registry):
    assert asyncio.run(make_auth(registry).check_allowed("u01", None)) is False


def refresh(auth, name):
    return asyncio.run(auth.refresh_user(SimpleNamespace(name=name)))


def test_sesja_trwa_dopoki_rejestr_wskazuje_te_sama_osobe(registry, monkeypatch):
    auth = make_auth(registry)
    assert login(auth, monkeypatch, id_token())["name"] == "u01"
    assert (registry.parent / "entra-logins").stat().st_mode & 0o777 == 0o600
    assert refresh(auth, "u01") is True


def test_przejecie_konta_konczy_sesje_poprzedniej_osoby(registry, monkeypatch, caplog):
    """#102 D3: konto u01 przekazane innej osobie — sesja i tokeny poprzedniej osoby wygasają."""
    caplog.set_level(logging.INFO)
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())
    registry.write_text(f"{TENANT} {OID_OBCY} u01\n")
    assert refresh(auth, "u01") is False
    assert "nieaktualna wobec rejestru" in caplog.text


def test_usuniecie_z_rejestru_i_bledny_rejestr_koncza_sesje(registry, monkeypatch):
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())
    login(auth, monkeypatch, id_token(oid=OID_JAN))
    registry.write_text(f"{TENANT} {OID_JAN} jkowalski\n")
    assert refresh(auth, "u01") is False
    assert refresh(auth, "jkowalski") is True
    registry.write_text("zepsuty\n")
    assert refresh(auth, "jkowalski") is False


def test_sesja_sprzed_migracji_bez_zapisu_wymaga_logowania_entra(registry):
    # konto w rejestrze, ale nikt nie logował się na nie przez Entra (np. sesja hasłem przed migracją)
    assert refresh(make_auth(registry), "u01") is False


def test_odswiezenie_niezalezne_od_enable_auth_state(registry, monkeypatch):
    # bazowy refresh_user przy auth_state wymienia tokeny z token_response, którego nie przechowujemy
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())
    auth.enable_auth_state = True
    assert refresh(auth, "u01") is True


def test_brak_zapisu_logowania_to_odmowa(registry, monkeypatch, caplog):
    auth = make_auth(registry, logins_file=str(registry.parent / "brak-katalogu" / "entra-logins"))
    assert login(auth, monkeypatch, id_token()) is None
    assert "nie można zapisać" in caplog.text


def test_uszkodzony_zapis_logowan_konczy_sesje(registry, monkeypatch):
    auth = make_auth(registry)
    login(auth, monkeypatch, id_token())
    (registry.parent / "entra-logins").write_text("[]")
    assert refresh(auth, "u01") is False
    (registry.parent / "entra-logins").write_text("{nie-json")
    assert refresh(auth, "u01") is False
