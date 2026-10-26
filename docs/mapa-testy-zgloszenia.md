# Mapa: zgłoszenie → test

Dokument śledzi, które testy pilnują rozwiązania z poszczególnych zgłoszeń, żeby po każdym PR było widać, że **stare i nowe funkcjonalności nadal działają** (wymóg regresji dla Tier 4, DoD #46/#52). Zasada: patrz [CONTRIBUTING.md](../CONTRIBUTING.md) — „każda poprawka = test regresji”.

_Wygenerowano skryptem `ci/mapa-testy.py` z drzewa `tests/` (2026-10-21). Odśwież: `python3 ci/mapa-testy.py`._

## Pokrycie wg zgłoszeń

### #4 — Kolejka eksportu na jednorazowym dysku systemowym — utrata wniosków przy wymianie obrazu  ·  _scalone_
- `tests/acceptance-remote.sh` — `Badacz nie ma dostępu do kolejki`
- `tests/migration-remote.sh` — `Wniosek o eksport z poprzedniej VM jest w kolejce (#4)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #5 — Synchronizacja czasu: chrony korzysta z publicznych serwerów NTP niedostępnych w sieci Laboratorium  ·  _scalone_
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #6 — Logi do SIEM wysyłane bez szyfrowania — TLS dla rsyslog  ·  _scalone_
- `tests/acceptance-remote.sh` — `Moduł TLS rsyslog zainstalowany (lmnsd_gtls, #6)`, `Przekazywanie do SIEM skonfigurowane`, `SIEM po TLS z weryfikacją nazwy serwera (#6)`, `rsyslog bez błędów TLS (moduł, nazwa i zaufanie certyfikatu, #6)`, `rsyslog bez odmów AppArmor (#44, #6)`
- `tests/acceptance.d/20-apparmor.sh` — `Profil rsyslogd w trybie enforce (#6)`, `Profil rsyslogd nie jest w trybie complain (#6)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`, *TLS do SIEM (#6)*

### #7 — Blokada pobierania plików z JupyterLab na urządzenia badaczy (§24.e, częściowo)  ·  _scalone_
- `tests/acceptance-remote.sh` — *5a. Blokada pobierania plików na urządzenie badacza (#7, §14, §24.e — środek częściowy)*

### #8 — Spójna kopia bazy huba (SQLite) przed snapshotem storage  ·  _scalone_
- `tests/acceptance-remote.sh` — `Hub działa po odtworzeniu z kopii (#8)`, `Kopia bazy huba wykonana na żądanie (#8)`, `Kopia spójna (integrity_check, #8)`, `Kopia tylko dla roota (0600, #8)`, `Kopia zawiera konta huba (#8)`, `Logowanie $R1 po odtworzeniu z kopii (konta i hasła działają, #8)`, `Timer kopii bazy huba włączony (#8)`, *9. Spójna kopia i odtworzenie bazy huba (#8)*, `Świeża kopia istnieje (#8)`

### #10 — Kalibracja budżetów wydajności — pierwszy przebieg etapu 6a  ·  _otwarte_
- `tests/unit/perf-helpers.bats` — `median: brak próbek zwraca błąd (#10)`, `median: jedna próbka (#10)`, `median: nieparzysta liczba próbek to wartość środkowa (#10)`, `median: parzysta liczba próbek — dolna środkowa (#10)`, `perf_vm_resources: bez wartości — czapka 4 vCPU / 8192 MB wyliczona z hosta (#10)`, `perf_vm_resources: respektuje podane VM_CPUS/VM_MEMORY (#10)`

### #12 — Proces wydania obrazu (12a): metadane, SBOM, changelog na tag (M2)  ·  _scalone_
- `tests/unit/release.bats` — `image_provenance: GITHUB_RUN_ID trafia do BUILD_RUN (#12)`, `image_provenance: commit, flaga dirty, build_run (#12)`, `release.sh: brak tagu przerywa (#12)`, `release.sh: zły format tagu przerywa (#12)`

### #13 — Runbooki operacyjne cyklu życia Laboratorium  ·  _otwarte_
- `tests/unit/wlb-hub-db-preupgrade.bats` — `brak image-release -> pre-unknown (#13)`, `druga próba tej samej wersji nie nadpisuje starej kopii (#13)`, `kopia pre-<wersja> powstaje, gdy baza istnieje (#13)`, `świeży dysk bez bazy -> brak kopii (#13)`

### #18 — Dostęp: MFA (Keycloak / Entra ID) i HTTPS przez portal WLB lub bramkę VDI  ·  _otwarte_
- `tests/unit/wlb-firstboot.bats` — *Uwierzytelnianie: native / OIDC (#18)*

### #29 — TOCTOU w śluzie wyjściowej: podmiana pliku na dowiązanie symboliczne przed przeniesieniem przez root  ·  _scalone_
- `tests/acceptance-remote.sh` — `Dowiązanie w /sluza-out odrzucone (#29)`, `Kolejka eksportu na dysku roboczym`, `Prawa /etc/passwd bez zmian (#29)`, `W kolejce nie ma dowiązań ani plików specjalnych (#29)`
- `tests/unit/wlb-sluza-out-mover.bats` — `#29: dowiązania i pliki specjalne wewnątrz katalogu są usuwane, reszta eksportowana`, `#29: dwa wpisy o tej samej nazwie w tej samej sekundzie nie nadpisują się`, `#29: plik podmieniony na dowiązanie po sprawdzeniu — cel nietknięty, kolejka pusta`, `#29: plik z drugim dowiązaniem twardym jest odrzucany, oryginał badacza zostaje`, `#29: wpis usunięty przez badacza w trakcie przeglądu nie zatrzymuje usługi`, *#29: podmiana wpisu między sprawdzeniem a przeniesieniem (TOCTOU)*

### #30 — Limity zasobów na badacza (pamięć, CPU, liczba procesów) i ochrona usług systemowych przed OOM  ·  _scalone_
- `tests/acceptance-remote.sh` — *7b. Limity zasobów badaczy (#30)*
- `tests/unit/wlb-firstboot.bats` — *Limity zasobów badaczy (#30)*

### #31 — wlb-hub-user: brak timeoutu blokady SQLite („database is locked” przy działającym hubie)  ·  _scalone_
- `tests/unit/test_wlb_hub_user.py` — *Blokada zapisu SQLite przy działającym hubie (#31)*
- `tests/unit/wlb-firstboot.bats` — `konto huba: trwała blokada bazy przerywa firstboot czytelnym błędem (#31)`

### #33 — Niedokończone eksporty: śluza może przenieść plik zapisywany w kilku otwarciach  ·  _otwarte_
- `tests/unit/wlb-sluza-out-mover.bats` — `plik tymczasowy po zmianie nazwy na docelową trafia do kolejki (#33)`, `pliki tymczasowe/ukryte są pomijane do zmiany nazwy (#33)`

### #35 — Telemetria CI: walidacja OTLP/JSON oficjalnym schematem w testach  ·  _otwarte_
- `tests/unit/test_ci_telemetry.py` — *#35: walidacja trzech sygnałów oficjalnym schematem OTLP + semantyka*, *Walidacja OTLP/JSON oficjalnym schematem (#35)*

### #36 — Test akceptacyjny: faktyczna synchronizacja czasu z NTP_SERVERS  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Brak publicznych serwerów NTP`, `Synchronizacja NTP — brak testowego serwera NTP na hoście (wymaga sudo, #36)`, `chrony zsynchronizowany z NTP_SERVERS (#36)`

### #44 — SIEM: badacz może fałszować zdarzenia z kontraktu (logger z tagiem wlb-*) — pola zaufane z journald  ·  _scalone_
- `tests/acceptance-remote.sh` — `Reguły audytu zablokowane (-e 2)`, `Wpis podrobiony przez badacza ma w journald jego UID (#44)`, `rsyslog bez odmów AppArmor (#44, #6)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #50 — Wspólny katalog projektu dla członków zespołu (§10 Regulaminu)  ·  _otwarte_
- `tests/acceptance-remote.sh` — *1a. Wspólny katalog projektu (§10, #50)*

### #53 — Logo IP_CMC na stronie logowania i w nagłówku huba  ·  _scalone_
- `tests/acceptance-remote.sh` — `Logo na stronie logowania wskazuje /hub/logo (#53)`, `Logo to przesłany plik PNG IP_CMC (#53)`, `Nazwa platformy na stronie logowania (#53)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*

### #54 — Kafelek „Pomoc i zgłoszenia” (helpdesk) w Launcherze JupyterLab  ·  _scalone_
- `tests/acceptance-remote.sh` — `Kafelek pomocy w konfiguracji Launchera (#54)`, `Strona pomocy z kontaktem helpdesku (#54)`, `jupyter-app-launcher zainstalowany (#54)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*

### #62 — SSH: Limity logowania i komunikat powitalny (CIS 5.2)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Baner nie ujawnia wersji systemu (#62)`, `Baner prawny o monitoringu (#62)`, `Banner /etc/issue.net (#62)`, `LogLevel VERBOSE (#62)`, `LoginGraceTime 60 (#62)`, `MaxAuthTries 4 (#62)`, `MaxSessions 4 (#62)`, `MaxStartups 10:30:60 (#62)`, `PermitUserEnvironment no (#62)`, *10. Utwardzenie SSH (CIS 5.2, #62)*
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #65 — AppArmor: apparmor-utils, apparmor=1 w GRUB i profile w trybie complain (CIS 1.6)  ·  _otwarte_
- `tests/acceptance.d/20-apparmor.sh` — *AppArmor (CIS 1.6, #65)*: `apparmor=1` i `security=apparmor` w `/proc/cmdline`, dropin GRUB `60-wlb-apparmor.cfg` (brak starego `50-`), `apparmor-utils` w PATH, licznik profili w complain = 0 i pusta lista profili complain (CIS 1.6.3)

### #66 — Reguły audytu: konta, czas, moduły, sesje, AppArmor (podstawa §21/OPZ B.21)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Audyt: zmiana MAC/AppArmor (#66)`, `Audyt: zmiana konta/PAM (#66)`, *8. Logi i audyt*

### #86 — CI: etap 5/6a rzadziej lub lokalnie — bramkowanie weryfikacji ciężkiej (do czasu self-hosted #25)  ·  _otwarte_
- `tests/unit/changes.bats` — `PR bez etykiet: etap 5/6 pominięty (#86)`, `PR z etykietą run-integration: etap 5 na żądanie (#86)`, `PR ze zmianą kodu obrazu, ale bez etykiety: nadal bez etapu 5 (#86)`

### #106 — Pulpit w przeglądarce: rola desktop + flavor wlb-memory (remote-desktop-proxy, kafelek „Pulpit”)  ·  _otwarte_
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #123 — Bramka etapu 1: nierozwiązane znaczniki konfliktu gita w plikach nielintowanych  ·  _otwarte_
- `tests/unit/test_conflict_markers.py` — *Bramka znacznikow konfliktu (#123)*

### #111 — Kernel Julia (luka vs strona JupyterHub IP_CMC)  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Kernel Julia (IJulia) zarejestrowany (#111)`, `Notebook Julia (IJulia, stdlib)`, *2. Notebook Python, R i Julia*

### #106 — Pulpit w przeglądarce (flavor wlb-memory) + regresja lekkości bazy (#105)  ·  _otwarte_
- `tests/acceptance-remote.sh` — sekcja *11*: na `wlb-memory` sprawdza XFCE/TigerVNC/websockify/schowek i `WLB_IMAGE_NAME`; na `wlb-general` pilnuje, że pulpit NIE wyciekł do bazy. Testy interaktywne (idle culler na noVNC, dziedziczenie OOMScoreAdjust) — runbook w #106.

### #97 — Hooki cyklu życia sesji badacza (pre/post-spawn) + korelacja sesji w SIEM  ·  _otwarte_
- `observability/contract.yml` — zdarzenia `session.start`, `session.stop` (tag `wlb-session`); pilnuje `tests/unit/test_observability_contract.py`.
- `tests/acceptance-remote.sh` — sekcja *11*: config hooka `80-wlb-session.py`, emiter `wlb-session-log` → journal.

### #98 — Raport użycia/pojemności sesji (sampler systemd + JSONL, osobno od SIEM)  ·  _otwarte_
- `tests/unit/wlb-usage-record.bats` — składanie rekordu JSONL (szczyt z próbki, zera przy braku, sanityzacja liczb).
- `tests/acceptance-remote.sh` — sekcja *12*: sampler/rekord wykonywalne, timer włączony, katalog 0750 niedostępny dla badacza, zapis JSONL.
## Uwagi

- **Mapa pokazuje testy z jawnym znacznikiem `#NN`.** Wiele zachowań jest pokrytych testami bez odwołania do zgłoszenia (pełny zestaw jednostkowy bats/pytest w `tests/unit/`, akceptacja e2e w `tests/acceptance-remote.sh`, migracja w `tests/migration-remote.sh`). Brak wiersza nie znaczy „brak testu”, lecz „brak znacznika” — przy nowych poprawkach dodawaj `#NN` w tytule/sekcji testu, aby trafił do mapy.
- **Dryf zamrożonych wersji** (np. `markupsafe`) pilnuje test dryfu w etapie 5 oraz nocny pełny build (harmonogram `CI`) — to również forma regresji, łapiąca zmiany spoza repozytorium, zanim uderzą w PR.

