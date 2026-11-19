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
- **Token:** punkty końcowe v2.0, zakresy `openid profile`. Entra wysyła `oid` dopiero z `profile`; imię
  i UPN odrzucamy zaraz po odczycie. Sprawdzane są `tid`, `iss`, `aud` i `exp`. Z claimów zostają tylko `tid`,
  `oid` i `roles`. Surowy id_token ani tokeny dostępu nie trafiają do `auth_state`.
- **Brak przekazywania kont (MVP):** pierwsze udane logowanie trwale wiąże konto z `(tid, oid)`
  (`/workspace/.wlb-hub/entra-bindings`, obok bazy huba). Rejestr wskazujący na koncie inną osobę odrzuca
  jej logowanie. Powód: stare ciasteczka i tokeny poprzedniej osoby identyfikują konto, a nie osobę, więc
  bez ich odwołania następca dzieliłby konto z poprzednikiem. Przekazanie konta będzie jedną operacją
  administracyjną #102 D3 (blokada logowań i spawnu → odwołanie ciasteczek i tokenów Hub/OAuth → zamknięcie
  dostępu do serwera → potwierdzenie → atomowa zmiana przypisania). Awaria zostawi konto zablokowane.
  Plik powiązań zakłada `wlb-firstboot` przy przejściu na Entra; jego brak w trakcie pracy wstrzymuje logowanie
  i odświeżanie (brak pliku nie oznacza „brak powiązań"), a `wlb-firstboot` w trybie entra bez pliku przerywa
  pracę. Nowy pusty plik powstaje tylko przez świadomą reinicjalizację (`WLB_ENTRA_REINIT=1`), która najpierw
  odwołuje poświadczenia wszystkich kont.
- **Odwołanie poświadczeń przy zmianie `AUTH_MODE`:** `refresh_user` nie zna pochodzenia sesji, więc nie
  odróżni ciasteczka z logowania hasłem od sesji Entra tego samego konta. Dlatego `wlb-firstboot` przy każdej
  zmianie trybu (także rollback entra → native) wywołuje `wlb-hub-revoke --all`: zatrzymuje hub i serwery kont,
  zmienia `cookie_id` kont, usuwa tokeny API/OAuth kont i kody OAuth, uruchamia hub. Błąd przerywa firstboot,
  hub zostaje zatrzymany. To samo narzędzie z `--user` odcina jedno konto i jest elementem przyszłej procedury #102 D3.- **Ograniczenie dostępu przy zmianie rejestru:** rejestr jest czytany przy każdym logowaniu oraz w
  `refresh_user` (żądania do huba po `auth_refresh_age`, start serwera). Blokuje to nowe logowania i żądania
  podlegające odświeżeniu. **Nie** jest trwałym odwołaniem poświadczeń ani gwarancją zamknięcia trwających
  połączeń (WebSocket notebooka, noVNC, pamięć podręczna serwera badacza). Pełne odcięcie: `wlb-hub-revoke --user`.
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
  - brak imion, UPN i e-maili w loginach i w zdarzeniach modułu. Zdarzenia mają kod przyczyny i pseudonim osoby (`oid`)
    albo konta (skrót loginu), nigdy login i nigdy oba naraz (pseudonimizacja, nadal dane osobowe). Standardowe wpisy
    JupyterHub zawierają login — poza tym modułem,
  - istniejące konta i dane nienaruszone. Migracja to procedura w oknie serwisowym (rejestr, `AUTH_MODE`; firstboot
    zatrzymuje serwery i odwołuje poświadczenia), a rollback wymaga wcześniejszego resetu haseł Native kont z odebranym
    dostępem (RB-entra §5),
  - dostęp per Laboratorium nadawany w Entra (rola) i na VM (rejestr), bez restartu huba; przekazanie konta innej osobie
    jest zablokowane, zamiast działać bez odwołania poświadczeń,
  - naprawione P0 i błąd startu trybu `oidc`.
* **Negatywne / dług techniczny:**
  - rejestr na VM to dane pseudonimizowane (oid ↔ konto) objęte backupem. Lokalizację musi potwierdzić IOD (#102 D1),
  - utrzymanie rejestru jest ręczne. Narzędzie dla Administratora Klienta i synchronizacja z rejestrem
    organizacyjnym to zakres #102/#51,
  - odebranie roli lub blokada w Entra działa od następnego logowania: hub nie wymienia tokenów z Entra.
    Nie obiecujemy CAE ani ponownej oceny polityk Entra w trakcie lokalnej sesji. Maksymalny wiek sesji
    i SLA odwołania trzeba ustalić z właścicielem platformy (sign-in frequency w Entra, limit sesji huba §9.5),
  - podpis id_token nie jest weryfikowany lokalnie (jak w oauthenticator). Token pochodzi bezpośrednio z punktu `token` po TLS,
  - authenticator jest testowany modułowo z podstawioną odpowiedzią punktu `token`. Odwołanie poświadczeń jest
    testowane na prawdziwej bazie JupyterHub i przez działający hub na VM (ciasteczko, token API, serwer konta).
    Brak testu callbacku i logowania z prawdziwym tenantem w CI,
* **Świadomie pominięte:**
  - usunięcie haseł Native (osobny krok po odbiorze),
  - procedura przekazania konta z odwołaniem poświadczeń (#102 D3); do tego czasu przekazanie jest zablokowane,
  - portal vs VDI (#18 D2),
  - wiele tenantów (rejestr już ma kolumnę `tid`, ale walidacja wymaga tenantu Laboratorium).

## Odbiór (przed produkcją; wymaga tenantu testowego)

1. `oid`/`tid`/`roles` w id_token dla użytkownika wewnętrznego i gościa B2B; brak `oid` = odmowa.
2. Conditional Access: polityka w trybie *On* (nie *Report-only*), brak wyłączeń dla badaczy, efektywne MFA
   gościa B2B (zaufanie do MFA tenantu macierzystego) potwierdzone w logach logowań Entra.
3. Callback: dwie karty, przerwany callback, stary `state`, ponowne użycie kodu, powrót przeglądarką „wstecz”.
   Ochrony z oauthenticator, bez własnego protokołu.
4. Odcięcie przez HTTP/API/WebSocket po migracji i po `wlb-hub-revoke --user`: ciasteczko i token API sprawdza
   etap 5 (`68-entra.sh`); do odbioru zostają token OAuth serwera użyty przez przeglądarkę, trwające połączenie
   noVNC i sesja zalogowana przez Entra (nie Native).
5. Awarie: wygasły `client_secret`, DNS/proxy/TLS/IdP niedostępne, przesunięty zegar. Nowe logowania odmawiają,
   brak automatycznego powrotu do Native, działające obliczenia nie są przerywane.
6. Odtworzenie dysku roboczego z kopii nie przywraca odwołanego dostępu (rejestr wobec rejestru organizacyjnego);
   kopia samej bazy huba bez pliku powiązań kończy się odmową firstboot (`POWIAZANIA_BRAK`), nie cichym dopuszczeniem.
