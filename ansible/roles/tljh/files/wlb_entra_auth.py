"""Logowanie do huba WLB przez Microsoft Entra ID (#18, mapowanie z #102 D4).

`WlbEntraAuthenticator` rozszerza `AzureAdOAuthenticator` (oauthenticator 17, TLJH 2.0):

- **login = przypisanie z rejestru** `(tid, oid) -> konto` (`wlb_entra_accounts.py`), nigdy
  claim osobowy (`upn`, `name`, `email`). Konta huba (`u01`, `a01`, stare konta nazwane)
  zostają bez zmian — zmienia się wyłącznie źródło uwierzytelnienia;
- **dostęp = przypisanie I rola aplikacji Laboratorium** (`roles` w id_token). Rola nie
  podlega limitowi grup w tokenie (groups overage). `allow_all`, `allowed_users`
  i `admin_users` nie omijają tej kontroli;
- tenant, issuer, audience i ważność id_token są sprawdzane, punkty końcowe to v2.0;
- z tokenu zostają tylko `tid`, `oid` i `roles` — imię, e-mail i UPN nie trafiają do
  modelu uwierzytelnienia ani do dziennika (w logach tylko pseudonim `oid` przy odmowie);
- **sesja jest związana z osobą**: po udanym logowaniu zapisujemy, która para `(tid, oid)`
  zalogowała się na konto (`logins_file`, root 0600). Każde odświeżenie sesji, także sesji
  tokenem API i przed startem serwera, porównuje ją z bieżącym rejestrem. Usunięcie wiersza
  albo przekazanie konta innej osobie kończy sesję i tokeny poprzedniej osoby najpóźniej
  po `auth_refresh_age`. Sesja bez zapisu (np. zalogowana hasłem przed migracją) też się kończy.

Odebranie roli aplikacji w Entra działa od następnego logowania (bez wymiany tokenów
z Entra hub nie widzi bieżących ról). Natychmiastowe odcięcie = usunięcie wiersza z rejestru.

Konfigurację (`70-wlb-auth.py`) generuje `wlb-firstboot` dla `AUTH_MODE=entra`.
"""

from __future__ import annotations

import json
import os
import time

import wlb_entra_accounts
from oauthenticator.azuread import AzureAdOAuthenticator
from tornado import web
from traitlets import Unicode, default, validate

# Ten sam komunikat dla każdej odmowy: strona logowania nie zdradza, czego brakuje.
DENIED = "Brak dostępu do tego Laboratorium WLB. Skontaktuj się z Administratorem Klienta."


class WlbEntraAuthenticator(AzureAdOAuthenticator):
    accounts_file = Unicode(
        wlb_entra_accounts.DEFAULT_PATH,
        config=True,
        help="Rejestr przypisań 'tid oid konto' (root, 0600).",
    )
    required_role = Unicode(
        "",
        config=True,
        help="Wartość roli aplikacji Entra wymaganej do wejścia do tego Laboratorium.",
    )
    logins_file = Unicode(
        "/var/lib/wlb/entra-logins",
        config=True,
        help="Kto (tid, oid) ostatnio zalogował się na każde konto; wiąże sesję z osobą (root, 0600).",
    )

    @validate("allow_all")
    def _never_allow_all(self, proposal):
        # JupyterHub przy allow_all w ogóle nie woła check_allowed — dla Entra oznaczałoby to
        # wejście każdej osoby z przypisaniem, bez roli Laboratorium. Nie da się tego włączyć.
        if proposal.value:
            self.log.warning("WLB Entra: allow_all ignorowane — dostęp wymaga przypisania i roli aplikacji")
        return False

    @default("login_service")
    def _login_service_default(self):
        return "Microsoft Entra ID"

    @default("authorize_url")
    def _authorize_url_default(self):
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize"

    @default("token_url")
    def _token_url_default(self):
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

    @default("scope")
    def _scope_default(self):
        # id_token z `oid`, `tid` i `roles` wymaga tylko `openid`; bez `profile`/`email` IdP nie
        # wysyła imienia ani adresu, których WLB nie potrzebuje (minimalizacja danych, RODO)
        return ["openid"]

    def _accounts(self):
        try:
            return wlb_entra_accounts.load(self.accounts_file, self.tenant_id)
        except wlb_entra_accounts.AccountsError as exc:
            # błędny rejestr = nikt nie wchodzi (fail-secure); szczegóły tylko w dzienniku huba
            self.log.error("WLB Entra: rejestr przypisań niepoprawny, logowanie wstrzymane: %s", exc)
            raise web.HTTPError(403, DENIED) from exc

    async def token_to_user(self, token_info):
        claims = await super().token_to_user(token_info)
        tenant = self.tenant_id.lower()
        tid = str(claims.get("tid", "")).lower()
        oid = str(claims.get("oid", "")).lower()
        problems = []
        if tid != tenant:
            problems.append("tid")
        if claims.get("iss") != f"https://login.microsoftonline.com/{tenant}/v2.0":
            problems.append("iss")
        audience = claims.get("aud")
        if audience != self.client_id and not (isinstance(audience, list) and self.client_id in audience):
            problems.append("aud")
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < time.time():
            problems.append("exp")
        if not wlb_entra_accounts.GUID_RE.fullmatch(oid):
            problems.append("oid")
        if problems:
            self.log.warning("WLB Entra: odrzucony id_token (niezgodne: %s)", ", ".join(problems))
            raise web.HTTPError(403, DENIED)
        roles = claims.get("roles") or []
        if not isinstance(roles, list):
            roles = []
        # tylko identyfikatory i role — reszta claimów (imię, UPN, e-mail) nie idzie dalej
        return {"tid": tid, "oid": oid, "roles": [str(r) for r in roles]}

    def build_auth_state_dict(self, token_info, user_info):
        state = super().build_auth_state_dict(token_info, user_info)
        # surowy id_token, odpowiedź i tokeny dostępu zawierają claimy osobowe albo nie są potrzebne —
        # nie przechowujemy ich nawet przy włączonym enable_auth_state (minimalizacja danych, RODO).
        # refresh_user nie wymienia tokenów z Entra, więc ich brak niczego nie psuje.
        for key in ("id_token", "token_response", "access_token", "refresh_token"):
            state.pop(key, None)
        return state

    # --- powiązanie sesji z osobą --------------------------------------------------------------

    def _recorded_logins(self):
        try:
            with open(self.logins_file, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _record_login(self, username, identity):
        logins = self._recorded_logins()
        logins[username] = " ".join(identity)
        tmp = f"{self.logins_file}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(logins, fh, sort_keys=True)
        os.replace(tmp, self.logins_file)

    def user_info_to_username(self, user_info):
        login = self._accounts().login_for(user_info["tid"], user_info["oid"])
        if login is None:
            self.log.warning("WLB Entra: brak przypisania konta dla oid=%s", user_info["oid"])
            raise web.HTTPError(403, DENIED)
        return login

    def _allowed(self, username, user_info):
        if not self.required_role:
            self.log.error("WLB Entra: brak required_role w konfiguracji — logowanie wstrzymane")
            return False
        identity = self._accounts().identity_for(username)
        if identity != (user_info.get("tid"), user_info.get("oid")):
            self.log.warning("WLB Entra: konto %s nie jest przypisane do oid=%s", username, user_info.get("oid"))
            return False
        if self.required_role not in user_info.get("roles", []):
            self.log.warning(
                "WLB Entra: oid=%s (konto %s) bez roli aplikacji %s", user_info.get("oid"), username, self.required_role
            )
            return False
        return True

    async def check_allowed(self, username, auth_model):
        if auth_model is None:
            # JupyterHub 5 zawsze przekazuje model; brak modelu = brak dowodu tożsamości (fail-secure)
            return False
        user_info = (auth_model.get("auth_state") or {}).get(self.user_auth_state_key) or {}
        # świadomie BEZ odwołania do super(): allow_all / allowed_users / admin nie mogą
        # dopuścić osoby bez przypisania i bez roli Laboratorium
        if not self._allowed(username, user_info):
            return False
        try:
            self._record_login(username, (user_info["tid"], user_info["oid"]))
        except OSError as exc:
            # bez zapisu sesja i tak skończyłaby się przy pierwszym odświeżeniu — odmawiamy od razu
            self.log.error("WLB Entra: nie można zapisać %s: %s", self.logins_file, exc.strerror)
            return False
        return True

    async def refresh_user(self, user, handler=None, **kwargs):
        # Woła to JupyterHub co auth_refresh_age dla sesji z ciasteczkiem, dla tokenów API i przed
        # startem serwera (refresh_pre_spawn). Sesja trwa, dopóki rejestr wskazuje na koncie TĘ SAMĄ
        # osobę, która się zalogowała. Bez wymiany tokenów z Entra (i bez auth_state), więc działa
        # niezależnie od enable_auth_state.
        try:
            current = self._accounts().identity_for(user.name)
        except web.HTTPError:
            return False
        recorded = self._recorded_logins().get(user.name)
        if current is None or recorded != " ".join(current):
            self.log.info("WLB Entra: sesja konta %s nieaktualna wobec rejestru — wymagane logowanie", user.name)
            return False
        return True
