# Mapa: zgłoszenie → test

Dokument śledzi, które testy pilnują rozwiązania z poszczególnych zgłoszeń, żeby po każdym PR było widać, że **stare i nowe funkcjonalności nadal działają** (wymóg regresji dla Tier 4, DoD #46/#52). Zasada: patrz [CONTRIBUTING.md](../CONTRIBUTING.md) — „każda poprawka = test regresji”.

_Wygenerowano skryptem `ci/mapa-testy.py` z drzewa `tests/` (2026-10-26). Odśwież: `python3 ci/mapa-testy.py`._

## Pokrycie wg zgłoszeń

### #4 —   ·  _—_
- `tests/acceptance-remote.sh` — `Badacz nie ma dostępu do kolejki`
- `tests/migration-remote.sh` — `Wniosek o eksport z poprzedniej VM jest w kolejce (#4)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #5 —   ·  _—_
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #6 —   ·  _—_
- `tests/acceptance-remote.sh` — `Moduł TLS rsyslog zainstalowany (lmnsd_gtls, #6)`, `Przekazywanie do SIEM skonfigurowane`, `SIEM po TLS z weryfikacją nazwy serwera (#6)`, `rsyslog bez błędów TLS (moduł, nazwa i zaufanie certyfikatu, #6)`, `rsyslog bez odmów AppArmor (#44, #6)`
- `tests/acceptance.d/20-apparmor.sh` — `Profil rsyslogd w trybie enforce (#6)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`, *TLS do SIEM (#6)*

### #7 —   ·  _—_
- `tests/acceptance-remote.sh` — *5a. Blokada pobierania plików na urządzenie badacza (#7, §14, §24.e — środek częściowy)*

### #8 —   ·  _—_
- `tests/acceptance-remote.sh` — `Hub działa po odtworzeniu z kopii (#8)`, `Kopia bazy huba wykonana na żądanie (#8)`, `Kopia spójna (integrity_check, #8)`, `Kopia tylko dla roota (0600, #8)`, `Kopia zawiera konta huba (#8)`, `Logowanie $R1 po odtworzeniu z kopii (konta i hasła działają, #8)`, `Timer kopii bazy huba włączony (#8)`, *9. Spójna kopia i odtworzenie bazy huba (#8)*, `Świeża kopia istnieje (#8)`

### #9 —   ·  _—_
- `tests/acceptance.d/10-jedno-jadro.sh` — *Jedno jądro w obrazie (#9)*

### #10 —   ·  _—_
- `tests/unit/perf-helpers.bats` — `median: brak próbek zwraca błąd (#10)`, `median: jedna próbka (#10)`, `median: nieparzysta liczba próbek to wartość środkowa (#10)`, `median: parzysta liczba próbek — dolna środkowa (#10)`, `perf_vm_resources: bez wartości — czapka 4 vCPU / 8192 MB wyliczona z hosta (#10)`, `perf_vm_resources: respektuje podane VM_CPUS/VM_MEMORY (#10)`

### #12 —   ·  _—_
- `tests/unit/release.bats` — `image_provenance: GITHUB_RUN_ID trafia do BUILD_RUN (#12)`, `image_provenance: commit, flaga dirty, build_run (#12)`, `release.sh: brak tagu przerywa (#12)`, `release.sh: zły format tagu przerywa (#12)`

### #13 —   ·  _—_
- `tests/unit/wlb-hub-db-preupgrade.bats` — `brak image-release -> pre-unknown (#13)`, `druga próba tej samej wersji nie nadpisuje starej kopii (#13)`, `kopia pre-<wersja> powstaje, gdy baza istnieje (#13)`, `świeży dysk bez bazy -> brak kopii (#13)`

### #16 —   ·  _—_
- `tests/acceptance-remote.sh` — `Allowlista proxy (mirror PyPI/CRAN) — brak testowego proxy na hoście (#16)`, `CONNECT poza allowlistą: $target (403, #16, #63)`, `Reguły egress nftables załadowane`
- `tests/unit/changes.bats` — `PR i merge_group: sieć i harness wymagają KVM bez etykiety (#63, #16)`
- `tests/unit/test_network_gates.py` — `test_connect_denial_over_real_socket`, `test_connect_requires_explicit_proxy_denial`

### #18 —   ·  _—_
- `tests/unit/wlb-firstboot.bats` — *Uwierzytelnianie: native / OIDC (#18)*

### #29 —   ·  _—_
- `tests/acceptance-remote.sh` — `Dowiązanie w /sluza-out odrzucone (#29)`, `Kolejka eksportu na dysku roboczym`, `Prawa /etc/passwd bez zmian (#29)`, `W kolejce nie ma dowiązań ani plików specjalnych (#29)`
- `tests/unit/wlb-sluza-out-mover.bats` — `#29: dowiązania i pliki specjalne wewnątrz katalogu są usuwane, reszta eksportowana`, `#29: dwa wpisy o tej samej nazwie w tej samej sekundzie nie nadpisują się`, `#29: plik podmieniony na dowiązanie po sprawdzeniu — cel nietknięty, kolejka pusta`, `#29: plik z drugim dowiązaniem twardym jest odrzucany, oryginał badacza zostaje`, `#29: wpis usunięty przez badacza w trakcie przeglądu nie zatrzymuje usługi`, *#29: podmiana wpisu między sprawdzeniem a przeniesieniem (TOCTOU)*

### #30 —   ·  _—_
- `tests/acceptance-remote.sh` — *7b. Limity zasobów badaczy (#30)*
- `tests/unit/wlb-firstboot.bats` — *Limity zasobów badaczy (#30)*

### #31 —   ·  _—_
- `tests/unit/test_wlb_hub_user.py` — *Blokada zapisu SQLite przy działającym hubie (#31)*
- `tests/unit/wlb-firstboot.bats` — `konto huba: trwała blokada bazy przerywa firstboot czytelnym błędem (#31)`

### #33 —   ·  _—_
- `tests/unit/wlb-sluza-out-mover.bats` — `plik tymczasowy po zmianie nazwy na docelową trafia do kolejki (#33)`, `pliki tymczasowe/ukryte są pomijane do zmiany nazwy (#33)`

### #35 —   ·  _—_
- `tests/unit/test_ci_telemetry.py` — *#35: walidacja trzech sygnałów oficjalnym schematem OTLP + semantyka*, *Walidacja OTLP/JSON oficjalnym schematem (#35)*

### #36 —   ·  _—_
- `tests/acceptance-remote.sh` — `Brak publicznych serwerów NTP`, `Synchronizacja NTP — brak testowego serwera NTP na hoście (wymaga sudo, #36)`, `chrony zsynchronizowany z NTP_SERVERS (#36)`

### #44 —   ·  _—_
- `tests/acceptance-remote.sh` — `Reguły audytu zablokowane (-e 2)`, `Wpis podrobiony przez badacza ma w journald jego UID (#44)`, `rsyslog bez odmów AppArmor (#44, #6)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #53 —   ·  _—_
- `tests/acceptance-remote.sh` — `Logo na stronie logowania wskazuje /hub/logo (#53)`, `Logo to przesłany plik PNG IP_CMC (#53)`, `Nazwa platformy na stronie logowania (#53)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*

### #54 —   ·  _—_
- `tests/acceptance-remote.sh` — `Kafelek pomocy w konfiguracji Launchera (#54)`, `Strona pomocy z kontaktem helpdesku (#54)`, `jupyter-app-launcher zainstalowany (#54)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*

### #62 —   ·  _—_
- `tests/acceptance-remote.sh` — `Baner nie ujawnia wersji systemu (#62)`, `Baner prawny o monitoringu (#62)`, `Banner /etc/issue.net (#62)`, `LogLevel VERBOSE (#62)`, `LoginGraceTime 60 (#62)`, `MaxAuthTries 4 (#62)`, `MaxSessions 4 (#62)`, `MaxStartups 10:30:60 (#62)`, `PermitUserEnvironment no (#62)`, *10. Utwardzenie SSH (CIS 5.2, #62)*
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #63 —   ·  _—_
- `tests/acceptance-remote.sh` — `CONNECT poza allowlistą: $target (403, #16, #63)`
- `tests/acceptance.d/30-sysctl-coredump.sh` — `$key=$expected (#63)`, `Twardy limit core=0 w limits.d (#63)`, `systemd-coredump ProcessSizeMax=0 (#63)`, `systemd-coredump Storage=none (#63)`, *Utwardzenie jądra: sysctl i zrzuty pamięci (#63)*
- `tests/unit/changes.bats` — `PR i merge_group: sieć i harness wymagają KVM bez etykiety (#63, #16)`, `PR: brak albo błędna baza nie omija integracji (#63)`
- `tests/unit/test_network_gates.py` — `test_connect_requires_explicit_proxy_denial`

### #65 —   ·  _—_
- `tests/acceptance.d/20-apparmor.sh` — *AppArmor (CIS 1.6, #65)*

### #66 —   ·  _—_
- `tests/acceptance-remote.sh` — `Audyt: zmiana MAC/AppArmor (#66)`, `Audyt: zmiana konta/PAM (#66)`, *8. Logi i audyt*

### #86 —   ·  _—_
- `tests/unit/changes.bats` — `PR bez etykiet: etap 5/6 pominięty (#86)`, `PR z etykietą run-integration: etap 5 na żądanie (#86)`, `PR ze zmianą poza siecią, bez etykiety: bez etapu 5 (#86)`

### #97 —   ·  _—_
- `tests/acceptance.d/50-hooki-sesji.sh` — `Config hooka 80-wlb-session.py obecny i poprawny składniowo (#97)`, `Emiter sesji trafia do journala z tagiem wlb-session (#97)`, `Emiter sesji wykonywalny (#97)`, *Hooki cyklu życia sesji badacza + emiter SIEM (#97)*

### #98 —   ·  _—_
- `tests/acceptance.d/60-raport-uzycia.sh` — `Badacz nie czyta raportów użycia (#98)`, `Katalog raportów 0750, nie dla badaczy (#98)`, `Rekord użycia wykonywalny (#98)`, `Rekord użycia zapisany do JSONL (#98)`, `Sampler użycia wykonywalny (#98)`, `Timer samplera włączony (#98)`, *Raport użycia/pojemności sesji (#98)*
- `tests/unit/wlb-usage-record.bats` — `brak próbki szczytu -> zera, rekord nadal poprawny (#98)`, `niepoprawne wartości liczbowe sprowadzane do zera (#98)`, `rekord łączy czasy z hooka ze szczytem zasobów z próbki (#98)`

### #105 —   ·  _—_
- `tests/acceptance.d/40-pulpit.sh` — `Metadane: WLB_IMAGE_NAME=wlb-memory (#105)`, `Regresja: obraz bazowy nie jest wlb-memory (#105)`, `Regresja: pulpit XFCE nieobecny w obrazie bazowym (#105)`, `Regresja: serwer VNC nieobecny w obrazie bazowym (#105)`, *Pulpit / flavor wlb-memory (#106) i regresja lekkości bazy (#105)*

### #106 —   ·  _—_
- `tests/acceptance.d/40-pulpit.sh` — `Schowek VNC wyłączony — konfiguracja obecna (#106)`, *Pulpit / flavor wlb-memory (#106) i regresja lekkości bazy (#105)*
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #111 —   ·  _—_
- `tests/acceptance-remote.sh` — `Kernel Julia (IJulia) zarejestrowany (#111)`, *2. Notebook Python, R i Julia*

### #123 —   ·  _—_
- `tests/unit/test_conflict_markers.py` — *Bramka znacznikow konfliktu (#123)*

### #135 —   ·  _—_
- `tests/acceptance.d/70-radiologia.sh` — *Stos neuroobrazowania (FSL, FSLeyes, 3DSlicer, #135)*

## Uwagi

- **Mapa pokazuje testy z jawnym znacznikiem `#NN`.** Wiele zachowań jest pokrytych testami bez odwołania do zgłoszenia (pełny zestaw jednostkowy bats/pytest w `tests/unit/`, akceptacja e2e w `tests/acceptance-remote.sh`, migracja w `tests/migration-remote.sh`). Brak wiersza nie znaczy „brak testu”, lecz „brak znacznika” — przy nowych poprawkach dodawaj `#NN` w tytule/sekcji testu, aby trafił do mapy.
- **Dryf zamrożonych wersji** (np. `markupsafe`) pilnuje test dryfu w etapie 5 oraz nocny pełny build (harmonogram `CI`) — to również forma regresji, łapiąca zmiany spoza repozytorium, zanim uderzą w PR.

