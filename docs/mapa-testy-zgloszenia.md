# Mapa: zgłoszenie → test

Dokument śledzi, które testy pilnują rozwiązania z poszczególnych zgłoszeń, żeby po każdym PR było widać, że **stare i nowe funkcjonalności nadal działają** (wymóg regresji dla Tier 4, DoD #46/#52). Zasada: patrz [CONTRIBUTING.md](../CONTRIBUTING.md) — „każda poprawka = test regresji”.

_Wygenerowano skryptem `ci/mapa-testy.py` z drzewa `tests/` (2026-11-20). Odśwież: `python3 ci/mapa-testy.py`._

## Pokrycie wg zgłoszeń

### #4 — Kolejka eksportu na jednorazowym dysku systemowym — utrata wniosków przy wymianie obrazu  ·  _scalone_
- `tests/acceptance-remote.sh` — `Badacz nie ma dostępu do kolejki`
- `tests/acceptance.d/70-radiologia.sh` — `3DSlicer startuje pod wirtualnym X — biblioteki xcb + Qt (#4)`, `FSLeyes uruchamia się (--version, #4)`, `Kafelek czytnika PDF w menu (#200)`, `Regresja: brak serwera X (Xtigervnc) na flavorze radiologia (#4)`, *Uruchamialność GUI stosu neuro (#4)*
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

### #17 — SIEM: Wazuh/OpenSearch — dekodery i reguły na podstawie kontraktu obserwowalności  ·  _otwarte_
- `tests/unit/test_observability_contract.py` — `test_zdarzenie_uslugi_tylko_od_jej_programu`, *Wazuh: dekodery i reguły powiązane z kontraktem (#17)*
- `tests/unit/test_wazuh_check.py` — *walidator wyników logtest (#17)*
- `tests/unit/test_wazuh_logtest_client.py` — *protokół logtest: długość + JSON, jedna sesja na plik (#17)*

### #18 — Dostęp: MFA (Keycloak / Entra ID) i HTTPS przez portal WLB lub bramkę VDI  ·  _otwarte_
- `tests/acceptance-remote.sh` — `${AUTH_MODE}: konfiguracja 70-wlb-auth.py obecna (#18)`, `AUTH_MODE=${AUTH_MODE}: logowanie runtime zablokowane — brak produkcyjnego IdP (#18, #57)`, `OIDC: klasa generic-oauth w konfiguracji (#18)`, `Serwer notebooków uruchomiony ($R1)`, `entra: klasa WlbEntraAuthenticator w konfiguracji (#18)`
- `tests/acceptance.d/15-dostep-tls-cidr.sh` — `443 nie jest otwarte przy HUB_TLS=0 (#18)`, `HTTP na 80 przekierowuje na HTTPS (#18)`, `HTTPS bez zaufanej CA jest odrzucone (#18)`, `Hub odpowiada po HTTPS na 443 z zaufanym certem (#18)`, `Polityka wejścia: drop (#18)`, `nftables: SSH tylko z ADMIN_SSH_CIDR na porcie 22 (#18)`, `nftables: brak 0.0.0.0/0 w aktywnym rulesecie (#18)`, `nftables: hub z HUB_ALLOWED_CIDR na 80 i 443 (TLS, #18)`, `nftables: hub z HUB_ALLOWED_CIDR tylko na 80 (HUB_TLS=0, #18)`, *Dostęp: wymuszony CIDR + TLS huba (#18)*
- `tests/acceptance.d/68-entra.sh` — `Badacz nie zmieni modułów logowania (#18)`, `Hub wraca po odwołaniu (#18)`, `Konto i hasło Native bez zmian po odwołaniu (#18)`, `Moduły Entra zainstalowane (#18)`, `Odwołanie nie dotyka innych kont (#18)`, `Po odwołaniu: serwer konta zatrzymany — trwające połączenia zamknięte (#18)`, `Po odwołaniu: stare ciasteczko nie otwiera huba (#18)`, `Po odwołaniu: stary token API odrzucony (#18)`, `Przed odwołaniem: ciasteczko konta działa (#18)`, `Przed odwołaniem: serwer konta działa (#18)`, `Przed odwołaniem: token API konta działa (#18)`, `Rejestr przypisań: obcy tenant odrzucony (#18)`, `Rejestr przypisań: poprawny przechodzi (#18)`, `WlbEntraAuthenticator na oauthenticator z TLJH: przypisanie, rola, odmowy, sesja (#18)`, `wlb-hub-revoke --user odwołuje poświadczenia konta (#18)`, *Logowanie Entra ID: moduły w obrazie (#18)*, *Odwołanie poświadczeń konta przez hub (wlb-hub-revoke, #18)*
- `tests/unit/wlb-firstboot.bats` — `#18 CIDR: HUB_ALLOWED_CIDR=0.0.0.0/0 jest odrzucane (/0)`, `#18 CIDR: brak HUB_ALLOWED_CIDR przerywa konfigurację`, `#18 CIDR: końcowa spacja w HUB_ALLOWED_CIDR jest odrzucana`, `#18 CIDR: lista adresów w ADMIN_SSH_CIDR jest odrzucana`, `#18 CIDR: prefiks > 32 jest odrzucany`, `#18 TLS: certyfikat i klucz nie są parą — odrzucone`, `#18 TLS: klucz huba o zbyt szerokich prawach jest odrzucany`, `#18 dostęp: HUB_TLS domyślnie 1 — HTTPS włączone, cert i klucz ustawione`, `#18 dostęp: HUB_TLS=0 — hub tylko po HTTP (port 80, bez 443), z ostrzeżeniem`, `#18 fail-secure: błąd TLS huba nie otwiera portu huba ani nie kończy firstboot`, `AUTH_MODE oidc: brak lub puste grupy przerywa przed zmianą (P0 z audytu #18)`, `AUTH_MODE oidc: poprawny config GenericOAuthenticator (grupy, bez allow_all)`, `AUTH_MODE oidc: wygenerowany config ładuje się w oauthenticator 17 (#18)`, `SIEM TLS: nieczytelny certyfikat CA przerywa konfigurację`, `pełna konfiguracja Laboratorium`, *#18: dostęp (CIDR fail-secure, TLS huba)*, *AUTH_MODE=entra: Entra ID, login z rejestru (tid, oid) -> konto, rola aplikacji (#18)*, *Uwierzytelnianie: native / OIDC (#18)*

### #20 — Proces zatwierdzania eksportu przez Kontrolera Przesyłu Danych  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Manifest i integralność kopii w kolejce (#20)`
- `tests/migration-remote.sh` — `Manifest i kopia przeżywają wymianę VM (#20)`
- `tests/unit/test_wlb_export_snapshot.py` — *#20: integralność kopii, manifest, wyścigi i awarie*
- `tests/unit/wlb-export.bats` — `wlb-export list: pokazuje wniosek z metadanymi (#20)`, `wlb-export list: wpis legacy (bez manifestu v1) oznaczony, nie ukryty (#20)`, `wlb-export show: zweryfikowany deskryptor po request_id, bez treści/nazw plików (#20)`, `wlb-export stage: kopiuje zweryfikowany payload do staged, kolejka nietknięta (#20)`, `wlb-export stage: nie nadpisuje istniejącego staged (retencja ręczna, #20)`, `wlb-export staged-clear: usuwa staged pliki (#20)`, `wlb-export verify: poprawny pakiet -> exit 0 (#20)`, `wlb-export: list/show/verify NIE modyfikują kolejki (inwariant read-only, #20)`, `wlb-export: nieznany request_id -> błąd niezerowy (fail-closed, #20)`
- `tests/unit/wlb-sluza-out-mover.bats` — `#20: niedozwolony element zatrzymuje cały katalog w kwarantannie`, `#20: suma katalogu odtwarzalna przez weryfikator po przeniesieniu pakietu`

### #22 — Metryki VM (np. node_exporter, /hub/metrics) — wybór systemu monitoringu  ·  _otwarte_
- `tests/acceptance.d/65-node-exporter.sh` — `Badacz nie może zapisać metryk (#22)`, `Metryki dostępne lokalnie (#22)`, `brak ekspozycji metryk bez MONITORING_CIDR (#22)`, `nftables: metryki tylko z MONITORING_CIDR na 9100 (#22)`, `node_exporter działa (#22)`, `node_exporter nasłuchuje tylko na IPv4 loopback (#22)`, `node_exporter słucha poza pętlą (#22)`, `node_exporter włączony (#22)`, `override eksportera pochodzi z firstboot (#22)`, *Metryki systemowe (#22)*
- `tests/acceptance.d/66-wlb-health.sh` — `Kolejka eksportu poprawnie zmierzona (#22)`, `Pliki kolejki SIEM poprawnie zmierzone (#22)`, `Pomiar wlb-health kończy się poprawnie (#22)`, `Timer wlb-health działa (#22)`, `Timer wlb-health włączony (#22)`, *Zagregowane metryki stanu WLB (#22)*, `Świeża próbka wlb-health (#22)`
- `tests/acceptance.d/67-monitoring-siec.sh` — `Bez zapory eksporter poza pętlą nie startuje (guard) (#22)`, `Bez zapory nic nie słucha poza pętlą (#22)`, `Domyślnie: dozwolone źródło nie pobiera metryk (#22)`, `Dozwolone źródło pobiera /metrics (#22)`, `Efektywna komenda eksportera: 0.0.0.0 + flagi z obrazu (#22)`, `Inne źródło nie łączy się z 9100 (#22)`, `Niekanoniczny zakres jest odrzucany bez zmian (#22)`, `Po naprawie nasłuch tylko na pętli (#22)`, `Po odrzuceniu nadal tylko pętla (#22)`, `Po powrocie zapory eksporter otwiera gniazdo poza pętlą (#22)`, `Po powrocie zapory ekspozycja wraca (#22)`, `Po restarcie zapory dozwolone źródło pobiera (#22)`, `Po restarcie zapory eksporter działa (#22)`, `Po restarcie zapory inne źródło odrzucane (#22)`, `Po wyłączeniu brak reguły 9100 w rulesecie (#22)`, `Po wyłączeniu dozwolone źródło traci dostęp (#22)`, `Po wyłączeniu nasłuch tylko na pętli (#22)`, `Ponowione disable naprawia stan (#22)`, `Port 9100 dopuszczony tylko w łańcuchu monitoring_in (#22)`, `Restart zapory: reguła odtworzona z include (#22)`, `Start eksportera podnosi zaporę z regułą (Wants=) (#22)`, `Stop zapory zatrzymuje eksporter poza pętlą (#22)`, `Symulacja przerwanego wyłączenia: proces poza pętlą (#22)`, `Włączenie nie zmienia dostępu do huba (reguła i odpowiedź) (#22)`, `wlb-monitoring apply $MON_OK_SRC/32 (#22)`, `wlb-monitoring disable (#22)`, *Ekspozycja metryk dla sieci monitoringu (#22)*
- `tests/unit/test_node_exporter_config.py` — `test_monitoring_tool_paths_match_the_role_and_firstboot`, `test_node_exporter_is_configured_before_install_and_only_listens_locally`
- `tests/unit/test_observability_contract.py` — *log z SIEM*
- `tests/unit/wlb-firstboot.bats` — `#22 metryki: --force po usunięciu MONITORING_CIDR wyłącza pozostałą ekspozycję`, `#22 metryki: MONITORING_CIDR=/32 stosuje ekspozycję dopiero po otwarciu portu huba`, `#22 metryki: bez MONITORING_CIDR nic się nie zmienia (żadnego wywołania)`, `#22 metryki: błąd wlb-monitoring nie zamyka huba i nie pomija reguł audytu`, `#22 metryki: niekanoniczny MONITORING_CIDR przerywa przed zmianą zapory`, *Metryki VM dla sieci monitoringu (#22)*
- `tests/unit/wlb-monitoring.bats` — `#22 apply: brak gniazda po restarcie cofa ekspozycję`, `#22 apply: brak pliku eksportera z obrazu przerywa bez zmian w jądrze`, `#22 apply: czeka na gniazdo eksportera po restarcie (wyścig z etapu 5)`, `#22 apply: gdy nasłuch nie wstaje na 0.0.0.0, ekspozycja jest cofana`, `#22 apply: niekanoniczne wartości są odrzucane i nic nie zmieniają`, `#22 apply: nieudany restart eksportera też cofa ekspozycję`, `#22 apply: plik eksportera z nieoczekiwanym adresem nasłuchu jest odrzucany`, `#22 apply: reguła w jądrze, plik na dysku, override eksportera i weryfikacja nasłuchu`, `#22 disable: brak gniazda po restarcie to niepotwierdzony stan, nie sukces`, `#22 disable: brak łańcucha monitoring_in (starszy ruleset) nie wywraca wyłączania`, `#22 disable: idempotentne, gdy ekspozycja nigdy nie była włączona`, `#22 disable: naprawia stan także wtedy, gdy plik override już zniknął`, `#22 disable: nieaktywny eksporter to niepotwierdzony stan`, `#22 disable: zamyka regułę, usuwa pliki i wraca na pętlę`, `#22 guard: brak pliku reguły blokuje nasłuch poza pętlą`, `#22 guard: nieaktywna zapora blokuje nasłuch poza pętlą`, `#22 guard: przepuszcza start tylko przy aktywnej zaporze i utrwalonej regule`, `#22 guard: wyczyszczona reguła w jądrze blokuje nasłuch poza pętlą`, `#22 status: pokazuje plik reguły, override i nasłuch`, `#22 użycie: nieznana komenda kończy się błędem z opisem`

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

### #35 — Telemetria CI: walidacja OTLP/JSON oficjalnym schematem w testach  ·  _scalone_
- `tests/unit/test_ci_telemetry.py` — *#35: walidacja trzech sygnałów oficjalnym schematem OTLP + semantyka*, *Walidacja OTLP/JSON oficjalnym schematem (#35)*

### #36 — Test akceptacyjny: faktyczna synchronizacja czasu z NTP_SERVERS  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Brak publicznych serwerów NTP`, `Synchronizacja NTP — brak testowego serwera NTP na hoście (wymaga sudo, #36)`, `chrony zsynchronizowany z NTP_SERVERS (#36)`

### #44 — SIEM: badacz może fałszować zdarzenia z kontraktu (logger z tagiem wlb-*) — pola zaufane z journald  ·  _scalone_
- `tests/acceptance-remote.sh` — `Reguły audytu zablokowane (-e 2)`, `Wpis podrobiony przez badacza ma w journald jego UID (#44)`, `rsyslog bez odmów AppArmor (#44, #6)`
- `tests/unit/wlb-firstboot.bats` — `pełna konfiguracja Laboratorium`

### #51 — Decyzja: zakres uprawnień Administratora Klienta w hubie (dostęp do serwerów i kont badaczy)  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Administrator Klienta NIE w users.admin (brak pełnego admina)`, `Uprzywilejowana akcja admina audytowana pod tagiem wlb-hub-audit (#51)`, *5c. Administrator Klienta: rola ograniczona, bez wglądu w dane badacza (IMG-003/#51)*
- `tests/unit/wlb-firstboot.bats` — `--force nie dubluje admina i nie nadpisuje hasła`, `HUB_ADMIN_USER o nieprawidłowym formacie jest odrzucany (#51)`, `pełna konfiguracja Laboratorium`

### #53 — Logo IP_CMC na stronie logowania i w nagłówku huba  ·  _scalone_
- `tests/acceptance-remote.sh` — `Logo na stronie logowania wskazuje /hub/logo (#53)`, `Logo to przesłany plik PNG IP_CMC (#53)`, `Nazwa platformy na stronie logowania (#53)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*

### #54 — Kafelek „Pomoc i zgłoszenia” (helpdesk) w Launcherze JupyterLab  ·  _scalone_
- `tests/acceptance-remote.sh` — `Kafelek pomocy w konfiguracji Launchera (#54)`, `Strona pomocy z kontaktem helpdesku (#54)`, `jupyter-app-launcher zainstalowany (#54)`, *5b. Identyfikacja IP_CMC i pomoc (#53, #54)*
- `tests/unit/test_launcher_help.py` — `test_launcher_ma_kafelek_pomocy`, `test_pomoc_ma_kontakt_helpdesku`

### #62 — SSH: Limity logowania i komunikat powitalny (CIS 5.2)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Baner nie ujawnia wersji systemu (#62)`, `Baner prawny o monitoringu (#62)`, `Banner /etc/issue.net (#62)`, `LogLevel VERBOSE (#62)`, `LoginGraceTime 60 (#62)`, `MaxAuthTries 4 (#62)`, `MaxSessions 4 (#62)`, `MaxStartups 10:30:60 (#62)`, `PermitUserEnvironment no (#62)`, *10. Utwardzenie SSH (CIS 5.2, #62)*
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #63 — sysctl: brakujące parametry sieciowe i wyłączenie zrzutów pamięci (CIS 1.x/3.x)  ·  _scalone_
- `tests/acceptance-remote.sh` — `CONNECT poza allowlistą: $target (403, #16, #63)`
- `tests/acceptance.d/30-sysctl-coredump.sh` — `$key=$expected (#63)`, `Twardy limit core=0 w limits.d (#63)`, `systemd-coredump ProcessSizeMax=0 (#63)`, `systemd-coredump Storage=none (#63)`, *Utwardzenie jądra: sysctl i zrzuty pamięci (#63)*
- `tests/acceptance.d/47-histologia.sh` — `jamovi: dostęp sandboxa do /workspace (override, #108)`, `jamovi: sandbox bwrap startuje (nieuprzywilejowane userns, #63/#108)`
- `tests/unit/changes.bats` — `PR i merge_group: sieć i harness wymagają KVM bez etykiety (#63, #16)`, `PR: brak albo błędna baza nie omija integracji (#63)`
- `tests/unit/test_network_gates.py` — `test_connect_requires_explicit_proxy_denial`

### #65 — AppArmor: apparmor-utils, apparmor=1 w GRUB i profile w trybie complain (CIS 1.6)  ·  _scalone_
- `tests/acceptance.d/20-apparmor.sh` — `Licznik profili w complain = 0`, `apparmor-utils zainstalowany (aa-enforce, aa-status)`, `security=apparmor w parametrach jądra (GRUB)`, *AppArmor (CIS 1.6, #65)*
- `tests/acceptance.d/40-pulpit.sh` — `Skrypt AppArmor enforce warstwy pulpitu na obrazie (#65)`, `Warstwa pulpitu kończy się licznikiem AppArmor complain = 0 (#65, CIS 1.6.3)`, `websockify na obrazie`
- `tests/acceptance.d/47-histologia.sh` — `jamovi: dostęp sandboxa do /workspace (override, #108)`
- `tests/unit/wlb-apparmor-mode.bats` — `rsyslogd unconfined + inny profil enforce w tej samej linii -> unconfined (#65 regresja)`

### #66 — Reguły audytu: konta, czas, moduły, sesje, AppArmor (podstawa §21/OPZ B.21)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Audyt: zmiana MAC/AppArmor (#66)`, `Audyt: zmiana konta/PAM (#66)`, *8. Logi i audyt*

### #78 — Długie obliczenia (> 12 h) odpięte od limitu sesji §9.5  ·  _otwarte_
- `tests/acceptance-remote.sh` — *7. Limity sesji (§9.5)*
- `tests/unit/wlb-firstboot.bats` — `limit sesji: --force po usunięciu MAX_SESSION_HOURS cofa wydłużenie do domyślnego (#78)`, `limit sesji: MAX_SESSION_HOURS niepoprawne (zakres, zera wiodące, nieliczba) -> blad firstboot (#78)`, `limit sesji: MAX_SESSION_HOURS=48 -> cull.max_age + TTL ciasteczka/tokenu spojnie (#78)`, `limit sesji: domyslnie (bez MAX_SESSION_HOURS) brak override i ZADNEGO set cull.max_age (#78)`

### #84 — CI: zmiany dokumentacji w obrazie nie powinny wyzwalać etapu 5 (allowlista changes.sh)  ·  _otwarte_
- `tests/unit/changes.bats` — `push tylko z CHANGELOG.md: etap 5 pominięty (#84)`, `tekst-w-obrazie: PR/push zmieniający tylko pomoc.md Launchera pomija etap 5 (#84)`, `tekst-w-obrazie: konfiguracja Launchera (yaml) NIE jest zwolniona — wyzwala etap 5 (#84)`, `tekst-w-obrazie: pomoc.md razem z kodem nadal wyzwala etap 5 (#84)`

### #86 — CI: etap 5/6a rzadziej lub lokalnie — bramkowanie weryfikacji ciężkiej (do czasu self-hosted #25)  ·  _scalone_
- `tests/unit/changes.bats` — `PR bez etykiet: etap 5/6 pominięty (#86)`, `PR z etykietą run-integration: etap 5 na żądanie (#86)`, `PR ze zmianą poza siecią, bez etykiety: bez etapu 5 (#86)`

### #97 — Hooki sesji badacza (pre/post-spawn): montaż, znacznik audytu, sprzątanie — inspiracja AppStream  ·  _otwarte_
- `tests/acceptance.d/50-hooki-sesji.sh` — `Config hooka 80-wlb-session.py obecny i poprawny składniowo (#97)`, `Emiter sesji trafia do journala z tagiem wlb-session (#97)`, `Emiter sesji wykonywalny (#97)`, `Realny Hub E2E (#97): serwer jupyter-$R2 nie jest aktywny`, `Realny Hub: brak SID1 uniemożliwia weryfikację session_start (#97)`, `Realny Hub: brak SID1 uniemożliwia weryfikację session_stop (#97)`, `Realny Hub: brak SID2 uniemożliwia weryfikację nowego session_start (#97)`, `Realny Hub: jednostka systemd ponownie aktywna (#97)`, `Realny Hub: jednostka systemd zatrzymana (#97)`, `Realny Hub: marker w scratchu usunięty (#97, #318)`, `Realny Hub: nowy scratch sesji utworzony (#97, #318)`, `Realny Hub: nowy session_id jest różny od poprzedniego (#97)`, `Realny Hub: plik stanu sesji obecny (#97, #98)`, `Realny Hub: plik stanu sesji usunięty po stopie (#97)`, `Realny Hub: ponowny spawn serwera $R2 (#97)`, `Realny Hub: scratch ma tryb 0700 (#97, #318)`, `Realny Hub: scratch należy do badacza $R2 (#97, #318)`, `Realny Hub: scratch sesji całkowicie usunięty po stopie (#97, #318)`, `Realny Hub: scratch sesji na tmpfs obecny dla jupyter-$R2 (#97, #318)`, `Realny Hub: session_id w stanie sesji jest niepusty (#97)`, `Realny Hub: session_start wyemitowany dla nowego SID2 (#97)`, `Realny Hub: session_start wyemitowany do journald z SID1 (#97)`, `Realny Hub: session_stop w journald ze skorelowanym SID1 i czasem trwania (#97)`, `Realny Hub: zapis pliku-markera w scratchu (#97, #318)`, `Realny Hub: zatrzymanie serwera przez API Huba (hub_stop $R2) (#97)`, `pre_spawn domyka osieroconą sesję jako interrupted (#97, #98)`, *Hooki cyklu życia sesji badacza + emiter SIEM (#97)*, *Pełny E2E cykl życia z realnym Hubem (#97, #318)*
- `tests/unit/test_wlb_session_hook.py` — `test_pre_spawn_czysta_sesja_nie_wywoluje_interrupted`, `test_pre_spawn_domyka_osierocona_sesje_jako_interrupted`, `test_pre_spawn_osierocona_sesja_bez_start_wall_przekazuje_pusty_czas`, `test_pre_spawn_uszkodzony_plik_stanu_nie_wywraca_spawnu`, `test_wlb_ident_normalizuje_unit_name_bez_sufiksu`, `test_wlb_ident_wola_ensure_user_gdy_konto_jeszcze_nie_istnieje`

### #98 — Raporty użycia sesji do planowania pojemności — inspiracja AppStream  ·  _scalone_
- `tests/acceptance.d/50-hooki-sesji.sh` — `Realny Hub: plik stanu sesji obecny (#97, #98)`, `pre_spawn domyka osieroconą sesję jako interrupted (#97, #98)`
- `tests/acceptance.d/60-raport-uzycia.sh` — `Badacz nie czyta raportów użycia (#98)`, `Katalog raportów 0750, nie dla badaczy (#98)`, `Katalog stanu korelacji nie do odczytu przez badacza (#98)`, `Plik raportu 0640 od narodzin (#98)`, `Probka niesie BootID i InvocationID (#98)`, `Probka z obcego bootu -> no_samples i null, nie zero udajace pomiar (#98)`, `Reguła tmpfiles dla katalogu stanu (#98)`, `Rekord complete: tozsama probka w oknie sesji, pelne wartosci (#98)`, `Rekord użycia wykonywalny (#98)`, `Sampler użycia wykonywalny (#98)`, `Sampler łowi rzeczywista jednostke serwera badacza (#98)`, `Samplera na zywej jednostce — serwer $R1 nieaktywny w tym punkcie akceptacji`, `Timer samplera włączony (#98)`, *Raport użycia/pojemności sesji (#98)*
- `tests/unit/test_wlb_session_hook.py` — `test_pre_spawn_domyka_osierocona_sesje_jako_interrupted`, `test_pre_spawn_osierocona_sesja_bez_start_wall_przekazuje_pusty_czas`
- `tests/unit/wlb-usage-record.bats` — `UINT64_MAX i [not set] to brak pomiaru, nie rozmiar (#98)`, `brak próbki -> no_samples i null, nigdy zero udające pomiar (#98)`, `cudzolow i polskie znaki w lab nie psuja JSON — rekord caly sie parsuje (#98)`, `niepoprawny czas trwania -> duration null, status partial (#98)`, `próbka spoza okna sesji -> odrzucona z powodem (dziedzictwo po poprzedniej sesji) (#98)`, `próbka z innego bootu jest odrzucana (nie przezywa reboota jako 'nasza') (#98)`, `spójna próbka tej samej sesji -> rekord complete z pelnymi danymi (#98)`, `zle uzycie (za malo argumentow) konczy sie 2 bez zapisu (#98)`
- `tests/unit/wlb-usage-sampler.bats` — `aktywna jednostka: pelna tozsamosc probki i pomiar zapisane (#98)`, `brak aktywnych jednostek: zadnych plikow i zadnego awaryjnego tmp (#98)`, `konwencje systemd ([not set], UINT64_MAX) to brak klucza, nie zero (#98)`, `ta sama instancja: CPUIntervalMax z delty; nowa instancja interval resetuje (#98)`

### #102 — Weryfikacja architektury: model kont WLB (nazwane vs bezosobowe uNN) wg standardu  ·  _otwarte_
- `tests/acceptance-remote.sh` — *0. Konta bezosobowe uNN/a01 pre-provisionowane; self-signup wyłączony (IMG-002/#102)*
- `tests/unit/test_wlb_hub_user.py` — *Tryby odczytu dla bezpiecznego provisioningu w wlb-firstboot (#102)*
- `tests/unit/wlb-firstboot.bats` — `HUB_ADMIN_USER nie może używać przestrzeni kont badaczy, nawet poza aktualną pulą (#102)`, `RESEARCHER_ACCOUNTS: błędny zapis i przepełnienie są odrzucane przed provisioningiem (#102)`, `pełna konfiguracja Laboratorium`, `plik hasła bez konta — konto nie jest odtwarzane, ostrzeżenie (#102)`, `plik oczekujący bez konta (przerwanie przed zapisem w bazie) — konto z hasłem z pliku (#102)`, `plik oczekujący, konto z dysku roboczego ma inne hasło — hasło bez zmian (#102)`, `pre-provisioning kont stanowiskowych uNN wg RESEARCHER_ACCOUNTS (IMG-002/#102)`, `przerwanie po zapisie konta, przed plikiem hasła — ponowienie odzyskuje hasło (#102)`, *Przerwanie provisioningu kont (#102)*

### #105 — Flavor „pod pamięć”: pulpit w przeglądarce + aplikacje GUI (arkusz, zamiennik Prism) i kafelek Leaf  ·  _otwarte_
- `tests/acceptance.d/40-pulpit.sh` — `Metadane: flavor z pulpitem wlb-memory/wlb-radiologia/wlb-histologia (#105, #135, #108)`, `Regresja: obraz bazowy nie ma pulpitu (wlb-memory/wlb-radiologia/wlb-histologia, #105)`, `Regresja: pulpit XFCE nieobecny w obrazie bazowym (#105)`, `Regresja: serwer VNC nieobecny w obrazie bazowym (#105)`, *Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135, wlb-histologia #108) i lekkość bazy (#105)*
- `tests/acceptance.d/45-memory.sh` — `Calc konwertuje CSV->ODS (silnik arkusza, #105)`, *Aplikacje GUI flavora wlb-memory (LibreOffice Calc #105, LabPlot #109, RStudio #108)*
- `tests/desktop-e2e-novnc.py` — *canvas: jednoznaczny selektor #screen canvas (bez fallbacku na dowolny canvas)*
- `tests/unit/changes.bats` — `memory: etykieta build-memory wyzwala flavor na żądanie (#105)`, `memory: zmiana plików flavora wyzwala build+test memory (#105)`, `memory: zmiana spoza flavora nie wyzwala memory (#105)`

### #106 — Pulpit w przeglądarce: rola desktop + flavor wlb-memory (remote-desktop-proxy, kafelek „Pulpit”)  ·  _scalone_
- `tests/acceptance.d/40-pulpit.sh` — `Konfiguracja TigerVNC ma poprawną składnię Perla (#106)`, `Schowek VNC: polityka wrappera wyłącza odbiór (#106)`, `Schowek VNC: polityka wrappera wyłącza wysyłanie (#106)`, *Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135, wlb-histologia #108) i lekkość bazy (#105)*
- `tests/migration.sh` — *Migracja: $(basename "$FROM") -> $(basename "$TO")*

### #107 — Arkusz (open-source Excel): LibreOffice Calc na pulpicie wlb-memory  ·  _scalone_
- `tests/acceptance.d/47-histologia.sh` — `Calc konwertuje CSV->ODS (silnik arkusza, #107)`, *LibreOffice Calc (arkusz) — jak na wlb-memory (#107)*, *Stos histologii: Calc + RStudio + jamovi (#107/#108)*

### #108 — Zamiennik Prism (1/2): statystyka z GUI — jamovi lub JASP  ·  _scalone_
- `tests/acceptance.d/40-pulpit.sh` — `Metadane: flavor z pulpitem wlb-memory/wlb-radiologia/wlb-histologia (#105, #135, #108)`, *Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135, wlb-histologia #108) i lekkość bazy (#105)*
- `tests/acceptance.d/45-memory.sh` — `Calc konwertuje CSV->ODS (silnik arkusza, #105)`, `RStudio Server zainstalowany (rserver, #108)`, `Samodzielna usługa rstudio-server WYŁĄCZONA — dostęp tylko przez hub (#108)`, `jupyter-rsession-proxy w środowisku TLJH — launcher RStudio w JupyterLab (#108)`, *Aplikacje GUI flavora wlb-memory (LibreOffice Calc #105, LabPlot #109, RStudio #108)*
- `tests/acceptance.d/47-histologia.sh` — `RStudio Server zainstalowany (rserver, #108)`, `Samodzielna usługa rstudio-server WYŁĄCZONA — dostęp tylko przez hub (#108)`, `jamovi: dostęp sandboxa do /workspace (override, #108)`, `jamovi: sandbox bwrap startuje (nieuprzywilejowane userns, #63/#108)`, `jupyter-rsession-proxy w środowisku TLJH — launcher RStudio w JupyterLab (#108)`, *RStudio Server (statystyka z GUI w przeglądarce) — jak na wlb-memory (#108)*, *Stos histologii: Calc + RStudio + jamovi (#107/#108)*, *jamovi (Flatpak, #108)*, *jamovi (Flatpak, aplikacja pulpitowa) — #108*
- `tests/unit/changes.bats` — `histologia: etykieta build-histologia wyzwala flavor na żądanie (#108)`, `histologia: zmiana plików flavora wyzwala build+test histologii (#108)`, `histologia: zmiana spoza flavora nie wyzwala histologii (#108)`

### #109 — Zamiennik Prism (2/2): wykresy naukowe + curve-fitting — LabPlot lub SciDAVis  ·  _scalone_
- `tests/acceptance.d/45-memory.sh` — `Integracja GTK3 LibreOffice (render pod XFCE)`, *Aplikacje GUI flavora wlb-memory (LibreOffice Calc #105, LabPlot #109, RStudio #108)*

### #111 — Kernel Julia (luka vs strona JupyterHub IP_CMC)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Kernel Julia (IJulia) zarejestrowany (#111)`, *2. Notebook Python, R i Julia*

### #123 — Bramka etapu 1: nierozwiązane znaczniki konfliktu gita w plikach nielintowanych  ·  _scalone_
- `tests/unit/test_conflict_markers.py` — *Bramka znacznikow konfliktu (#123)*

### #129 — osv-scanner/image-SCA: ekosystem Ubuntu czytany z hosta, nie z VM — asercja VERSION_ID  ·  _scalone_
- `tests/unit/release.bats` — `release.sh: brak dpkg-status zatrzymuje wydanie przed kopiowaniem (#129)`, `release.sh: niezgodna para tozsamosci OS zatrzymuje wydanie (#129)`
- `tests/unit/test_image_identity.py` — `test_main_niezgodnosc_wychodzi_2_kodem`
- `tests/unit/wlb-sbom-gate.bats` — `SBOM bez dpkg-status pada, nie ostrzega (#129)`, `nieznane wydanie obrazu blokuje SBOM niezaleznie od hosta (#129)`, `obca dystrybucja z tym samym VERSION_ID odrzucona (#129)`, `pelna zgodna para tozsamosci przechodzi do skanu (#129)`

### #135 — Flavor wlb-radiologia: pulpit + FSL/FSLeyes/3DSlicer (warstwowy build na #106)  ·  _scalone_
- `tests/acceptance.d/40-pulpit.sh` — `Metadane: flavor z pulpitem wlb-memory/wlb-radiologia/wlb-histologia (#105, #135, #108)`, *Pulpit / flavory z pulpitem (wlb-memory #106, wlb-radiologia #135, wlb-histologia #108) i lekkość bazy (#105)*
- `tests/acceptance.d/70-radiologia.sh` — `Regresja: brak serwera X (Xtigervnc) na flavorze radiologia (#4)`, *Kafelki pulpitu stosu neuro (#135)*, *Stos neuroobrazowania (FSL, FSLeyes, 3DSlicer, #135)*
- `tests/unit/changes.bats` — `radiologia: etykieta build-radiologia wyzwala flavor na żądanie (#135)`, `radiologia: zmiana plików flavora wyzwala build+test radiologii (#135)`, `radiologia: zmiana spoza flavora nie wyzwala radiologii (#135)`
- `tests/unit/image-size-report.bats` — `brak pomiaru jest błędem również bez progu (#135)`, `prawdziwy mały qcow2 daje raport i blokuje zerowy limit (#135)`, `próg jest dziesiętny, dokładny i nie interpretuje wyrażeń Bash (#135)`, `raport: bez progu nie zawodzi nawet dla dużego pliku (#135)`, `raport: brak obrazu lub argumentu to błąd (#135)`, `raport: przekroczenie progu WLB_IMAGE_SIZE_MAX_GIB kończy się błędem (#135)`, `raport: rozmiar poniżej progu przechodzi (#135)`, `raport: wypisuje rozmiar wirtualny i faktyczny w GiB (#135)`

### #138 — Testy wizualne pulpitu (render-smoke → regresja perceptualna), etapami  ·  _otwarte_
- `tests/acceptance.d/45-memory.sh` — `Kafelek LabPlot w menu XFCE`
- `tests/acceptance.d/45-pulpit-render.sh` — `Render-smoke pulpitu nieudany — NIE bramkuje do walidacji KVM (#138 §8): $(tail -n1 `, `Render-smoke: brak wykonywalnego $W45_SMOKE na obrazie (#138)`, *Render-smoke pulpitu (#138, etap 1b — NIE-bramkujący, SKIP przy błędzie)*
- `tests/acceptance.d/99-dr-odtworzenie-bazy.sh` — `Konta u01 i a01 obecne w odtworzonej bazie (#288)`

### #140 — Test behawioralny copy-lockdown pulpitu (schowek + transfer plików noVNC)  ·  _otwarte_
- `tests/acceptance.d/44-copy-lockdown.sh` — `Copy-lockdown #140 VM→host: wynik niejednoznaczny (xclip/RFB harness)`, `Copy-lockdown #140 host→VM: wynik niejednoznaczny (xclip/RFB harness)`, `Copy-lockdown #140: brak komendy startowej jrdp — nie można sprawdzić flag wrappera`, `Copy-lockdown #140: brak konta jupyter-$R1 (test adaptacyjny)`, `Copy-lockdown #140: brak xclip/vncserver/Xtigervnc/xauth — behawioralny test pominięty (TODO: dodać xclip do roli desktop)`, `Copy-lockdown #140: kontrola pozytywna nie przeszła (inject=$W44_POS_INJECT send=$W44_POS_SEND) — wyniki negatywne byłyby niejednoznaczne`, `Copy-lockdown #140: nie można utworzyć katalogu tymczasowego`, `Copy-lockdown #140: sesja VNC przez proxy nie wystartowała (display='${W44_N:-?}'): $(tail -n1 `, **, *Copy-lockdown pulpitu przez ścieżkę proxy (#140 — NIE-bramkujący)*
- `tests/unit/test_channels_matrix.py` — `test_jrdp_pin_is_audited_version`

### #149 — feat(storage): izolacja i limity cgroups dla demona śluzy wyjściowej (sluza-out)  ·  _otwarte_
- `tests/unit/changes.bats` — `śluza: PR i merge_group wymagają integracji bez etykiety (#149)`

### #157 — Testy #65/AppArmor (20-apparmor.sh): expect_fail na complain oblewa POPRAWNY obraz  ·  _scalone_
- `tests/acceptance.d/20-apparmor.sh` — `apparmor-utils zainstalowany (aa-enforce, aa-status)`

### #162 — Decyzje operacyjne eksportu/śluzy przed produkcją (akceptacja warunkowa #147)  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Powód odrzucenia dowiązania czytelny dla badacza (#162)`, `W kolejce nie ma dowiązań ani plików specjalnych (#29)`
- `tests/unit/wlb-sluza-out-mover.bats` — `dowiązanie symboliczne jest odrzucane i usuwane`, `odrzucenie zostawia badaczowi czytelny plik z powodem (#162/IMG-008)`

### #180 — CI: kontrakt zmiennych wdrożeniowych (lab.env ↔ wlb-firstboot ↔ przykłady cloud-init)  ·  _scalone_
- `tests/unit/test_deployment_vars.py` — *kontrakt zmiennych wdrożeniowych (#180)*

### #193 — CD na żywą VM Laboratorium: polityka L/D i bezpieczna aktywacja wersjonowanych narzędzi  ·  _otwarte_
- `tests/acceptance.d/55-python-prefiks.sh` — *Wersjonowany prefiks środowiska Pythona (#193, M0)*

### #199 — wlb-radiologia: wrappery neuro poza PATH sesji XFCE; fsl.sh powiela wpis w PATH  ·  _scalone_
- `tests/acceptance.d/43-kafelki-exec.sh` — `Bramka odrzuca polecenie istniejące tylko w /usr/local/bin (sedno #199, #314)`, `Fixture #199: PATH sesji zawiera /usr/local/bin na tym flavorze — premisa flavor-specific (#314)`, `Kafelek pulpitu: Exec istnieje i jest wykonywalny na PATH sesji (#314)`, `Realny PATH sesji nie zawiera /usr/local/bin (fakt z warstwy jrdp, #199/#202)`, `Realny PATH sesji zawiera /usr/bin (#314)`, *Kafelki pulpitu: Exec → istniejący, wykonywalny cel (#314)*
- `tests/acceptance.d/45-memory.sh` — `LibreOffice obecny (binarka)`
- `tests/acceptance.d/47-histologia.sh` — `Kafelek jamovi wskazuje flatpak run absolutnie (Exec, #199)`, `jamovi zainstalowany w Flatpak (systemowo)`
- `tests/acceptance.d/70-radiologia.sh` — `Kafelek 3DSlicer wskazuje Slicer (Exec)`, `Kafelek FSL wskazuje wrapper absolutnie (Exec, #199)`, `Kafelek FSLeyes wskazuje wrapper absolutnie (Exec, #199)`, `fsl.sh w pełni idempotentny: 2. źródłowanie nie zmienia PATH (#199)`, `Środowisko FSL (profile.d/fsl.sh)`
- `tests/unit/kafelki-exec.bats` — `PATH sesji nie zawiera /usr/local/bin i zawiera /usr/bin (#199/#202)`
- `tests/unit/wlb-e2e-target.bats` — `kafelki .desktop: posiadają poprawny format i absolutne ścieżki Exec (#199, #277)`

### #200 — wlb-radiologia: soft z pierwszego wdrożenia — MRtrix3 (dwidenoise/mp-pca) + czytnik PDF  ·  _scalone_
- `tests/acceptance.d/70-radiologia.sh` — `3DSlicer na PATH (Slicer)`, `Czytnik PDF evince na PATH (#200)`, `Kafelek czytnika PDF w menu (#200)`, `MRtrix3 dwidenoise na PATH (#200)`, `MRtrix3 dwidenoise uruchamia się (-version, #200)`, *Dodatkowe narzędzia (MRtrix3, czytnik PDF, #200)*

### #204 — Pulpit: kontrakt wizualny XFCE — motyw, ikony, fonty, DPI, panel, tapeta, locale  ·  _scalone_
- `tests/acceptance.d/42-pulpit-wartosci.sh` — `Geometria sesji X = $W204_GEO wg kontraktu (xdpyinfo, #204)`, `Kafelek $W204_REQ.desktop obecny na wlb-radiologia (#204)`, `Klawiatura X: ${W204_K%%:*} = ${W204_K#*:} wg kontraktu (setxkbmap, #204)`, `Kontrakt ma znacznik wersji contract|version (#204)`, `Kontrakt xfconf: profil ze /etc/skel = wartości kontraktu (#204)`, `Kontrakt xfconf: scope systemowy = wartości efektywne świeżego konta (#204)`, `Locale $W204_LOCALE działa (locale charmap = UTF-8) (#204)`, `Locale domyślna (LANG) zgodna z kontraktem: $W204_LOCALE (#204)`, `Nadpisane /Xft/DPI=120 NIE przechodzi kontraktu (test negatywny, #204)`, `Nadpisanie badacza (DPI=120) jest respektowane przez xfconf (#204)`, `Nierozwiązywalna nazwa ikony jest odrzucana (test negatywny, #204)`, `Odczyt brakującej właściwości kończy się błędem (#204)`, `Regresja: Xtigervnc nieobecny na flavorze z pulpitem (#204)`, `Serwer X wystartował na $W204_DISP (#204)`, `Zmieniona wartość motywu NIE przechodzi kontraktu (test negatywny, #204)`, `fc-match Monospace = $W204_MONO wg kontraktu (#204)`, `fc-match Sans = $W204_SANS wg kontraktu (#204)`, *Pulpit: kontrakt wizualny XFCE (#204)*, `Żywa sesja XFCE: Xcursor=$W204_CURSOR, Xft.dpi=$W204_DPIVAL (xrdb), ikony=$W204_ICONS, tapeta SOLID pod monitorVNC-0, panel przy dolnej krawędzi (#204)`

### #208 — Śluza wyjściowa: pozytywne potwierdzenie przyjęcia do kolejki (receipt dla badacza)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Badacz widzi katalog /sluza-potwierdzenia (#208)`, `Katalog potwierdzen ma tryb 0750 root:jupyterhub-users (#208)`, `Po przyjeciu pojawia się potwierdzenie (*potwierdzenie.*) (#208)`, `Potwierdzenie czytelne dla badacza i ze zgodnymi etykietami/rozmiarem kontraktu (#208)`, `Potwierdzenie nie zawiera treści pliku — tylko metadane (§14.7, #208)`, `Potwierdzenie własnością badacza, tryb 0640 (#208)`, `Powód odrzucenia dowiązania czytelny dla badacza (#162)`, `Wpis odrzucony (dowiązanie) NIE ma potwierdzenia — tylko powód (#208)`
- `tests/unit/wlb-sluza-out-mover.bats` — `#208: blad zapisu potwierdzenia nie przerywa przyjecia`, `#208: nazwa wpisu z niedozwolonymi znakami jest zakodowana w potwierdzeniu`, `#208: odrzucenie tworzy tylko powód — bez potwierdzenia`, `#208: potwierdzenie nie duplikuje sie i nie zostawia plikow tymczasowych`, `#208: przyjęty katalog dostaje potwierdzenie z liczbą plików, rozmiarem i sha256-inventory`, `#208: przyjęty pojedynczy plik — potwierdzenie z jednym plikiem i jego rozmiarem`, *#208: pozytywne potwierdzenie przyjęcia do kolejki (receipt)*

### #251 — [P0] Firstboot udostępnia hub przed finalizacją kont i audytu, także po awarii  ·  _otwarte_
- `tests/unit/wlb-firstboot.bats` — `awaria finalizacji audytu nie otwiera portu huba ani nie publikuje firstboot.done (#251)`, `awaria po otwarciu huba, przed firstboot.done, zamyka bramkę (trap, #251)`, `firstboot otwiera hub po gotowości kont i finalizacji audytu (#251)`, `wycofanie reguły firstboot HTTP`, `wycofanie reguły firstboot HTTPS`

### #257 — [P0][ci] Code scanning nieaktywny, mimo że CI produkuje SARIF (semgrep/checkov)  ·  _otwarte_
- `tests/unit/scan-status.bats` — `czysty skan: kod 0 zapisany (#257)`, `katalog raportów tworzony, gdy go nie ma (#257)`, `kod wyjścia skanera zapisany i przekazany dalej, także znaleziska (#257)`, `skaner zabity przed zakończeniem: brak pliku .exit, czyli not_run, nie clean (#257)`, `stary raport i status usunięte przed skanem — awaria nie zostawia poprzedniego wyniku (#257)`
- `tests/unit/test_code_scanning_workflow.py` — `test_contract_fixture_excluded_from_main_scans_257`, *dwa raporty, stałe kategorie, publikacja także po znaleziskach (#257)*, *job publikujący nie wykonuje kodu z repozytorium (#257)*, *konteksty zdarzeń i stan publikacji: wykonanie kroków run: joba 3r (#257)*, *potwierdzenie terminalnego statusu sarif-id (#257, review PR #324)*, *uprawnienia: zapis security-events wyłącznie w jobie publikującym (#257)*, *zakres ochrony eksportu: logi i surowe artefakty (#257, review PR #324)*
- `tests/unit/test_ready.py` — *publikacja Code scanning wymagana, gdy etap 3 wykonał skan (#257)*
- `tests/unit/test_sarif_report.py` — `test_prepare_awaria_narzedzia_powod_z_kodu_wyjscia`, `test_prepare_wersja_semgrep_z_semantic_version`, *CLI (#257)*, *allowlist i ochrona eksportu (#257)*, *classify (#257)*, *export_sarif (#257)*, *kontrakt modułu (#257)*, *limity zasobów, dokładne nazwy driverów i weryfikacja sha256 (#257)*, *load_report (#257)*, *prepare: porządki i artefakty CI (#257)*, *prepare: ścieżka szczęśliwa i publikacja (#257)*, *read_exit_code (#257)*, *walidacja elementów i oba narzędzia naraz (#257)*, *wyciszone wyniki (#257)*

### #269 — Standard biurowy pulpitu: LibreOffice Writer (edytor tekstu + OpenDocument)  ·  _scalone_
- `tests/acceptance.d/41-biuro.sh` — `Writer konwertuje .txt->.odt i .odt->.docx (silnik dokumentów, #269)`, *Standard biurowy pulpitu: LibreOffice Writer (#269), czytnik PDF (#270) i edytor tekstu (#272)*

### #270 — Standard pulpitu: przeglądarka PDF (evince) we wspólnej roli desktop  ·  _scalone_
- `tests/acceptance.d/41-biuro.sh` — `Czytnik PDF evince obecny (binarka, #270)`, `Kafelek czytnika PDF w menu XFCE (org.gnome.Evince.desktop, #270)`, `Writer konwertuje .txt->.odt i .odt->.docx (silnik dokumentów, #269)`, `evince-thumbnailer renderuje PDF bez X (smoke silnika PDF, #270)`, *Standard biurowy pulpitu: LibreOffice Writer (#269), czytnik PDF (#270) i edytor tekstu (#272)*

### #271 — Lokalny PostgreSQL + klient GUI bazy (DBeaver / pgAdmin) w standardzie laboratorium  ·  _otwarte_
- `tests/unit/test_check_package_existence.py` — `test_parse_linux_allowlist_skips_out_of_archive`

### #272 — Standard pulpitu: edytor tekstu/kodu w stylu Notepad++ (Geany/odpowiednik) na każdym flavorze  ·  _otwarte_
- `tests/acceptance.d/41-biuro.sh` — `Edytor tekstu mousepad obecny (binarka, #272)`, `Kafelek edytora tekstu w menu XFCE (org.xfce.mousepad.desktop, #272)`, `evince-thumbnailer renderuje PDF bez X (smoke silnika PDF, #270)`, *Standard biurowy pulpitu: LibreOffice Writer (#269), czytnik PDF (#270) i edytor tekstu (#272)*

### #277 — E2E pulpitu: sterowanie input (Playwright → noVNC) nie dociera — focus canvasu / Pointer Events  ·  _otwarte_
- `tests/acceptance.d/40-pulpit.sh` — `Brak targetu E2E: /opt/wlb/e2e nie istnieje w obrazie nie-E2E (#277)`, `Brak targetu E2E: autostart wlb-e2e nie istnieje w obrazie nie-E2E (#277)`, `Brak targetu E2E: kafelek wlb-e2e-mouse nie istnieje w obrazie nie-E2E (#277)`, `Brak targetu E2E: tmpfiles wlb-e2e.conf nie istnieje w obrazie nie-E2E (#277)`, `Regresja: serwer VNC nieobecny w obrazie bazowym (#105)`
- `tests/desktop-e2e-novnc.py` — *scenariusze*
- `tests/unit/kafelki-exec.bats` — `domyślne katalogi wrapperów nie obejmują zwykłych skryptów /opt/wlb (#277)`
- `tests/unit/test_channels_matrix.py` — `test_jrdp_pin_is_audited_version`
- `tests/unit/test_e2e_negative_acceptance.py` — `test_acceptance_40_pulpit_defines_all_four_negative_assertions`, `test_acceptance_negative_assertions_fail_when_any_path_exists`, `test_acceptance_negative_assertions_not_in_e2e_branch`, `test_acceptance_negative_assertions_pass_when_paths_absent`
- `tests/unit/wlb-e2e-target.bats` — `kafelki .desktop: posiadają poprawny format i absolutne ścieżki Exec (#199, #277)`, `keyboard-target.sh: zapisuje każdą odczytaną linię nonce do keyboard.txt (#277)`, `mouse-target.sh: generuje poprawny /run/wlb/e2e/target.json z wymaganymi polami (#277)`, `mouse-target.sh: przelicza geometrię target.json po zmianie ekranu (resize/reconnect, #277 review)`, `mouse-target.sh: zapisuje mouse.txt rc=0 przy kliknięciu OK w zenity (#277)`, `mouse-target.sh: zapisuje rc!=0 przy anulowaniu zenity (#277)`, `session_id: jest trwały i nie zmienia się po wyczyszczeniu markerów (#277)`, `target.json: przechodzi pełną walidację parsera z desktop-e2e-novnc.py (#277)`, `wlb-e2e-tmpfiles.conf: deklaruje katalog /run/wlb/e2e z uprawnieniami 0777 (#277)`
- `tests/unit/wlb-e2e-target.bats` — `kafelki .desktop: posiadają poprawny format i absolutne ścieżki Exec (#199, #277)`, `keyboard-target.sh: zapisuje każdą odczytaną linię nonce do keyboard.txt (#277)`, `mouse-target.sh: generuje poprawny /run/wlb/e2e/target.json z wymaganymi polami (#277)`, `mouse-target.sh: przelicza geometrię target.json po zmianie ekranu (resize/reconnect, #277 review)`, `mouse-target.sh: zapisuje mouse.txt rc=0 przy kliknięciu OK w zenity (#277)`, `mouse-target.sh: zapisuje rc!=0 przy anulowaniu zenity (#277)`, `session_id: jest trwały i nie zmienia się po wyczyszczeniu markerów (#277)`, `target.json: przechodzi pełną walidację parsera z desktop-e2e-novnc.py (#277)`, `wlb-e2e-tmpfiles.conf: deklaruje katalog /run/wlb/e2e z uprawnieniami 0777 (#277)`

### #278 — Sesja pulpitu nie eksportuje XAUTHORITY — natywne apki GUI (LibreOffice) nie startują  ·  _scalone_
- `tests/acceptance.d/46-gui-launch.sh` — `GUI-launch #278: brak konta jupyter-$R1 (test adaptacyjny)`, `GUI-launch #278: brak vncserver/Xtigervnc/xauth/xdpyinfo/xwininfo — test pominięty`, `GUI-launch #278: nie można utworzyć katalogu tymczasowego`, `GUI-launch #278: nie udało się pobrać komendy startowej jrdp`, `GUI-launch #278: okno LibreOffice nie zmapowało się w czasie (wynik niejednoznaczny, nie bramkuje)`, `GUI-launch #278: sesja VNC przez proxy nie wystartowała: $(tail -n1 `, *Asercja 1 (rdzeń #278): sesja wyeksportowała niepuste XAUTHORITY do potomka*, *Asercja 2: natywna apka GUI realnie mapuje okno (nie tylko headless)*, *GUI-launch natywnej apki w sesji pulpitu (#278 — NIE-bramkujący)*
- `tests/acceptance.d/99-dr-odtworzenie-bazy.sh` — `Konta u01 i a01 obecne w odtworzonej bazie (#288)`
- `tests/unit/wlb-desktop-xstartup.bats` — `brak xstartup jrdp -> fallback dbus-launch startxfce4 z eksportem XAUTHORITY (#278)`, `eksportuje żywy XAUTHORITY do potomka sesji (#278)`, `nieustawiony XAUTHORITY -> fallback na \$HOME/.Xauthority (#278)`, `puste XAUTHORITY -> fallback na \$HOME/.Xauthority, też eksportowany (#278)`, `xstartup jrdp niewykonywalny/nieczytelny -> fallback (#278)`, `łańcuchuje do domyślnego xstartup jrdp gdy dostępny (#278)`

### #284 — JupyterLab: wyszarzyć „Save and Export Notebook As” (ścieżka eksportu obok śluzy, #7)  ·  _scalone_
- `tests/acceptance-remote.sh` — `Menu eksportu notebooka wyszarzone w JupyterLab (#284)`, `Przyciski pobierania ukryte w JupyterLab`

### #288 — Testy: domknięcie 5 klas — CIS, izolacja u01, idempotencja Ansible, macierz flavorów, UI JupyterLab  ·  _otwarte_
- `tests/acceptance-remote.sh` — `Brak binariów SUID/SGID w /workspace (#288)`, `Brak groźnych file-capabilities (sys_admin/setuid/dac_override/ptrace/sys_module) (#288)`, `Capabilities: brak getcap (libcap2-bin) na obrazie (#288)`, `Egress ICMP do zewnętrznego IP odrzucony (#288)`, `Egress ICMP/ICMPv6: brak ping w środowisku badacza (#288)`, `Egress ICMPv6 do zewnętrznego IPv6 odrzucony (#288)`, `Egress IPv6/TCP do zewnętrznego hosta odrzucony (#288)`, `Egress UDP/DNS do zewnętrznego resolvera zablokowany (#288)`, `Egress: researcher_egress kończy się reject — default-deny (#288)`, `Egress: ruch badacza (skuid) kierowany do researcher_egress (#288)`, `Eskalacja pkexec: brak pkexec/polkit w środowisku badacza (#288)`, `Eskalacja: /etc/cron.d niezapisywalny dla badacza (#288)`, `Eskalacja: pkexec nie podnosi uprawnień badacza (#288)`, `Obejście pobierania metodą $w6b_m odrzucone 403 (#288)`, `Odczyt $target zablokowany dla badacza (Ring3->Ring0, #288)`, `Odczyt $target: urządzenie nie występuje na obrazie (#288)`, `Odrzucony egress badacza jest logowany (wlb-egress-deny -> SIEM, #288)`, `Zbiór capabilities procesu badacza jest pusty/minimalny (CapBnd/CapEff w /proc/self/status, #288)`, *6b. Aktywne próby izolacji/eskalacji z konta badacza (#288, klasa 2)*, *Izolacja pamięci jądra z Ring 3: siłowa próba odczytu struktur Ring 0 -> odmowa (EACCES/EPERM) (#288)*, `Żaden plik SUID nie jest zapisywalny przez badacza (#288)`
- `tests/acceptance.d/99-dr-odtworzenie-bazy.sh` — `Administrator Klienta a01 loguje się starym hasłem po odtworzeniu (302, #288)`, `Badacz $R1 loguje się przed symulacją awarii (#288)`, `Badacz u01 loguje się starym hasłem po odtworzeniu (302, #288)`, `Baza huba uszkodzona przed procedurą DR (integrity_check, #288)`, `Brak osieroconego dziennika obok odtworzonej bazy (#288)`, `DR: pominięto niszczącą symulację — wcześniejsze asercje nie przeszły (#288)`, `Hub działa i odpowiada na API po odtworzeniu (RB-07b, #288)`, `Hub nieaktywny po zatrzymaniu (#288)`, `Hub odpowiada przed symulacją awarii (#288)`, `Konta u01 i a01 obecne w odtworzonej bazie (#288)`, `Kopia bazy huba na żądanie przed symulacją (#288)`, `Kopia spójna przed symulacją (test -s + integrity_check, #288)`, `Kopia zawiera konta u01 i a01 (#288)`, `Lista kont żywej bazy = kopia (#288)`, `Odtworzona baza = kopia (sha256, #288)`, `Odtworzona baza ma uprawnienia 0600 root:root (#288)`, `Timer kopii bazy wlb-hub-db-backup aktywny po procedurze DR (#288)`, `Uszkodzona baza i jej dziennik w katalogu dowodowym (#288)`, `wlb-hub-db-restore kończy się sukcesem (exit 0, RB-07b, #288)`, *Próba odtworzenia po awarii bazy huba (DR drill, RB-07b, #288)*, `Świeża kopia do odtworzenia istnieje i jest niepusta (#288)`
- `tests/unit/ready.bats` — `ready: build-base w needs blokuje merge przy awarii gdy image=true (#288)`, `ready: build-base w needs zaliczony gdy image=true (#288)`
- `tests/unit/test_idempotency.py` — `test_changed_task_is_reported`
- `tests/unit/wlb-firstboot.bats` — `AUTH_MODE oidc: błąd pobierania discovery przerywa konfigurację (fail-secure, #288)`, `AUTH_MODE oidc: discovery /.well-known/openid-configuration uzupełnia endpointy i generuje config (#288)`, `AUTH_MODE oidc: discovery wymaga https (fail-secure, #288)`

### #292 — Wynoszenie i wnoszenie plików poza śluzą: JupyterLab API, RStudio Files, jamovi Flatpak i kanały klienta  ·  _otwarte_
- `tests/acceptance.d/46-kanaly-eksportu.sh` — *Kanały eksportu/importu (#292 — matryca tests/channels.yaml)*, *RStudio: known_open (brak fixture ścieżek) — tylko raport, nie asercja*, *Self-test harnessu kanałów (#292)*

### #314 — Testy: kafelek pulpitu ↔ Exec ↔ realne uruchomienie (2 warstwy)  ·  _otwarte_
- `tests/acceptance.d/43-kafelki-exec.sh` — `Bramka akceptuje ten sam cel przez ścieżkę absolutną (fixture, #314)`, `Bramka odrzuca polecenie istniejące tylko w /usr/local/bin (sedno #199, #314)`, `Bramka wykrywa absolutny nieistniejący Exec (test negatywny, #314)`, `Bramka wykrywa względny/nieistniejący Exec (test negatywny, #314)`, `Fixture #199: PATH sesji zawiera /usr/local/bin na tym flavorze — premisa flavor-specific (#314)`, `Kafelek pulpitu: Exec istnieje i jest wykonywalny na PATH sesji (#314)`, `Kafelki wlb-*.desktop: brak na tym obrazie (#314)`, `PATH sesji wyprowadzony z realnego środowiska procesu serwera/jednostki (#314)`, `Realny PATH sesji zawiera /usr/bin (#314)`, *Kafelki pulpitu: Exec → istniejący, wykonywalny cel (#314)*
- `tests/unit/kafelki-exec.bats` — `domyślne katalogi wrapperów nie obejmują zwykłych skryptów /opt/wlb (#277)`

### #318 — Sprzątanie scratch sesji w post_stop_hook (scratch-only, deny-lista /workspace+śluza) — z #97  ·  _otwarte_
- `tests/acceptance.d/50-hooki-sesji.sh` — `Emiter sesji trafia do journala z tagiem wlb-session (#97)`, `Kolejka .wlb-export-queue nietknięta (deny-lista, #318)`, `Plik-świadek w /workspace przeżywa sprzatanie (deny-lista, #318)`, `Realny Hub: marker w scratchu usunięty (#97, #318)`, `Realny Hub: nowy scratch sesji utworzony (#97, #318)`, `Realny Hub: scratch ma tryb 0700 (#97, #318)`, `Realny Hub: scratch należy do badacza $R2 (#97, #318)`, `Realny Hub: scratch sesji całkowicie usunięty po stopie (#97, #318)`, `Realny Hub: scratch sesji na tmpfs obecny dla jupyter-$R2 (#97, #318)`, `Realny Hub: zapis pliku-markera w scratchu (#97, #318)`, `Reaping UID-scoped: <host>:77.pid/.log usunięte dla DISPLAY 77 (#318)`, `Reaping UID-scoped: plik .vnc spoza wzorca DISPLAY nietknięty (#318)`, `Reaping UID-scoped: plik badacza keepme.log przeżył (nie blanket *.log, #318)`, `Reaping display-scoped (#318): brak pulpitu/xauth — sprawdzone testami jednostkowymi`, `Reaping display: gniazdo X usunięte dla zwalnianego UID (#318)`, `Reaping display: lock X usunięty (#318)`, `post_stop usuwa scratch w całości (katalog z podkatalogiem, #318)`, `pre_spawn tworzy scratch per-unit na tmpfs i ustawia TMPDIR sesji (#318)`, `scratch należy do UID badacza (10000-59999, #318)`, `xauth: wpis :77 usunięty, plik .Xauthority zachowany (#318)`, *Pełny E2E cykl życia z realnym Hubem (#97, #318)*, `Ścieżka spoza allowlisty nietknięta (test negatywny, #318)`
- `tests/unit/test_wlb_session_hook.py` — `test_denylista_obejmuje_workspace_i_podsciezki`, `test_fail_secure_sprzatanie_nie_wywraca_stopu`, `test_post_stop_usuwa_scratch_rekurencyjnie`, `test_pre_spawn_tworzy_scratch_i_ustawia_TMPDIR`, `test_reap_display_usuwa_tylko_artefakty_wlasciciela`, `test_scratch_nie_powstaje_gdy_sciezka_jest_z_denylisty`, `test_sprzatanie_pomijane_dla_uid_spoza_zakresu`, `test_wlb_ident_normalizuje_unit_name_bez_sufiksu`, `test_wlb_ident_wola_ensure_user_gdy_konto_jeszcze_nie_istnieje`

### #340 — Testy mutacyjne: kontrakty abstrakcji i polimorfizm implementacji (etap 4b)  ·  _otwarte_
- `tests/unit/test_deployment_vars.py` — *wartości aktywne w przykładach wdrożenia (#340)*
- `tests/unit/wlb-firstboot.bats` — `kontrakt reguł firstboot HTTP`, `kontrakt reguł firstboot HTTPS`, `wycofanie reguły firstboot HTTP`, `wycofanie reguły firstboot HTTPS`

### #349 — CI: zarządzanie testami niestabilnymi (flaky) — metryki per test, kwarantanna i polityka retry  ·  _otwarte_
- `tests/unit/test_flaky_report.py` — `test_cli_output_write_error`, `test_cli_parse_fail_closed_on_malformed`, `test_cli_parse_fail_closed_on_missing`, `test_cli_parse_success`, `test_direct_execution_subprocess`, `test_parse_acceptance_sample`, `test_parse_direct_testcase_under_testsuites`, `test_parse_empty_file_fail_closed`, `test_parse_error_and_failure_text_only_and_empty`, `test_parse_error_status_distinguished`, `test_parse_explicit_source_stage`, `test_parse_invalid_root_element_fail_closed`, `test_parse_malformed_fail_closed`, `test_parse_missing_file_fail_closed`, `test_parse_missing_testcase_name_fail_closed`, `test_parse_oserror_handling`, `test_parse_pytest_subtests_multi_failure`, `test_parse_skipped_with_reason`, `test_parse_testsuites_hierarchy`, `test_parse_time_fallback`

## Uwagi

- **Mapa pokazuje testy z jawnym znacznikiem `#NN`.** Wiele zachowań jest pokrytych testami bez odwołania do zgłoszenia (pełny zestaw jednostkowy bats/pytest w `tests/unit/`, akceptacja e2e w `tests/acceptance-remote.sh`, migracja w `tests/migration-remote.sh`). Brak wiersza nie znaczy „brak testu”, lecz „brak znacznika” — przy nowych poprawkach dodawaj `#NN` w tytule/sekcji testu, aby trafił do mapy.
- **Dryf zamrożonych wersji** (np. `markupsafe`) pilnuje test dryfu w etapie 5 oraz nocny pełny build (harmonogram `CI`) — to również forma regresji, łapiąca zmiany spoza repozytorium, zanim uderzą w PR.

