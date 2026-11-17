# IMG-011: Logowanie przez Microsoft Entra ID — mapowanie (tid, oid) na istniejące konta

* **Status:** Proponowana (IdP = Entra ID zdecydowane przez Właściciela Platformy 2026-11-17; rejestr na VM do potwierdzenia przez IOD w #102)
* **Data:** 2026-11-17
* **Autorzy / decyduje:** Właściciel Platformy (IdP, model dostępu); IOD (lokalizacja rejestru przypisań)
* **Powiązania:** Regulamin: §6 (IdP + MFA), §20, §21 · RODO · Zgłoszenia/PR: #18, #102 (D1, D4, D5), #57, #317, #51 · IMG-002, IMG-003, IMG-005 · Pliki: `ansible/roles/tljh/files/wlb_entra_auth.py`, `ansible/roles/tljh/files/wlb_entra_accounts.py`, `ansible/roles/lab_config/files/wlb-firstboot` (5c), `docs/runbooks/RB-entra.md`

## Kontekst i problem

IMG-005 odłożyło IdP na po pilotażu. Docelowo rozważano Keycloak federujący Entra. Właściciel Platformy
zdecydował: **tożsamość z Entra ID** (tenant GUMed, MFA przez Conditional Access, goście B2B dla osób spoza
GUMed). Do rozstrzygnięcia było, jak tożsamość osobowa z Entra ma wejść na **bezosobowe** konta `uNN` (IMG-002),
nie łamiąc kont ani danych istniejących Laboratoriów.

Dotychczasowy tryb `AUTH_MODE=oidc` (#57) zamieniał claim (`preferred_username`) wprost na login. Na
`main` miał trzy wady:
1. Tworzył konta osobowe obok `uNN`.
2. Bez grup generował `allow_all = True`, czyli dostęp dla każdego w tenancie (P0 z audytu #18).
3. Z grupami w ogóle nie uruchamiał huba na oauthenticator 17 z TLJH 2.0 (`claim_groups_key requires manage_groups`).

## Rozważane opcje

1. **`username_claim` = `upn`/`email`.** Proste, ale dane osobowe trafiają do nazw kont, logów i SIEM, a konta
   nie są pre-provisionowanymi `uNN`. Odrzucone (IMG-002, RODO).
2. **`username_claim` = `oid`.** Konta `jupyter-<guid>` są nieczytelne i nadal nie są `uNN`. Odrzucone (#18, 12.11).
3. **Rejestr `(tid, oid) -> istniejące konto` na VM + rola aplikacji Laboratorium.** Login pochodzi z rejestru,
   dostęp wymaga wpisu i roli. Konta, dane i hasła Native zostają.
4. **Atrybut konta w Entra** (rozszerzenie katalogu z nazwą `uNN`). VM nie trzyma rejestru, ale potrzebne
   są uprawnienia do schematu Entra GUMed i Graph. Każda zmiana przypisania wymaga administratora Entra.

## Decyzja

**Opcja 3.** `AUTH_MODE=entra` uruchamia `WlbEntraAuthenticator` (podklasa `AzureAdOAuthenticator`):

- **Login:** wiersz `tid oid konto` w `/etc/wlb/entra-accounts`. Plik należy do roota, ma prawa `0600` i zawiera
  tylko identyfikatory. Jedna osoba ma jedno konto, jedno konto ma jedną osobę. Rejestr może wskazywać
  też stare konta nazwane.
- **Dostęp:** wpis w rejestrze **i** rola aplikacji Laboratorium (`ENTRA_REQUIRED_ROLE`) w `roles` id_token.
  Rola zamiast grup, bo grupy podlegają limitowi w tokenie (overage). `allow_all` jest zablokowane w kodzie,
  a `allowed_users` i admin nie omijają kontroli.
- **Token:** punkty końcowe v2.0, zakres `openid` (bez imienia i adresu e-mail). Sprawdzane są `tid`, `iss`,
  `aud` i `exp`. Z claimów zostają tylko `tid`, `oid` i `roles`. Surowy id_token nie trafia do `auth_state`.
- **Odwołanie i przejęcie:** rejestr jest czytany przy każdym logowaniu. Sesja jest związana z osobą:
  po logowaniu zapisujemy, która para `(tid, oid)` weszła na konto (`/var/lib/wlb/entra-logins`). Przy
  odświeżaniu (5 min), dla tokenów API i przed startem serwera ten zapis musi zgadzać się z rejestrem.
  Usunięcie wiersza albo przekazanie konta kończy sesje i tokeny poprzedniej osoby bez restartu huba.
- **Fail-secure:** `wlb-firstboot` waliduje zmienne i rejestr przed zmianą na VM. Błędny rejestr w trakcie
  pracy wstrzymuje logowanie (403), a nie otwiera dostępu.
- **Migracja i powrót:** zmiana `AUTH_MODE` per Laboratorium (RB-entra). Konta, UID, `/workspace`,
  baza huba i hasła Native bez zmian.

Przy okazji `AUTH_MODE=oidc` wymaga niepustego `OIDC_ALLOWED_GROUPS` i generuje konfigurację zgodną
z oauthenticator 17.

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Nie. Realizuje §6 (IdP + MFA) i IMG-002 (konta bezosobowe, mapowanie
  w rejestrze). Zmienia rekomendację IMG-005 („Keycloak federujący Entra”) na bezpośrednie Entra,
  zgodnie z decyzją Właściciela Platformy.

## Konsekwencje

* **Pozytywne:**
  - brak imion, UPN i e-maili w loginach i logach. W dzienniku huba jest `oid` przy odmowach (pseudonim, nadal dana osobowa),
  - istniejące konta i dane nienaruszone, a migracja i rollback sprowadzają się do zmiany jednej zmiennej,
  - dostęp per Laboratorium nadawany w Entra (rola) i na VM (rejestr), bez restartu huba,
  - naprawione P0 i błąd startu trybu `oidc`.
* **Negatywne / dług techniczny:**
  - rejestr na VM to dane pseudonimizowane (oid ↔ konto) objęte backupem. Lokalizację musi potwierdzić IOD (#102 D1),
  - utrzymanie rejestru jest ręczne. Narzędzie dla Administratora Klienta i synchronizacja z rejestrem
    organizacyjnym to zakres #102/#51,
  - odebranie roli lub blokada w Entra działa od następnego logowania: hub nie wymienia tokenów z Entra.
    Natychmiastowe odcięcie zapewnia usunięcie wiersza z rejestru. Pełne sprawdzanie ról w trakcie sesji
    wymagałoby `enable_auth_state` + `offline_access` (klucz szyfrujący, refresh token) i jest osobną decyzją,
  - podpis id_token nie jest weryfikowany lokalnie (jak w oauthenticator). Token pochodzi bezpośrednio z punktu `token` po TLS,
  - brak testu z prawdziwym tenantem w CI.
* **Świadomie pominięte:**
  - usunięcie haseł Native (osobny krok po odbiorze),
  - procedura przejęcia konta z unieważnieniem sesji (#102 D3),
  - portal vs VDI (#18 D2),
  - wiele tenantów (rejestr już ma kolumnę `tid`, ale walidacja wymaga tenantu Laboratorium).
