# Przewodnik administratora: konta badaczy i administracja obrazem

Jak założyć i prowadzić konto badacza oraz jak administrować samym obrazem VM
Laboratorium. Opisuje **stan obecny** (MVP, Native Authenticator); model docelowy
kont bezosobowych `uNN` jest przyjęty w [IMG-002](adr/IMG-002-model-kont-badaczy.md),
ale **jeszcze niewdrożony** (#102).

Powiązane: [pierwsze uruchomienie obrazu](pierwsze-uruchomienie.md) ·
[RB-05 aktualizacja i rollback](runbooks/RB-05-aktualizacja-i-rollback.md) ·
[kopia bazy huba](runbook-kopia-bazy-huba.md) ·
[eksport/kolejka śluzy](runbooks/RB-eksport-kolejka.md).

## Dwie role administracyjne

| | Administrator Platformy (IP_CMC) | Administrator Klienta Środowiska WLB |
|---|---|---|
| Kto | zespół platformy / opiekun obrazu | wyznaczona osoba po stronie jednostki badawczej |
| Gdzie działa | buduje i wdraża obraz, SSH do VM, `lab.env` | panel huba w przeglądarce |
| Zakres | pełny nad obrazem i wdrożeniem | **ograniczony** (patrz [IMG-003](adr/IMG-003-zakres-admina-klienta.md)) |
| Konta badaczy | może zakładać z CLI (`wlb-hub-user`) | zatwierdza/zarządza w panelu huba |
| Dane badacza | brak wglądu w ramach procedury (poufność §26) | **nie wchodzi** do serwera badacza (`access:servers`, `tokens` odebrane) |

Administrator Klienta ma w hubie rolę ograniczoną: zatwierdzanie kont
(`admin:users`) i zarządzanie serwerami (`admin:servers`), **bez** `access:servers`
i `tokens`. Nie otworzy sesji badacza ani nie zadziała jego tokenem; pozostałe
ryzyka (zmiana hasła, eskalacja) są **wykrywane** i trafiają do SIEM przez kontrakt
obserwowalności. Uzasadnienie i macierz zagrożeń: [IMG-003](adr/IMG-003-zakres-admina-klienta.md).

---

# Część I — Konta badaczy

## Model kont (stan obecny)

- **Uwierzytelnianie:** Native Authenticator (MVP). `AUTH_MODE=native` w `lab.env`;
  przełączenie na OIDC (Entra ID / Keycloak, SSO+MFA) planowane (#18/#57).
- **Login:** `^[a-z0-9][a-z0-9._-]{0,31}$`, hasło min. 12 znaków, blokada po seriach
  nieudanych prób. Rejestracja otwarta jest wyłączona (`open_signup=False`) — każde
  konto wymaga zatwierdzenia.
- **Katalog domowy:** `/workspace/<login>`, prawa `0700`; badacz widzi tylko swoje pliki.
- **Model docelowy:** konta bezosobowe stanowiskowe `uNN` + rejestr osoba↔konto↔daty
  ([IMG-002](adr/IMG-002-model-kont-badaczy.md)) — **jeszcze nie wdrożony**; dziś konta są nazwane.

## Skąd bierze się Administrator Klienta (bootstrap)

Przy pierwszym starcie VM `wlb-firstboot` czyta `/etc/wlb/lab.env`, dodaje
`HUB_ADMIN_USER` do `users.admin` huba, zakłada to konto (idempotentnie,
`wlb-hub-user --if-missing`) i zapisuje **hasło początkowe** do
`/root/wlb-hub-admin-initial-password`.

- Na VM testowej hasło odczytasz: `make test-password`.
- Na wdrożeniu: Administrator Platformy pobiera je z pliku (SSH) i przekazuje
  Administratorowi Klienta kanałem bezpiecznym; przy pierwszym logowaniu należy je zmienić.

## Założenie konta badacza — dwie drogi

### A. Administrator Klienta w panelu huba (droga podstawowa)

1. Badacz (lub Administrator Klienta w jego imieniu) składa **wniosek o konto** na stronie
   logowania huba (formularz „Signup"; dostępny, gdy `tljh_enable_signup=1`).
2. Administrator Klienta wchodzi na **`/hub/authorize`**, weryfikuje i **zatwierdza** wniosek.
3. Od tej chwili badacz loguje się swoim loginem i hasłem; przy pierwszym logowaniu zmienia hasło.

> Gdy formularz wniosków jest wyłączony (`tljh_enable_signup=0`), konta zakłada wyłącznie
> Administrator Platformy drogą B.

### B. Administrator Platformy z CLI na VM (zakładanie/zasiew)

Narzędzie `wlb-hub-user` tworzy **od razu zatwierdzone** konto w bazie Native Authenticatora:

```bash
sudo wlb-hub-user u01                 # generuje hasło i wypisuje je na stdout
sudo wlb-hub-user u01 --password-stdin # hasło z pierwszej linii stdin (min. 12 znaków)
sudo wlb-hub-user u01 --if-missing     # tylko gdy konta nie ma (istniejące: bez zmian)
```

- Login jest walidowany; hasło wygenerowane losowo przekaż badaczowi bezpiecznym kanałem.
- Konto dostaje `is_authorized=True` — nie wymaga już zatwierdzenia w panelu.
- Uprawnień administratora **to narzędzie nie nadaje** — admina daje wyłącznie lista
  `users.admin` w konfiguracji huba (ustawiana z `HUB_ADMIN_USER`).
- Hub musi być uruchomiony co najmniej raz (baza musi istnieć). Baza huba leży na dysku
  roboczym: `sqlite:////workspace/.wlb-hub/jupyterhub.sqlite`.

## Reset hasła i przejęcie konta

Ponowne `sudo wlb-hub-user <login>` **resetuje hasło** i zatwierdza konto (tej samej
komendy użyj, gdy badacz zapomni hasła). W modelu docelowym `uNN` przejęcie konta
stanowiskowego przez nową osobę = reset poświadczeń + wpis do rejestru
(patrz [IMG-002](adr/IMG-002-model-kont-badaczy.md)).

## Co dostaje badacz i jakie są granice

- Python + R (IRkernel/HADES) + Julia (IJulia) w jednej sesji JupyterLab; `/data-mart` tylko do odczytu.
- **Sesja max 12 h** niezależnie od aktywności (culler + ciasteczko/tokeny 12 h); długie
  obliczenia — patrz pomoc w Launcherze i #78.
- **Śluza:** zapis do `/sluza-in` odrzucany; plik w `/sluza-out` znika z widoku i trafia do kolejki eksportu.
- **Instalacja pakietów:** zależnie od `RESEARCHER_PACKAGE_INSTALL` — `deny` (domyślnie)
  albo `mirror` (tylko kuratorowany mirror Laboratorium). Decyzja: [IMG-004](adr/IMG-004-instalacja-pakietow-badacz.md).
- **Brak sudo** w sesji badacza (NoNewPrivileges); VM jest air-gapped (wyjście tylko przez proxy z allowlistą).

---

# Część II — Administracja obrazem

## Cykl życia: budowanie → test → wydanie

Wszystko przez `make` (pełna lista: `make help`). Szczegółowy pierwszy przebieg:
[pierwsze-uruchomienie.md](pierwsze-uruchomienie.md).

| Cel | Co robi |
|---|---|
| `make doctor` | sprawdza środowisko (repo, CRLF, KVM, narzędzia, miejsce, pamięć) |
| `make ci` | etapy 1–4 lokalnie (lint, build-check, bezpieczeństwo, obserwowalność, testy jednostkowe) — przed każdym pushem |
| `make build` | buduje **bazę** `wlb-general` → `output/<nazwa>-<wersja>-<data>/` |
| `make test-up` / `make test` / `make test-down` | uruchamia najnowszy obraz jako VM testową, odpala akceptację MVP, zatrzymuje |
| `make test-password` | hasło początkowe Administratora Klienta z działającej VM testowej |
| `make integration` | etap 5: build + akceptacja + migracja + dryf locków (KVM, ~1–2 h) |

**Flavory** budują się warstwowo na gotowej bazie (nie przez `make build`, który celowo
robi tylko bazę). Wzorzec i polecenia dla radiologii:
[RB-build-wlb-radiologia.md](runbooks/RB-build-wlb-radiologia.md). W skrócie — flavor nakłada
`base_image=<baza.qcow2>` szablonem `packer/` z `-only` właściwego źródła; bramka CI flavora
radiologia jest opt-in (`WLB_BUILD_RADIOLOGIA=1`, #167).

## Konfiguracja wdrożenia (`/etc/wlb/lab.env`)

Parametry Laboratorium dostarcza cloud-init (`write_files`); czyta je `wlb-firstboot`.
Wzorzec z opisem każdej zmiennej: [`cloud-init/lab.env.example`](../cloud-init/lab.env.example).
Najważniejsze:

| Zmienna | Rola |
|---|---|
| `LAB_NAME` | identyfikator Laboratorium (zgodny z hostname) |
| `HUB_ADMIN_USER` | **jedyny** administrator huba (Administrator Klienta) |
| `PROXY_URL` / `NO_PROXY` | proxy z allowlistą — jedyne wyjście z VM |
| `EGRESS_ALLOW` | adresy, z którymi procesy badaczy łączą się wprost (nftables, obrona w głębi) |
| `ADMIN_SSH_CIDR` | pojedyncza kanoniczna sieć źródłowa SSH administratora (#18) |
| `HUB_ALLOWED_CIDR` | skąd wolno łączyć się z hubem (portal/VDI) |
| `HUB_TLS` (+`_CERT`/`_KEY`) | TLS huba; `1` domyślnie (HTTPS/443). `0` tylko dev/izolowana sieć — dane RODO nie mogą iść jawnym tekstem |
| `NTP_SERVERS` | wewnętrzne serwery czasu |
| `AUTH_MODE` | `native` (MVP) albo `oidc` |
| `RESEARCHER_PACKAGE_INSTALL` | `deny` / `mirror` (IMG-004) |

Przy `HUB_TLS=1` firstboot **waliduje** certyfikat i klucz (para, ważność, prawa `0600`,
brak hasła) **przed** otwarciem portu — błędna konfiguracja nie wystawi huba po HTTP.
Rotacja certyfikatu / zmiana `lab.env`: podmień pliki i uruchom `sudo wlb-firstboot --force`
(przed blokadą audytu).

## Aktualizacja i wycofanie

Obraz jest niezmienny — aktualizacja to **podmiana qcow2**, dysk roboczy (dane badaczy,
baza huba) zostaje. Procedura w przód i rollback: [RB-05](runbooks/RB-05-aktualizacja-i-rollback.md).
Kopia bazy huba przed operacją: [runbook-kopia-bazy-huba.md](runbook-kopia-bazy-huba.md).

## Weryfikacja i codzienne operacje

- **Akceptacja:** `make test` po `make test-up`; testy to fragmenty w
  [`tests/acceptance.d/`](../tests/acceptance.d/) (adaptują się do flavora — np. `70-radiologia.sh`
  sprawdza stos neuro tylko na obrazie radiologicznym).
- **Logi/audyt:** auditd + journald → rsyslog → SIEM (`SIEM_HOST`). Kontrakt zdarzeń:
  [`observability/contract.yml`](../observability/contract.yml).
- **Panel huba:** lista i zarządzanie serwerami/kontami w zakresie roli Administratora Klienta.
- **Mapa testów ↔ zgłoszeń:** [docs/mapa-testy-zgloszenia.md](mapa-testy-zgloszenia.md).

---

## Checklista uruchomienia nowego Laboratorium

1. Przygotuj `lab.env` (z `cloud-init/lab.env.example`): `LAB_NAME`, `HUB_ADMIN_USER`, proxy,
   `EGRESS_ALLOW`, `ADMIN_SSH_CIDR`, `HUB_ALLOWED_CIDR`, TLS huba, NTP, `AUTH_MODE`, polityka pakietów.
2. Dostarcz certyfikat/klucz TLS huba przez cloud-init `write_files` (prawa `0600`).
3. Wdróż obraz; po pierwszym starcie sprawdź, że `wlb-firstboot` zakończył się bez błędu.
4. Pobierz hasło początkowe Administratora Klienta (`/root/wlb-hub-admin-initial-password`),
   przekaż bezpiecznym kanałem; wymuś zmianę przy pierwszym logowaniu.
5. Załóż konta badaczy (droga A w panelu albo B z `wlb-hub-user`) — liczba kont = liczba zatwierdzonych użytkowników.
6. Zweryfikuj akceptację i widoczność zdarzeń w SIEM.
