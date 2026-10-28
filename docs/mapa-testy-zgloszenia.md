# Mapa: zgłoszenie → test

Dokument śledzi, które testy pilnują rozwiązania z poszczególnych zgłoszeń, żeby po każdym PR było widać, że **stare i nowe funkcjonalności nadal działają** (wymóg regresji dla Tier 4, DoD #46/#52). Zasada: patrz [CONTRIBUTING.md](../CONTRIBUTING.md) — „każda poprawka = test regresji”.

_Wygenerowano skryptem `ci/mapa-testy.py` z drzewa `tests/` (2026-10-28). Odśwież: `python3 ci/mapa-testy.py`._

## Pokrycie wg zgłoszeń

### #4 — Kolejka eksportu na jednorazowym dysku systemowym — utrata wniosków przy wymianie obrazu  ·  _scalone_
- `tests/acceptance-remote.sh` — `Badacz nie ma dostępu do kolejki`
- `tests/migration-remote.sh` — `Wniosek o eksport z poprzedniej VM jest w kolejce (#4)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #5 — Synchronizacja czasu: chrony korzysta z publicznych serwerów NTP niedostępnych w sieci Laboratorium  ·  _scalone_
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #6 — Logi do SIEM wysyłane bez szyfrowania — TLS dla rsyslog  ·  _scalone_
- `tests/acceptance-remote.sh` — `Moduł TLS rsyslog zainstalowany (lmnsd_gtls, #6)`, `Przekazywanie do SIEM skonfigurowane`, `SIEM po TLS z weryfikacją nazwy serwera (#6)`, `rsyslog bez błędów TLS (moduł, nazwa i zaufanie certyfikatu, #6)`, `rsyslog bez odmów AppArmor (#44, #6)`
- `tests/acceptance.d/20-apparmor.sh` — `Profil rsyslogd w trybie enforce (#6)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`, *TLS do SIEM (#6)*

### #7 — Blokada pobierania plików z JupyterLab na urządzenia badaczy (§24.e, częściowo)  ·  _scalone_
- `tests/acceptance-remote.sh` — *5a. Blokada pobierania plików na urządzenie badacza (#7, §14, §24.e — środek częściowy)*

### #8 — Spójna kopia bazy huba (SQLite) przed snapshotem storage  ·  _scalone_
- `tests/acceptance-remote.sh` — `Hub działa po odtworzeniu z kopii (#8)`, `Kopia bazy huba wykonana na żądanie (#8)`, `Kopia spójna (integrity_check, #8)`, `Kopia tylko dla roota (0600, #8)`, `Kopia zawiera konta huba (#8)`, `Logowanie $R1 po odtworzeniu z kopii (konta i hasła działają, #8)`, `Timer kopii bazy huba włączony (#8)`, *9. Spójna kopia i odtworzenie bazy huba (#8)*, `Świeża kopia istnieje (#8)`

### #9 — Usunięcie starego jądra i modułów z obrazu (restart maszyny budującej przed czyszczeniem)  ·  _otwarte_
- `tests/acceptance.d/10-jedno-jadro.sh` — *Jedno jądro w obrazie (#9)*

### #10 — Kalibracja budżetów wydajności — pierwszy przebieg etapu 6a  ·  _otwarte_
- `tests/unit/perf-helpers.bats` — `median: brak próbek zwraca błąd (#10)`, `median: jedna próbka (#10)`, `median: nieparzysta liczba próbek to wartość środkowa (#10)`, `median: parzysta liczba próbek — dolna środkowa (#10)`, `perf_vm_resources: bez wartości — czapka 4 vCPU / 8192 MB wyliczona z hosta (#10)`, `perf_vm_resources: respektuje podane VM_CPUS/VM_MEMORY (#10)`

### #12 — Proces wydania obrazu (12a): metadane, SBOM, changelog na tag (M2)  ·  _scalone_
- `tests/unit/release.bats` — `image_provenance: GITHUB_RUN_ID trafia do BUILD_RUN (#12)`, `image_provenance: commit, flaga dirty, build_run (#12)`, `release.sh: brak tagu przerywa (#12)`, `release.sh: zły format tagu przerywa (#12)`

### #13 — Runbooki operacyjne cyklu życia Laboratorium  ·  _otwarte_
- `tests/unit/wlb-hub-db-preupgrade.bats` — `brak image-release -> pre-unknown (#13)`, `druga próba tej samej wersji nie nadpisuje starej kopii (#13)`, `kopia pre-<wersja> powstaje, gdy baza istnieje (#13)`, `świeży dysk bez bazy -> brak kopii (#13)`

### #16 — Proxy z allowlistą, mirrory PyPI/CRAN, blokada zewnętrznych API (w tym LLM, §31.3)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Allowlista proxy (mirror PyPI/CRAN) — brak testowego proxy na hoście (#16)`, `CONNECT poza allowlistą: $target (403, #16, #63)`, `Faktyczna instalacja z kuratorowanego mirrora — wymaga mirrora z allowlistą pakietów (#16)`, `Reguły egress nftables załadowane`
- `tests/unit/changes.bats` — `PR i merge_group: sieć i harness wymagają KVM bez etykiety (#63, #16)`
- `tests/unit/test_network_gates.py` — `test_connect_denial_over_real_socket`, `test_connect_requires_explicit_proxy_denial`

### #18 — Dostęp: MFA (Keycloak / Entra ID) i HTTPS przez portal WLB lub bramkę VDI  ·  _otwarte_
- `tests/acceptance.d/15-dostep-tls-cidr.sh` — `443 nie jest otwarte przy HUB_TLS=0 (#18)`, `HTTP na 80 przekierowuje na HTTPS (#18)`, `HTTPS bez zaufanej CA jest odrzucone (#18)`, `Hub odpowiada po HTTPS na 443 z zaufanym certem (#18)`, `Polityka wejścia: drop (#18)`, `nftables: SSH tylko z ADMIN_SSH_CIDR na porcie 22 (#18)`, `nftables: brak 0.0.0.0/0 w aktywnym rulesecie (#18)`, `nftables: hub z HUB_ALLOWED_CIDR na 80 i 443 (TLS, #18)`, `nftables: hub z HUB_ALLOWED_CIDR tylko na 80 (HUB_TLS=0, #18)`, *Dostęp: wymuszony CIDR + TLS huba (#18)*
- `tests/unit/wlb-firstboot.bats` — `#18 CIDR: HUB_ALLOWED_CIDR=0.0.0.0/0 jest odrzucane (/0)`, `#18 CIDR: brak HUB_ALLOWED_CIDR przerywa konfigurację`, `#18 CIDR: końcowa spacja w HUB_ALLOWED_CIDR jest odrzucana`, `#18 CIDR: lista adresów w ADMIN_SSH_CIDR jest odrzucana`, `#18 CIDR: prefiks > 32 jest odrzucany`, `#18 TLS: certyfikat i klucz nie są parą — odrzucone`, `#18 TLS: klucz huba o zbyt szerokich prawach jest odrzucany`, `#18 dostęp: HUB_TLS domyślnie 1 — HTTPS włączone, cert i klucz ustawione`, `#18 dostęp: HUB_TLS=0 — hub tylko po HTTP (port 80, bez 443), z ostrzeżeniem`, `#18 fail-secure: błąd TLS huba nie otwiera portu huba ani nie kończy firstboot`, `SIEM TLS: nieczytelny certyfikat CA przerywa konfigurację`, `pełna konfiguracja Laboratorium`, *#18: dostęp (CIDR fail-secure, TLS huba)*, *Uwierzytelnianie: native / OIDC (#18)*

### #20 — Proces zatwierdzania eksportu przez Kontrolera Przesyłu Danych  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Manifest i integralność kopii w kolejce (#20)`
- `tests/migration-remote.sh` — `Manifest i kopia przeżywają wymianę VM (#20)`
- `tests/unit/test_wlb_export_snapshot.py` — *#20: integralność kopii, manifest, wyścigi i awarie*
- `tests/unit/wlb-sluza-out-mover.bats` — `#20: niedozwolony element zatrzymuje cały katalog w kwarantannie`, `#20: suma katalogu odtwarzalna przez weryfikator po przeniesieniu pakietu`

### #23 — Decyzja regulaminowa: czy badacz może instalować pakiety z mirrora PyPI/CRAN (§24.c)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Allowlista proxy (mirror PyPI/CRAN) — brak testowego proxy na hoście (#16)`, `deny: interpreter TLJH z pipem dostępny dla badacza`
- `tests/unit/wlb-firstboot.bats` — *Instalacja pakietów przez badacza (#23, IMG-004)*

### #29 — TOCTOU w śluzie wyjściowej: podmiana pliku na dowiązanie symboliczne przed przeniesieniem przez root  ·  _scalone_
- `tests/acceptance-remote.sh` — `Dowiązanie w /sluza-out odrzucone (#29)`, `Kolejka eksportu na dysku roboczym`, `Prawa /etc/passwd bez zmian (#29)`, `W kolejce nie ma dowiązań ani plików specjalnych (#29)`
- `tests/unit/wlb-sluza-out-mover.bats` — `#29: dwa wpisy o tej samej nazwie w tej samej sekundzie nie nadpisują się`, `#29: plik podmieniony na dowiązanie po sprawdzeniu — cel nietknięty, kolejka pusta`, `#29: plik z drugim dowiązaniem twardym jest odrzucany, oryginał badacza zostaje`, `#29: wpis usunięty przez badacza w trakcie przeglądu nie zatrzymuje usługi`, *#29: podmiana wpisu między sprawdzeniem a przeniesieniem (TOCTOU)*

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

### #53 — Logo IP_CMC na stronie logowania i w nagłówku huba  ·  _scalone_
- `tests/acceptance-remote.sh` — `Logo na stronie logowania wskazuje /hub/logo (#53)`, `Logo to przesłany plik PNG IP_CMC (#53)`, `Nazwa platformy na stronie logowania (#53)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*

### #54 — Kafelek „Pomoc i zgłoszenia” (helpdesk) w Launcherze JupyterLab  ·  _scalone_
- `tests/acceptance-remote.sh` — `Kafelek pomocy w konfiguracji Launchera (#54)`, `Strona pomocy z kontaktem helpdesku (#54)`, `jupyter-app-launcher zainstalowany (#54)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*

### #62 — SSH: Limity logowania i komunikat powitalny (CIS 5.2)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Baner nie ujawnia wersji systemu (#62)`, `Baner prawny o monitoringu (#62)`, `Banner /etc/issue.net (#62)`, `LogLevel VERBOSE (#62)`, `LoginGraceTime 60 (#62)`, `MaxAuthTries 4 (#62)`, `MaxSessions 4 (#62)`, `MaxStartups 10:30:60 (#62)`, `PermitUserEnvironment no (#62)`, *10. Utwardzenie SSH (CIS 5.2, #62)*
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #63 — sysctl: brakujące parametry sieciowe i wyłączenie zrzutów pamięci (CIS 1.x/3.x)  ·  _scalone_
- `tests/acceptance-remote.sh` — `CONNECT poza allowlistą: $target (403, #16, #63)`
- `tests/acceptance.d/30-sysctl-coredump.sh` — `$key=$expected (#63)`, `Twardy limit core=0 w limits.d (#63)`, `systemd-coredump ProcessSizeMax=0 (#63)`, `systemd-coredump Storage=none (#63)`, *Utwardzenie jądra: sysctl i zrzuty pamięci (#63)*
- `tests/unit/changes.bats` — `PR i merge_group: sieć i harness wymagają KVM bez etykiety (#63, #16)`, `PR: brak albo błędna baza nie omija integracji (#63)`
- `tests/unit/test_network_gates.py` — `test_connect_requires_explicit_proxy_denial`

### #65 — AppArmor: apparmor-utils, apparmor=1 w GRUB i profile w trybie complain (CIS 1.6)  ·  _otwarte_
- `tests/acceptance.d/20-apparmor.sh` — `Licznik profili w complain = 0`, `apparmor-utils zainstalowany (aa-enforce, aa-status)`, `security=apparmor w parametrach jądra (GRUB)`, *AppArmor (CIS 1.6, #65)*
- `tests/unit/wlb-apparmor-mode.bats` — `rsyslogd unconfined + inny profil enforce w tej samej linii -> unconfined (#65 regresja)`

### #66 — Reguły audytu: konta, czas, moduły, sesje, AppArmor (podstawa §21/OPZ B.21)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Audyt: zmiana MAC/AppArmor (#66)`, `Audyt: zmiana konta/PAM (#66)`, *8. Logi i audyt*

### #86 — CI: etap 5/6a rzadziej lub lokalnie — bramkowanie weryfikacji ciężkiej (do czasu self-hosted #25)  ·  _otwarte_
- `tests/unit/changes.bats` — `PR bez etykiet: etap 5/6 pominięty (#86)`, `PR z etykietą run-integration: etap 5 na żądanie (#86)`, `PR ze zmianą poza siecią, bez etykiety: bez etapu 5 (#86)`

### #97 — Hooki sesji badacza (pre/post-spawn): montaż, znacznik audytu, sprzątanie — inspiracja AppStream  ·  _otwarte_
- `tests/acceptance.d/50-hooki-sesji.sh` — `Config hooka 80-wlb-session.py obecny i poprawny składniowo (#97)`, `Emiter sesji trafia do journala z tagiem wlb-session (#97)`, `Emiter sesji wykonywalny (#97)`, *Hooki cyklu życia sesji badacza + emiter SIEM (#97)*

### #98 — Raporty użycia sesji do planowania pojemności — inspiracja AppStream  ·  _otwarte_
- `tests/acceptance.d/60-raport-uzycia.sh` — `Badacz nie czyta raportów użycia (#98)`, `Katalog raportów 0750, nie dla badaczy (#98)`, `Rekord użycia wykonywalny (#98)`, `Rekord użycia zapisany do JSONL (#98)`, `Sampler użycia wykonywalny (#98)`, `Timer samplera włączony (#98)`, *Raport użycia/pojemności sesji (#98)*
- `tests/unit/wlb-usage-record.bats` — `brak próbki szczytu -> zera, rekord nadal poprawny (#98)`, `niepoprawne wartości liczbowe sprowadzane do zera (#98)`, `rekord łączy czasy z hooka ze szczytem zasobów z próbki (#98)`

### #105 — Flavor „pod pamięć”: pulpit w przeglądarce + aplikacje GUI (arkusz, zamiennik Prism) i kafelek Leaf  ·  _otwarte_
- `tests/acceptance.d/40-pulpit.sh` — `Metadane: flavor z pulpitem wlb-memory/wlb-radiologia (#105, #135)`, `Regresja: obraz bazowy nie ma pulpitu (wlb-memory/wlb-radiologia, #105)`, `Regresja: pulpit XFCE nieobecny w obrazie bazowym (#105)`, `Regresja: serwer VNC nieobecny w obrazie bazowym (#105)`, *Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135) i lekkość bazy (#105)*

### #106 — Pulpit w przeglądarce: rola desktop + flavor wlb-memory (remote-desktop-proxy, kafelek „Pulpit”)  ·  _otwarte_
- `tests/acceptance.d/40-pulpit.sh` — `Schowek VNC wyłączony — konfiguracja obecna (#106)`, *Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135) i lekkość bazy (#105)*
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #111 — Kernel Julia (luka vs strona JupyterHub IP_CMC)  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Kernel Julia (IJulia) zarejestrowany (#111)`, *2. Notebook Python, R i Julia*

### #123 — Bramka etapu 1: nierozwiązane znaczniki konfliktu gita w plikach nielintowanych  ·  _scalone_
- `tests/unit/test_conflict_markers.py` — *Bramka znacznikow konfliktu (#123)*

### #135 — Flavor wlb-radiologia: pulpit + FSL/FSLeyes/3DSlicer (warstwowy build na #106)  ·  _otwarte_
- `tests/acceptance.d/40-pulpit.sh` — `Metadane: flavor z pulpitem wlb-memory/wlb-radiologia (#105, #135)`, *Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135) i lekkość bazy (#105)*
- `tests/acceptance.d/70-radiologia.sh` — *Stos neuroobrazowania (FSL, FSLeyes, 3DSlicer, #135)*

### #149 — feat(storage): izolacja i limity cgroups dla demona śluzy wyjściowej (sluza-out)  ·  _otwarte_
- `tests/unit/changes.bats` — `śluza: PR i merge_group wymagają integracji bez etykiety (#149)`

### #157 — Testy #65/AppArmor (20-apparmor.sh): expect_fail na complain oblewa POPRAWNY obraz  ·  _otwarte_
- `tests/acceptance.d/20-apparmor.sh` — `apparmor-utils zainstalowany (aa-enforce, aa-status)`

## Uwagi

- **Mapa pokazuje testy z jawnym znacznikiem `#NN`.** Wiele zachowań jest pokrytych testami bez odwołania do zgłoszenia (pełny zestaw jednostkowy bats/pytest w `tests/unit/`, akceptacja e2e w `tests/acceptance-remote.sh`, migracja w `tests/migration-remote.sh`). Brak wiersza nie znaczy „brak testu”, lecz „brak znacznika” — przy nowych poprawkach dodawaj `#NN` w tytule/sekcji testu, aby trafił do mapy.
- **Dryf zamrożonych wersji** (np. `markupsafe`) pilnuje test dryfu w etapie 5 oraz nocny pełny build (harmonogram `CI`) — to również forma regresji, łapiąca zmiany spoza repozytorium, zanim uderzą w PR.

