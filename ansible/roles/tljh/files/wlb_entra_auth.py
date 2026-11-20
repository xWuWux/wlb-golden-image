"""Logowanie do huba WLB przez Microsoft Entra ID (#18, mapowanie z #102 D4).

`WlbEntraAuthenticator` rozszerza `AzureAdOAuthenticator` (oauthenticator 17, TLJH 2.0):

- **login = przypisanie z rejestru** `(tid, oid) -> konto` (`wlb_entra_accounts.py`), nigdy
  claim osobowy (`upn`, `name`, `email`). Konta huba (`u01`, `a01`, stare konta nazwane)
  zostają bez zmian — zmienia się wyłącznie źródło uwierzytelnienia;
- **dostęp = przypisanie I rola aplikacji Laboratorium** (`roles` w id_token). Rola nie
  podlega limitowi grup w tokenie (groups overage). `allow_all`, `allowed_users`
  i `admin_users` nie omijają tej kontroli;
- tenant, issuer, audience i ważność id_token są sprawdzane, punkty końcowe to v2.0;
- zakres `openid profile` (Entra gwarantuje `oid` dopiero z `profile`), ale z tokenu zostają
  tylko `tid`, `oid` i `roles` — imię, e-mail i UPN nie trafiają do modelu uwierzytelnienia;
- dziennik: zdarzenia `WLB Entra: kod=<KOD>` z pseudonimem osoby (`oid`) ALBO pseudonimem
  konta (`konto=<skrót>`, 12 znaków SHA-256 loginu) — nigdy loginu i nigdy obu naraz, żeby
  dziennik nie budował mapowania login↔osoba. Standardowe logi JupyterHub (np. ścieżki
  `/user/<login>`) zawierają login — to poza tym modułem;
- **konto raz związane z osobą nie przechodzi na inną** (`bindings_file`, obok bazy huba na
  dysku roboczym): pierwsze udane logowanie wiąże konto z `(tid, oid)` na stałe. Rejestr
  wskazujący na koncie inną osobę odmawia jej logowania — przekazanie konta wymaga procedury
  z odwołaniem poświadczeń (#102 D3, `wlb-hub-revoke --user`);
- plik powiązań zakłada `wlb-firstboot` przy przejściu na Entra, razem z odwołaniem wszystkich
  poświadczeń sprzed przejścia (`wlb-hub-revoke --all`). Brak pliku w trakcie pracy to awaria
  albo niepełne odtworzenie — logowanie i odświeżanie są wtedy wstrzymane (fail-secure);
- `refresh_user` (wołany przez JupyterHub przy żądaniach do huba po `auth_refresh_age`,
  dla tokenów API i przed startem serwera) odmawia, gdy konto nie ma już wiersza w rejestrze
  albo powiązania.

Odwołanie poświadczeń (ciasteczka, tokeny, połączenia z serwerem) robi `wlb-hub-revoke`, nie ten
moduł: `refresh_user` nie zna pochodzenia sesji. Odebranie roli w Entra działa od następnego
logowania (hub nie wymienia tokenów z Entra po zalogowaniu).

Konfigurację (`70-wlb-auth.py`) generuje `wlb-firstboot` dla `AUTH_MODE=entra`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import wlb_entra_accounts
from oauthenticator.azuread import AzureAdOAuthenticator
from tornado import web
from traitlets import Unicode, default, validate

# Ten sam komunikat dla każdej odmowy: strona logowania nie zdradza, czego brakuje.
DENIED = "Brak dostępu do tego Laboratorium WLB. Skontaktuj się z Administratorem Klienta."


def account_ref(login):
    """Pseudonim konta do dziennika (nie anonimizacja: odwracalny dla znającego listę loginów)."""
    return hashlib.sha256(login.encode()).hexdigest()[:12]


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
    bindings_file = Unicode(
        "/workspace/.wlb-hub/entra-bindings",
        config=True,
        help="Trwałe powiązania konto -> (tid, oid) z pierwszego logowania; obok bazy huba (root, 0600).",
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
        # Entra wysyła `oid` w id_token tylko przy zakresie `profile` (id-token-claims-reference).
        # `profile` dokłada też imię i UPN — odrzucamy je zaraz po odczycie tokenu (token_to_user),
        # więc nie trafiają do modelu uwierzytelnienia ani do dziennika. Bez `email`.
        return ["openid", "profile"]

    def _event(self, level, code, detail=None, *, oid=None, login=None):
        """Jedno zdarzenie WLB: kod przyczyny + pseudonim osoby (oid) albo konta — nigdy oba."""
        if oid is not None and login is not None:
            raise ValueError("oid i konto razem tworzyłyby w dzienniku mapowanie login↔osoba")
        parts = [f"kod={code}"]
        if oid is not None:
            parts.append(f"oid={oid}")
        if login is not None:
            parts.append(f"konto={account_ref(login)}")
        if detail:
            parts.append(detail)
        self.log.log(level, "WLB Entra: %s", " ".join(parts))

    def _accounts(self):
        try:
            return wlb_entra_accounts.load(self.accounts_file, self.tenant_id)
        except wlb_entra_accounts.AccountsError as exc:
            # błędny rejestr = nikt nie wchodzi (fail-secure); szczegóły tylko w dzienniku huba
            self._event(logging.ERROR, "REJESTR_NIEPOPRAWNY", f"logowanie wstrzymane: {exc}")
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
            self._event(logging.WARNING, "TOKEN_ODRZUCONY", f"niezgodne: {', '.join(problems)}")
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

    # --- trwałe powiązanie konta z osobą ---------------------------------------------------------

    def _bindings(self):
        """Konto -> 'tid oid'. Plik zakłada wlb-firstboot; brak albo uszkodzenie = błąd (fail-secure).

        Brak pliku nie może znaczyć „brak powiązań": po utracie pliku następca dostałby konto
        związane wcześniej z inną osobą, choć jej poświadczenia nie zostały odwołane.
        """
        try:
            with open(self.bindings_file, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError as exc:
            self._event(logging.ERROR, "POWIAZANIA_BRAK", f"{self.bindings_file} — logowanie wstrzymane (RB-entra §7)")
            raise web.HTTPError(403, DENIED) from exc
        except (OSError, ValueError) as exc:
            self._event(logging.ERROR, "POWIAZANIA_NIECZYTELNE", f"{self.bindings_file}: {type(exc).__name__}")
            raise web.HTTPError(403, DENIED) from exc
        if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
            self._event(logging.ERROR, "POWIAZANIA_NIECZYTELNE", f"{self.bindings_file}: niepoprawny format")
            raise web.HTTPError(403, DENIED)
        return data

    def _bind(self, bindings, username, identity):
        """Zapisuje NOWE powiązanie (atomowo); istniejących nigdy nie nadpisuje."""
        bindings = {**bindings, username: identity}
        tmp = f"{self.bindings_file}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(bindings, fh, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.bindings_file)

    def user_info_to_username(self, user_info):
        login = self._accounts().login_for(user_info["tid"], user_info["oid"])
        if login is None:
            self._event(logging.WARNING, "BRAK_PRZYPISANIA", oid=user_info["oid"])
            raise web.HTTPError(403, DENIED)
        return login

    def _allowed(self, username, user_info):
        if not self.required_role:
            self._event(logging.ERROR, "BRAK_KONFIGURACJI_ROLI", "logowanie wstrzymane")
            return False
        identity = self._accounts().identity_for(username)
        if identity != (user_info.get("tid"), user_info.get("oid")):
            self._event(logging.WARNING, "PRZYPISANIE_ZMIENIONE", oid=user_info.get("oid"))
            return False
        if self.required_role not in user_info.get("roles", []):
            self._event(logging.WARNING, "BRAK_ROLI", f"rola={self.required_role}", oid=user_info.get("oid"))
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
        identity = f"{user_info['tid']} {user_info['oid']}"
        try:
            bindings = self._bindings()
        except web.HTTPError:
            return False
        bound = bindings.get(username)
        if bound is None:
            try:
                self._bind(bindings, username, identity)
            except OSError as exc:
                self._event(logging.ERROR, "POWIAZANIA_ZAPIS", f"{self.bindings_file}: {exc.strerror}")
                return False
            self._event(logging.INFO, "POWIAZANO", "pierwsze logowanie Entra na konto", login=username)
        elif bound != identity:
            # Stare ciasteczka i tokeny poprzedniej osoby nadal wskazują to konto — dopuszczenie
            # następcy wymaga najpierw ich odwołania (#102 D3). Do tego czasu przekazanie jest zablokowane.
            self._event(
                logging.WARNING, "KONTO_INNEJ_OSOBY", "przekazanie konta wymaga procedury #102 D3", oid=user_info["oid"]
            )
            return False
        return True

    async def refresh_user(self, user, handler=None, **kwargs):
        # JupyterHub woła to przy żądaniach do huba starszych niż auth_refresh_age (ciasteczko, token
        # API) i przed startem serwera (refresh_pre_spawn). Żądanie przechodzi, gdy rejestr nadal
        # wskazuje na koncie osobę, z którą konto jest trwale powiązane. Bez wymiany tokenów z Entra
        # i bez auth_state. False odrzuca bieżące żądanie; nie usuwa poświadczeń z bazy huba.
        try:
            current = self._accounts().identity_for(user.name)
            bound = self._bindings().get(user.name)
        except web.HTTPError:
            return False
        if current is None or bound != " ".join(current):
            self._event(logging.INFO, "SESJA_ODRZUCONA", "brak ważnego przypisania", login=user.name)
            return False
        return True
