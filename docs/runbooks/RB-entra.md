# RB-entra: logowanie przez Microsoft Entra ID (`AUTH_MODE=entra`)

**Dotyczy:** #18 (IdP + MFA), #102 (D4: mapowanie tożsamości na konto) · **Moduły:** `/opt/wlb/hub/wlb_entra_auth.py`,
`/opt/wlb/hub/wlb_entra_accounts.py` · **Decyzja:** [IMG-011](../adr/IMG-011-logowanie-entra-id.md) · **Konfiguracja:** `/etc/wlb/lab.env`, `/etc/wlb/entra-accounts`

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
Przyczyna trafia do dziennika huba z `oid`, który jest pseudonimem osoby (dane osobowe w rozumieniu RODO,
ale bez imienia, UPN ani e-maila). `allow_all`, `allowed_users` ani uprawnienia administratora nie
omijają tych warunków.

**Sesja jest związana z osobą.** Po udanym logowaniu hub zapisuje w `/var/lib/wlb/entra-logins`
(root, `0600`), która para `(tid, oid)` zalogowała się na konto. Co 5 minut (`auth_refresh_age`), dla
tokenów API i przed startem serwera porównuje ten zapis z rejestrem. Sesja i tokeny kończą się, gdy:
- wiersz konta zniknie z rejestru,
- konto przejmie inna osoba,
- sesja nie pochodzi z logowania Entra (np. zalogowana hasłem przed migracją).

**Konta się nie zmieniają.** Konto systemowe `jupyter-<konto>`, UID, katalog `/workspace/jupyter-<konto>`,
baza huba i rola Administratora Klienta (`a01`, IMG-003) są te same co przy logowaniu hasłem. Rejestr
może wskazywać również stare konto nazwane (sprzed IMG-002), więc przejście na Entra nie wymaga
przenoszenia danych. Hasła Native zostają w bazie huba, dzięki czemu można wrócić do logowania hasłem.

## 1. Rejestracja aplikacji w Entra (raz na Laboratorium albo raz dla platformy)

Wykonuje administrator Entra GUMed:

1. **App registrations → New registration:** konta tylko z tego katalogu (single tenant).
   Redirect URI typu *Web*: `https://<nazwa-portalu-lab>/hub/oauth_callback`, czyli dokładnie `OIDC_CALLBACK_URL`.
2. **Certificates & secrets:** sekret klienta. Przekaż go wyłącznie przez menedżer sekretów (`OIDC_CLIENT_SECRET`).
3. **App roles → Create app role:** typ *Users/Groups*, wartość np. `WLB.Lab.<LAB_NAME>`, czyli `ENTRA_REQUIRED_ROLE`.
   Każde Laboratorium ma osobną rolę, więc jedna rejestracja może obsłużyć kilka Laboratoriów.
4. **Enterprise applications → (aplikacja) → Properties:** *Assignment required = Yes*. Token dostaną
   tylko osoby i grupy przypisane do roli. **Users and groups:** przypisz badaczy lub grupę Laboratorium do roli.
5. **Conditional Access:** polityka MFA obejmująca tę aplikację (wymóg §6).
6. Nie trzeba dodawać claimów opcjonalnych. `oid`, `tid` i `roles` są w id_token v2.0. Hub prosi
   wyłącznie o zakres `openid`, więc nie dostaje imienia ani adresu e-mail.

Badacze spoza GUMed: zaproszenie B2B (gość w tenancie GUMed). Gość ma własny `oid` w tym tenancie i wpisuje
się go do rejestru tak samo.

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
- Hub czyta rejestr przy każdym logowaniu, więc zmiany **nie wymagają restartu**. Usunięcie wiersza
  wylogowuje konto najpóźniej po 5 minutach (`auth_refresh_age`), a także przed startem serwera.
- Rejestr przypisań z datami i historią (kto, kiedy, na podstawie czego) prowadzi się poza VM (#102).
  Ten plik zawiera tylko bieżący stan potrzebny do logowania.

## 3. Nowe Laboratorium

Wzór: [`cloud-init/examples/lab-user-data-entra.yaml`](../../cloud-init/examples/lab-user-data-entra.yaml).
Do `lab.env` dodaj `AUTH_MODE=entra`, `ENTRA_TENANT_ID`, `ENTRA_REQUIRED_ROLE`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET` i `OIDC_CALLBACK_URL`. Rejestr dostarcz jako osobny plik `write_files`.

`wlb-firstboot` sprawdza konfigurację **przed** jakąkolwiek zmianą na VM. Brakująca zmienna, tenant
w złym formacie, callback bez `https://…/hub/oauth_callback`, brak rejestru, rejestr dostępny dla
innych niż root albo błędny rejestr przerywa uruchomienie.

Konta `a01` i `u01…uNN` powstają jak dotąd, również z hasłami Native, które służą jako droga powrotu.
Hasłami nie trzeba się dzielić z badaczami.

## 4. Migracja działającego Laboratorium (native → entra)

Warunki: działający TLS huba (`HUB_TLS=1`) z nazwą zgodną z `OIDC_CALLBACK_URL` oraz dostęp huba do
`https://login.microsoftonline.com` (sprawdź: `sudo curl -sSI https://login.microsoftonline.com | head -1`).
Zapora WLB ogranicza ruch wychodzący tylko kontom badaczy. Jeśli sieć Laboratorium wymaga proxy, ustal to
z zespołem sieci przed migracją.

1. **Okno serwisowe.** Uprzedź badaczy i zatrzymaj ich serwery w panelu huba. Sesje zalogowane hasłem
   kończą się same w ciągu 5 minut od przełączenia, bo nie mają zapisu logowania Entra. Badacz loguje się
   wtedy ponownie, już przez Entra.
2. W Entra przypisz osoby do roli Laboratorium (punkt 1.4) i odczytaj ich `oid`.
3. Zapisz rejestr: `sudo install -m 0600 -o root -g root entra-accounts /etc/wlb/entra-accounts` i sprawdź go (punkt 2).
4. W `/etc/wlb/lab.env` ustaw `AUTH_MODE=entra` i zmienne z punktu 3 (zachowaj kopię poprzedniego pliku).
5. `sudo wlb-firstboot --force`. Przebieg na krótko zamyka port huba. Konta, dane i hasła Native się nie zmieniają.
6. Weryfikacja:
   - strona logowania pokazuje „Sign in with Microsoft Entra ID”,
   - logowanie testowe konta z rejestru kończy się sukcesem,
   - osoba bez roli albo bez wpisu dostaje odmowę,
   - `sudo journalctl -u jupyterhub | grep 'WLB Entra'` pokazuje przyczyny odmów (tylko `oid`).
7. Gdy produkcyjne Laboratoria aktualizują się automatycznie z `labEnv`, wystarczy dopisać te zmienne
   i rejestr do seeda. Przełączenie nastąpi przy najbliższej wymianie obrazu (pierwszy start = `wlb-firstboot`).

**Przejęcie konta przez inną osobę** (#102 D3): zatrzymaj serwer konta w panelu huba, podmień `oid`
w wierszu rejestru i odbierz poprzedniej osobie rolę w Entra. Sesja i tokeny API poprzedniej osoby wygasają
w ciągu 5 minut, bo zapisany `oid` przestaje się zgadzać z rejestrem. Pliki w `/workspace/jupyter-<konto>`
zostają na koncie: ich rozliczenie i ślad w rejestrze organizacyjnym to zakres #102.

## 5. Powrót do haseł (rollback)

1. W `/etc/wlb/lab.env` ustaw `AUTH_MODE=native` (lub przywróć kopię).
2. `sudo wlb-firstboot --force`. Plik `70-wlb-auth.py` zostaje usunięty i hub wraca do Native Authenticatora.
3. Badacze logują się dotychczasowymi hasłami. Jeśli hasło nie jest znane, Administrator platformy ustawia
   nowe przez `wlb-hub-user <konto>`.

Rejestr można zostawić na VM, bo w trybie `native` nie jest używany. Hasła Native usuwa się osobnym krokiem,
dopiero po odbiorze Entra (#18).

## 6. Odebranie dostępu

| Co | Gdzie | Kiedy zadziała |
|---|---|---|
| **Usunięcie wiersza z rejestru** (zalecane) | `/etc/wlb/entra-accounts` | od razu dla nowych logowań; trwające sesje i tokeny API do 5 min |
| Natychmiast | panel huba: zatrzymaj serwer konta + usunięcie wiersza | od razu |
| Odebranie roli aplikacji | Entra (Users and groups) | **tylko przy następnym logowaniu**; trwająca sesja i tokeny API zostają |
| Blokada konta Entra | Entra (Block sign-in) | jak odebranie roli |

Hub nie wymienia tokenów z Entra po zalogowaniu, więc nie widzi bieżących ról. Zmiany w Entra działają
od następnego logowania. Aby odciąć osobę od razu, usuń jej wiersz z rejestru.

## 7. Diagnoza (`journalctl -u jupyterhub`)

| Komunikat | Przyczyna |
|---|---|
| `brak przypisania konta dla oid=…` | brak wiersza w rejestrze dla tej osoby |
| `oid=… (konto …) bez roli aplikacji …` | osoba nie ma roli Laboratorium w Entra albo ma rolę innego Laboratorium |
| `odrzucony id_token (niezgodne: tid/iss/aud/exp)` | token z innego tenantu lub aplikacji albo przeterminowany; sprawdź `ENTRA_TENANT_ID`, `OIDC_CLIENT_ID`, zegar VM (NTP) |
| `rejestr przypisań niepoprawny, logowanie wstrzymane` | błąd w rejestrze, szczegóły w tym samym wpisie; nikt nie wejdzie do czasu poprawki |
| `konto … nie jest przypisane do oid=…` | rejestr zmienił się w trakcie logowania (przejęcie konta); zaloguj ponownie |
| `sesja konta … nieaktualna wobec rejestru` (INFO) | sesja zakończona: wiersz usunięty, konto przejęte albo sesja sprzed migracji |
| `nie można zapisać /var/lib/wlb/entra-logins` | brak katalogu lub miejsca; logowanie odmawia (fail-secure) |

## Ograniczenia

- Brak testu z prawdziwym tenantem w CI. Obraz sprawdza moduły na zainstalowanym oauthenticatorze
  (`tests/acceptance.d/68-entra.sh`), a pełny przebieg logowania jest testowany z podmienioną wymianą tokenu.
- Podpis id_token nie jest weryfikowany lokalnie, tak jak w `AzureAdOAuthenticator`. Token pochodzi
  bezpośrednio z punktu `token` Entra po TLS, a hub sprawdza tenant, issuer, audience i ważność.
- Odebranie roli lub blokada w Entra nie kończy trwającej sesji (punkt 6). Natychmiastowe odcięcie
  zapewnia usunięcie wiersza z rejestru.
- `AUTH_MODE=oidc` (inny IdP) ma to samo ograniczenie dla grup: usunięcie z grupy działa od następnego
  logowania, a tryb nie ma rejestru, którym dałoby się odciąć osobę od razu.
- Rejestr organizacyjny z datami, właściciel danych (IOD) i pełna procedura przejęcia konta pozostają w #102.
