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
Przyczyna trafia do dziennika huba z `oid`. `oid` to pseudonim osoby, czyli dana osobowa w rozumieniu RODO,
ale bez imienia, UPN ani e-maila. `allow_all`, `allowed_users` ani uprawnienia administratora nie omijają
tych warunków. Hub prosi o zakresy `openid profile`, bo Entra wysyła `oid` dopiero z `profile`. Imię i UPN
z tego zakresu są odrzucane zaraz po odczycie tokenu.

**Konto raz powiązane z osobą nie przechodzi na inną.** Pierwsze udane logowanie zapisuje trwałe
powiązanie konta z `(tid, oid)` w `/workspace/.wlb-hub/entra-bindings` (obok bazy huba, root, `0600`).
Jeśli rejestr później wskaże na tym koncie inną osobę, jej logowanie zostanie odrzucone. Bezpieczne
przekazanie konta wymaga odwołania poświadczeń poprzedniej osoby (#102 D3), a takiej procedury jeszcze nie ma.
Nowej osobie przydziel wolne konto `uNN`.

**Co robi zmiana rejestru, a czego nie robi.** Zmiana rejestru blokuje nowe logowania i żądania do huba
podlegające odświeżeniu: ciasteczko lub token API starsze niż `auth_refresh_age` (5 min) oraz start serwera.
Taka zmiana **nie** jest trwałym odwołaniem poświadczeń. Nie usuwa ciasteczek ani tokenów z bazy huba
i nie zamyka trwających połączeń z serwerem badacza (notebook, terminal, noVNC), które mają własną pamięć
podręczną uwierzytelnienia. Pełne odcięcie wymaga zatrzymania serwera (punkt 6).

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

1. **Okno serwisowe.** Uprzedź badaczy i poproś o zapisanie pracy. W panelu huba **zatrzymaj wszystkie
   serwery**, co zamyka trwające połączenia. Sesje zalogowane hasłem nie mają powiązania z Entra, więc
   po przełączeniu są odrzucane przy odświeżeniu, ale ich poświadczenia pozostają w bazie huba.
2. W Entra przypisz osoby do roli Laboratorium (punkt 1.4) i odczytaj ich `oid`.
   Każdą osobę przypisz do konta, którego **dotąd używała**. Nowym osobom przydziel wolne konta.
3. Zapisz rejestr: `sudo install -m 0600 -o root -g root entra-accounts /etc/wlb/entra-accounts` i sprawdź go (punkt 2).
4. W `/etc/wlb/lab.env` ustaw `AUTH_MODE=entra` i zmienne z punktu 3 (zachowaj kopię poprzedniego pliku).
5. `sudo wlb-firstboot --force`. Przebieg na krótko zamyka port huba. Konta, dane i hasła Native się nie zmieniają.
6. Weryfikacja:
   - strona logowania pokazuje „Sign in with Microsoft Entra ID”,
   - logowanie testowe konta z rejestru kończy się sukcesem i MFA zostaje wymuszone (log logowań Entra),
   - osoba bez roli albo bez wpisu dostaje odmowę,
   - `sudo journalctl -u jupyterhub | grep 'WLB Entra'` pokazuje przyczyny odmów (tylko `oid`).
7. Gdy produkcyjne Laboratoria aktualizują się automatycznie z `labEnv`, dopisz te zmienne i rejestr do seeda.
   Kroki 1–2 i 6 wykonaj tak samo przy wymianie obrazu.

## 5. Powrót do haseł (rollback)

1. **Najpierw** zresetuj hasła Native kont, którym w międzyczasie odebrano dostęp (`sudo wlb-hub-user <konto>`).
   Bez tego osoba usunięta z rejestru odzyska dostęp starym hasłem.
2. W `/etc/wlb/lab.env` ustaw `AUTH_MODE=native` (lub przywróć kopię) i uruchom `sudo wlb-firstboot --force`.
   Plik `70-wlb-auth.py` zostaje usunięty i hub wraca do Native Authenticatora.
3. Badacze logują się dotychczasowymi hasłami albo nowymi, wydanymi w kroku 1.

Rejestr i powiązania można zostawić, bo w trybie `native` nie są używane. Ponowne przejście na `entra`
korzysta z tych samych powiązań. Hasła Native usuwa się osobnym krokiem, po odbiorze Entra (#18).

## 6. Odebranie dostępu

| Co | Gdzie | Efekt |
|---|---|---|
| Usunięcie wiersza z rejestru | `/etc/wlb/entra-accounts` | blokuje nowe logowania oraz żądania do huba podlegające odświeżeniu (ciasteczko/token API po 5 min, start serwera) |
| Zatrzymanie serwera konta | panel huba | zamyka trwające połączenia notebooka, terminala i noVNC |
| Odebranie roli / blokada w Entra | Entra | blokuje **następne** logowanie; nie dotyka trwającej sesji |

Pełne odcięcie osoby to wszystkie trzy kroki: usunięcie wiersza, zatrzymanie serwera i odebranie roli.
Nie ma tu gwarantowanego czasu odwołania wszystkich poświadczeń. Procedura z potwierdzeniem odwołania
(ciasteczka, tokeny API i OAuth serwera) to zakres #102 D3. Do jej wdrożenia konta odebranego **nie**
przekazuje się innej osobie: jej logowanie i tak zostanie zablokowane (punkt „Jak to działa”).

## 7. Diagnoza (`journalctl -u jupyterhub`)

| Komunikat | Przyczyna |
|---|---|
| `brak przypisania konta dla oid=…` | brak wiersza w rejestrze dla tej osoby |
| `oid=… (konto …) bez roli aplikacji …` | osoba nie ma roli Laboratorium w Entra albo ma rolę innego Laboratorium |
| `odrzucony id_token (niezgodne: …)` | `oid`: brak claimu (zakres `profile`?); `tid`/`iss`/`aud`: inny tenant lub aplikacja; `exp`: przeterminowany token lub zegar VM (NTP) |
| `konto … powiązane z inną osobą — przekazanie konta wymaga procedury #102 D3` | rejestr wskazuje nową osobę na koncie używanym wcześniej przez kogoś innego; przydziel wolne konto |
| `rejestr przypisań niepoprawny, logowanie wstrzymane` | błąd w rejestrze, szczegóły w tym samym wpisie; nikt nie wejdzie do czasu poprawki |
| `nieczytelne powiązania …` / `niepoprawny format …` | uszkodzony `/workspace/.wlb-hub/entra-bindings`; logowanie wstrzymane, przywróć z kopii dysku roboczego |
| `konto … bez ważnego przypisania w rejestrze — żądanie odrzucone` (INFO) | żądanie sesji usuniętego z rejestru konta albo sesji sprzed migracji |

## Ograniczenia i odbiór

- **Testy w repozytorium to testy modułowe authenticatora** z podstawioną odpowiedzią punktu `token`
  (`tests/unit/test_wlb_entra.py`, `tests/acceptance.d/68-entra.sh` na oauthenticatorze zainstalowanym przez TLJH).
  Callback, `state` i PKCE, polityka Conditional Access, sesje HTTP i WebSocket wymagają osobnych testów
  integracyjnych z tenantem testowym. Lista scenariuszy odbioru jest w IMG-011.
- Podpis id_token nie jest weryfikowany lokalnie, tak jak w `AzureAdOAuthenticator`. Przyjmujemy zaufanie
  do kanału zwrotnego: token pochodzi bezpośrednio z punktu `token` Entra po TLS. Hub sprawdza tenant,
  issuer, audience i ważność. To założenie zaufania wymaga oceny przy odbiorze.
- Odebranie roli lub blokada w Entra nie kończy trwającej sesji. Hub nie wymienia tokenów z Entra po zalogowaniu
  i nie obsługuje CAE.
- Odtworzenie dysku roboczego z kopii cofa razem bazę huba i powiązania. Rejestr z `/etc/wlb` może być
  nowszy, więc po odtworzeniu sprawdź rejestr wobec rejestru organizacyjnego.
- `AUTH_MODE=oidc` (inny IdP) nie ma rejestru ani powiązań: usunięcie z grupy działa od następnego logowania.
