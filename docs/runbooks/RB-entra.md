# RB-entra: logowanie przez Microsoft Entra ID (`AUTH_MODE=entra`)

**Dotyczy:** #18 (IdP + MFA), #102 (D4: mapowanie tożsamości na konto) · **Decyzja:** [IMG-011](../adr/IMG-011-logowanie-entra-id.md) ·
**Moduły:** `/opt/wlb/hub/wlb_entra_auth.py`, `/opt/wlb/hub/wlb_entra_accounts.py` · **Pliki:** `/etc/wlb/lab.env`,
`/etc/wlb/entra-accounts` (rejestr), `/workspace/.wlb-hub/entra-bindings` (powiązania)

## Jak to działa

Badacz loguje się w Entra ID GUMed (MFA wymusza Conditional Access po stronie Entra). Hub WLB dostaje
id_token i **nie** robi z niego nazwy konta. Zamiast tego szuka pary `(tid, oid)` w rejestrze przypisań
i loguje na konto, które tam wskazano:

```
Entra ID ── id_token (tid, oid, roles) ──▶ hub WLB ── rejestr /etc/wlb/entra-accounts ──▶ konto u01 / a01 / stare konto
```

Wejście wymaga **obu** warunków:

1. wiersza `tid oid konto` w rejestrze (tylko identyfikatory, bez imion i adresów e-mail);
2. roli aplikacji Laboratorium (`ENTRA_REQUIRED_ROLE`, np. `WLB.Lab.lab-histologia01`) w tokenie.

Inne sytuacje kończą się odmową z tym samym komunikatem („Brak dostępu do tego Laboratorium WLB”).
Przyczyna trafia do dziennika huba jako kod (`WLB Entra: kod=…`, punkt 7) z pseudonimem osoby (`oid`)
**albo** pseudonimem konta (`konto=` — 12 znaków skrótu SHA-256 loginu), nigdy z loginem i nigdy z oboma
naraz. To pseudonimizacja, nie anonimizacja: `oid` i skrót są danymi osobowymi w rozumieniu RODO.
Standardowe wpisy JupyterHub (np. „User '…' not allowed”, ścieżki `/user/<login>`) zawierają login —
ten moduł ich nie zmienia. `allow_all`, `allowed_users` ani uprawnienia administratora nie omijają
tych warunków. Hub prosi o zakresy `openid profile`, bo Entra wysyła `oid` dopiero z `profile`. Imię i UPN
z tego zakresu są odrzucane zaraz po odczycie tokenu.

**Konto raz powiązane z osobą nie przechodzi na inną.** Pierwsze udane logowanie zapisuje trwałe
powiązanie konta z `(tid, oid)` w `/workspace/.wlb-hub/entra-bindings` (obok bazy huba, root, `0600`).
Jeśli rejestr później wskaże na tym koncie inną osobę, jej logowanie zostanie odrzucone. Bezpieczne
przekazanie konta (#102 D3) jeszcze nie istnieje; nowej osobie przydziel wolne konto `uNN`.

Plik powiązań zakłada `wlb-firstboot` przy przejściu na Entra. **Brak pliku w trakcie pracy wstrzymuje
logowanie i odświeżanie sesji** (kod `POWIAZANIA_BRAK`), bo pusty plik pozwoliłby następcy przejąć konto
poprzedniej osoby. Odtwarzanie i świadoma reinicjalizacja: punkt 7.

**Zmiana sposobu logowania odwołuje wszystkie poświadczenia.** Gdy `AUTH_MODE` różni się od trybu z poprzedniego
przebiegu (`/workspace/.wlb-hub/auth-mode`), `wlb-firstboot` przed otwarciem huba uruchamia
`wlb-hub-revoke --all`:
- zatrzymuje hub i wszystkie serwery kont, co zamyka trwające połączenia notebooka, terminala i noVNC;
- nadaje każdemu kontu nowy `cookie_id`, więc dotychczasowe ciasteczka przestają pasować;
- usuwa tokeny API i OAuth kont (także tokeny serwerów) oraz niewykorzystane kody OAuth;
- uruchamia hub.

Dzięki temu po migracji native → entra żadne ciasteczko ani token z logowania hasłem nie przechodzi, także
po pierwszym logowaniu tej samej osoby przez Entra. Tokeny usług huba (np. culler) zostają. Błąd odwołania
przerywa `wlb-firstboot`, a hub zostaje zatrzymany.

**Co robi zmiana rejestru, a czego nie robi.** Zmiana rejestru blokuje nowe logowania i żądania do huba
podlegające odświeżeniu: ciasteczko lub token API starsze niż `auth_refresh_age` (5 min) oraz start serwera.
Sama zmiana rejestru **nie** odwołuje poświadczeń i nie zamyka połączeń. Robi to `wlb-hub-revoke` (punkt 6).

**Konta się nie zmieniają.** Konto systemowe `jupyter-<konto>`, UID, katalog `/workspace/jupyter-<konto>`,
baza huba i rola Administratora Klienta (`a01`, IMG-003) są te same co przy logowaniu hasłem. Rejestr
może wskazywać również stare konto nazwane (sprzed IMG-002). Hasła Native zostają w bazie huba
(droga powrotu, punkt 5).

## 1. Rejestracja aplikacji w Entra (raz na Laboratorium albo raz dla platformy)

Wykonuje administrator Entra GUMed:

1. **App registrations → New registration:** konta tylko z tego katalogu (single tenant).
   Redirect URI typu *Web*: `https://<nazwa-portalu-lab>/hub/oauth_callback`, czyli dokładnie `OIDC_CALLBACK_URL`.
2. **Certificates & secrets:** sekret klienta. Przekaż go wyłącznie przez menedżer sekretów (`OIDC_CLIENT_SECRET`).
   Zanotuj datę wygaśnięcia: wygasły sekret blokuje nowe logowania i nie ma automatycznego powrotu do haseł.
3. **App roles → Create app role:** typ *Users/Groups*, wartość np. `WLB.Lab.<LAB_NAME>`, czyli `ENTRA_REQUIRED_ROLE`.
4. **Enterprise applications → (aplikacja) → Properties:** *Assignment required = Yes*. **Users and groups:**
   przypisz badaczy lub grupę Laboratorium do roli.
5. **Conditional Access:** polityka MFA obejmująca tę aplikację (wymóg §6), w trybie *On*, nie *Report-only*.
   Sama rola aplikacji nie dowodzi MFA. Przy odbiorze sprawdź w logach logowań Entra efektywną politykę dla
   użytkownika wewnętrznego i dla gościa B2B (zaufanie do MFA tenantu macierzystego). Ustal też *sign-in frequency*.
6. Claimy: `oid`, `tid` i `roles` są w id_token v2.0 przy zakresach `openid profile`. Claimów opcjonalnych nie trzeba.

Badacze spoza GUMed: zaproszenie B2B (gość w tenancie GUMed z własnym `oid` w tym tenancie).
Przy odbiorze sprawdź na prawdziwym koncie gościa, że token zawiera `oid` i `tid` tenantu GUMed.

## 2. Rejestr przypisań

Plik `/etc/wlb/entra-accounts` (root, `0600`). Jeden wiersz to jedna osoba na jednym koncie:

```
# tid (tenant GUMed)                    oid (Object ID użytkownika)            konto
3f1c2b4a-0000-4000-8000-000000000001   9a8b7c6d-0000-4000-8000-0000000000a1   a01
3f1c2b4a-0000-4000-8000-000000000001   9a8b7c6d-0000-4000-8000-0000000000b1   u01
```

- `oid` to *Object ID* użytkownika w Entra admin center (Users → użytkownik → Overview).
- Jedna osoba ma tylko jedno konto i jedno konto ma tylko jedną osobę. Duplikat, obcy tenant albo błędny
  format sprawia, że **cały** rejestr jest odrzucany: nikt nie wejdzie, a błąd trafia do dziennika huba.
- Sprawdzenie po edycji: `sudo python3 /opt/wlb/hub/wlb_entra_accounts.py --check /etc/wlb/entra-accounts --tenant <ENTRA_TENANT_ID>`.
- Hub czyta rejestr przy każdym logowaniu, więc zmiany nie wymagają restartu.
- **Nie zmieniaj `oid` przy koncie, na które ktoś już się logował.** Taka osoba zostanie odrzucona (patrz wyżej).
- Rejestr przypisań z datami i historią prowadzi się poza VM (#102). Ten plik zawiera tylko bieżący stan.

## 3. Nowe Laboratorium

Wzór: [`cloud-init/examples/lab-user-data-entra.yaml`](../../cloud-init/examples/lab-user-data-entra.yaml).
Do `lab.env` dodaj `AUTH_MODE=entra`, `ENTRA_TENANT_ID`, `ENTRA_REQUIRED_ROLE`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET` i `OIDC_CALLBACK_URL`. Rejestr dostarcz jako osobny plik `write_files`.

`wlb-firstboot` sprawdza konfigurację **przed** jakąkolwiek zmianą na VM. Brakująca zmienna, tenant
w złym formacie, zły callback, brak rejestru, rejestr dostępny dla innych niż root albo błędny rejestr
przerywa uruchomienie. Konta `a01` i `u01…uNN` powstają jak dotąd, również z hasłami Native (droga powrotu).
Hasłami nie trzeba się dzielić z badaczami.

## 4. Migracja działającego Laboratorium (native → entra)

To procedura w oknie serwisowym z kontrolą sesji, a nie zmiana bez wpływu na pracę badaczy.

Warunki:
- działający TLS huba (`HUB_TLS=1`) z nazwą zgodną z `OIDC_CALLBACK_URL`,
- dostęp huba do `https://login.microsoftonline.com` (sprawdź: `sudo curl -sSI https://login.microsoftonline.com | head -1`),
- zgodny zegar VM (NTP), bo id_token z przesuniętym czasem zostanie odrzucony.

Zapora WLB ogranicza ruch wychodzący tylko kontom badaczy. Jeśli sieć Laboratorium wymaga proxy, ustal to
przed migracją.

1. **Okno serwisowe.** Uprzedź badaczy i poproś o zapisanie pracy. Przełączenie (krok 5) zatrzyma
   wszystkie serwery kont i odwoła wszystkie sesje i tokeny: niezapisana praca w otwartych notebookach przepadnie.
2. W Entra przypisz osoby do roli Laboratorium (punkt 1.4) i odczytaj ich `oid`.
   Każdą osobę przypisz do konta, którego **dotąd używała**. Nowym osobom przydziel wolne konta.
3. Zapisz rejestr: `sudo install -m 0600 -o root -g root entra-accounts /etc/wlb/entra-accounts` i sprawdź go (punkt 2).
4. W `/etc/wlb/lab.env` ustaw `AUTH_MODE=entra` i zmienne z punktu 3 (zachowaj kopię poprzedniego pliku).
5. `sudo wlb-firstboot --force`. Przebieg na krótko zamyka port huba, odwołuje poświadczenia wszystkich kont
   (`zmiana native -> entra — odwołano ciasteczka i tokeny` w dzienniku) i zakłada pusty plik powiązań.
   Konta, dane i hasła Native się nie zmieniają.
6. Weryfikacja:
   - strona logowania pokazuje „Sign in with Microsoft Entra ID”,
   - logowanie testowe konta z rejestru kończy się sukcesem i MFA zostaje wymuszone (log logowań Entra),
   - osoba bez roli albo bez wpisu dostaje odmowę,
   - `sudo journalctl -u jupyterhub | grep 'WLB Entra'` pokazuje kody przyczyn odmów (punkt 7).
7. Gdy produkcyjne Laboratoria aktualizują się automatycznie z `labEnv`, dopisz te zmienne i rejestr do seeda.
   Kroki 1–2 i 6 wykonaj tak samo przy wymianie obrazu.

## 5. Powrót do haseł (rollback)

1. **Najpierw** zresetuj hasła Native kont, którym w międzyczasie odebrano dostęp (`sudo wlb-hub-user <konto>`).
   Bez tego osoba usunięta z rejestru odzyska dostęp starym hasłem.
2. W `/etc/wlb/lab.env` ustaw `AUTH_MODE=native` (lub przywróć kopię) i uruchom `sudo wlb-firstboot --force`.
   Plik `70-wlb-auth.py` zostaje usunięty, sesje i tokeny z logowania przez Entra są odwołane
   (`wlb-hub-revoke --all`), a hub wraca do Native Authenticatora.
3. Badacze logują się dotychczasowymi hasłami albo nowymi, wydanymi w kroku 1.

Rejestr i powiązania można zostawić, bo w trybie `native` nie są używane. Ponowne przejście na `entra`
korzysta z tych samych powiązań. Hasła Native usuwa się osobnym krokiem, po odbiorze Entra (#18).

## 6. Odebranie dostępu

| Co | Gdzie | Efekt |
|---|---|---|
| Usunięcie wiersza z rejestru | `/etc/wlb/entra-accounts` | blokuje nowe logowania oraz żądania do huba podlegające odświeżeniu (ciasteczko/token API po 5 min, start serwera) |
| `sudo wlb-hub-revoke --user <konto>` | VM | odwołuje ciasteczka i tokeny konta, zatrzymuje jego serwer (zamyka połączenia); hub restartuje się na kilka sekund |
| Odebranie roli / blokada w Entra | Entra | blokuje **następne** logowanie; nie dotyka trwającej sesji |

Pełne odcięcie osoby: usunięcie wiersza, potem `wlb-hub-revoke --user <konto>` (narzędzie kończy się kodem 0
dopiero po zapisaniu odwołania w bazie huba), a w Entra odebranie roli. Kolejność ma znaczenie: bez usunięcia
wiersza osoba zaloguje się ponownie. Konta odebranego **nie** przekazuje się innej osobie: jej logowanie
zostanie zablokowane przez powiązanie (procedura przekazania to #102 D3).

## 7. Diagnoza (`journalctl -u jupyterhub`)

Wpisy mają postać `WLB Entra: kod=<KOD> [oid=…|konto=<skrót>] [szczegół]`. Skrót konta dla znanego loginu:
`printf %s u01 | sha256sum | cut -c1-12`.

| Kod | Przyczyna |
|---|---|
| `BRAK_PRZYPISANIA` (oid) | brak wiersza w rejestrze dla tej osoby |
| `BRAK_ROLI` (oid) | osoba nie ma roli Laboratorium w Entra albo ma rolę innego Laboratorium |
| `TOKEN_ODRZUCONY` | `oid`: brak claimu (zakres `profile`?); `tid`/`iss`/`aud`: inny tenant lub aplikacja; `exp`: przeterminowany token lub zegar VM (NTP) |
| `KONTO_INNEJ_OSOBY` (oid) | rejestr wskazuje nową osobę na koncie powiązanym z kimś innym; przydziel wolne konto |
| `PRZYPISANIE_ZMIENIONE` (oid) | rejestr zmienił się w trakcie logowania; zaloguj ponownie |
| `REJESTR_NIEPOPRAWNY` | błąd w rejestrze, szczegóły w tym samym wpisie; nikt nie wejdzie do czasu poprawki |
| `POWIAZANIA_BRAK` | brak `/workspace/.wlb-hub/entra-bindings` — patrz niżej; logowanie i odświeżanie wstrzymane |
| `POWIAZANIA_NIECZYTELNE` / `POWIAZANIA_ZAPIS` | uszkodzony plik powiązań albo brak miejsca/praw przy zapisie; logowanie wstrzymane |
| `POWIAZANO` (konto, INFO) | pierwsze logowanie Entra na konto |
| `SESJA_ODRZUCONA` (konto, INFO) | żądanie sesji konta bez wiersza w rejestrze albo bez powiązania |
| `BRAK_KONFIGURACJI_ROLI` | brak `required_role` w konfiguracji |

**Brak pliku powiązań.** `wlb-firstboot` w trybie entra odmawia pracy, jeśli w poprzednim przebiegu Laboratorium
też było w trybie entra, a pliku nie ma. Pusty plik pozwoliłby następcy przejąć konto, którego poświadczenia nie
zostały odwołane. Do wyboru:
1. **Odtworzenie** pliku z kopii dysku roboczego **razem z bazą huba** (ten sam punkt w czasie). Kopia samej bazy
   (`wlb-hub-db-backup`) nie zawiera powiązań.
2. **Świadoma reinicjalizacja:** `sudo WLB_ENTRA_REINIT=1 wlb-firstboot --force`. Odwołuje poświadczenia wszystkich
   kont, a stary plik (jeśli jest) zachowuje jako `entra-bindings.przed-reinit-<data>`. Pierwsze logowanie każdej
   osoby wiąże jej konto na nowo, zgodnie z bieżącym rejestrem. Przed reinicjalizacją sprawdź rejestr wobec
   rejestru organizacyjnego, bo przypisania wejdą w życie bez historii.

## Ograniczenia i odbiór

- **Testy w repozytorium:**
  - authenticator: testy modułowe z podstawioną odpowiedzią punktu `token` (`tests/unit/test_wlb_entra.py`,
    także na oauthenticatorze zainstalowanym przez TLJH w `tests/acceptance.d/68-entra.sh`);
  - odwołanie poświadczeń: na prawdziwej bazie JupyterHub (`tests/unit/test_wlb_hub_revoke.py`) i przez
    działający hub na VM: ciasteczko, token API i serwer konta przed i po `wlb-hub-revoke` (etap 5, `68-entra.sh`).

  Nie są testowane: callback z `state` i PKCE na prawdziwym IdP, polityka Conditional Access i pełny przepływ
  logowania Entra przez przeglądarkę. Lista scenariuszy odbioru jest w IMG-011.
- Podpis id_token nie jest weryfikowany lokalnie, tak jak w `AzureAdOAuthenticator`. Przyjmujemy zaufanie
  do kanału zwrotnego: token pochodzi bezpośrednio z punktu `token` Entra po TLS. Hub sprawdza tenant,
  issuer, audience i ważność. To założenie zaufania wymaga oceny przy odbiorze.
- Odebranie roli lub blokada w Entra nie kończy trwającej sesji. Hub nie wymienia tokenów z Entra po zalogowaniu
  i nie obsługuje CAE.
- Odtworzenie dysku roboczego z kopii cofa razem bazę huba i powiązania. Rejestr z `/etc/wlb` może być
  nowszy, więc po odtworzeniu sprawdź rejestr wobec rejestru organizacyjnego.
- `AUTH_MODE=oidc` (inny IdP) nie ma rejestru ani powiązań: usunięcie z grupy działa od następnego logowania.
