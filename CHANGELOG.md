# Changelog

Istotne zmiany w golden image VM Laboratorium (WLB). Format wzorowany na
[Keep a Changelog](https://keepachangelog.com/pl/1.1.0/); wersjonowanie obrazu —
[SemVer](https://semver.org/lang/pl/). Numery `#NN` odsyłają do zgłoszeń i PR-ów
w repozytorium `xWuWux/wlb-golden-image`. Decyzje architektoniczne mają własne
rekordy w [`docs/adr/`](docs/adr/).

Obraz nie ma jeszcze wydania produkcyjnego — `image_version` domyślnie `0.0.0-dev`.
Projekt jest na etapie **MVP lokalnego** (budowa i akceptacja na WSL2/KVM, przed
pierwszym Laboratorium na klastrze).

---

## Niewydane

- **Normalizator raportów JUnit i testów niestabilnych (#349, PR A2):** dodano moduł `ci/flaky_report.py`
  parsujący i normalizujący raporty JUnit XML z etapu 4 (pytest) oraz etapu 5 (akceptacja VM). Moduł
  działa w trybie fail-closed, obsługuje wielokrotne znaczniki `<failure>` w pojedynczym `<testcase>`
  (subtesty pytest), rozróżnia `<error>` i `<skipped>`, mapuje stabilne `test_id` oraz zapisuje
  znormalizowany JSON do `build/ci-logs/flaky-raw.json`.

- **Kontrakty mutacyjne (#340)** — etap 4b osobno sprawdza przykłady wdrożenia oraz HTTP/HTTPS firstboot.

- **Testy cyklu życia sesji badacza i osieroconych sesji (#97):** wdrożono testy jednostkowe
  w `tests/unit/test_wlb_session_hook.py` dla domykania osieroconych sesji (`interrupted`)
  przy restarcie huba (rejestracja w `wlb-usage-record` z zachowaniem starego UUID, pusty `stop_wall`,
  start nowej sesji z nowym UUID i odporność na uszkodzone pliki JSON). W `ansible/roles/tljh/templates/80-wlb-session.py.j2`
  znormalizowano nazwę jednostki (`.service`) oraz dodano obsługę `tljh.user.ensure_user` przy pierwszym spawnie
  badacza, zapewniając poprawne utworzenie scratcha i emisję UID w `wlb-session-log`. W `tests/lib/remote-common.sh`
  dodano funkcję `hub_stop` zamykającą serwer badacza przez API JupyterHub ze sprzątaniem tymczasowego tokenu API.
  Rozszerzono test akceptacyjny `tests/acceptance.d/50-hooki-sesji.sh` o pełny cykl życia E2E z realnym Hubem
  (start serwera, uprawnienia scratch 0700 na tmpfs, emisja `session_start`, asercja pliku-markera, stop przez API huba,
  weryfikacja usunięcia scratcha, markera i stanu, skorelowany `session_stop` z czasem trwania, ponowny spawn
  z nowym identyfikatorem sesji oraz zabezpieczenie sesji badacza przez trap/finally).

- **Procedura DR i odtwarzanie bazy huba (`wlb-hub-db-restore`, #306, #288):** aktualizacja runbooków
  `docs/runbooks/RB-07-odtworzenie-po-awarii.md` (RB-07b) oraz `docs/runbook-kopia-bazy-huba.md`:
  wywołanie skryptu `/usr/local/sbin/wlb-hub-db-restore` jako jednego źródła prawdy procedury DR
  (opcje CLI `--from`, `--no-start`, zmienne środowiskowe, kody wyjścia 0–6); ujednolicenie procedury
  awaryjnej/fallbacku na wyszukiwanie kopii przez `find` (odporne na format i spacje), sprawdzanie niepustości
  kopii (`test -s`) przed `integrity_check`, zabezpieczenie dowodowe (`mv` bazy i dzienników `-wal`, `-shm`,
  `-journal` do katalogu dowodowego) przed jakąkolwiek podmianą, zatrzymanie timera `wlb-hub-db-backup.timer`
  oraz procedura rollbacku w razie niepowodzenia. Dodano ostrzeżenie operacyjne dotyczące okna RPO (do 1h)
  i konieczności uzgodnienia przywróconych/usuniętych kont z autorytatywnym rejestrem źródłowym. Zarejestrowano
  skrypty `wlb-hub-db-backup` i `wlb-hub-db-restore` w `SHELL_SCRIPTS` (`ci/common.sh`) oraz zdeduplikowano wpisy
  #288 w mapie testów (`99-dr-odtworzenie-bazy.sh`). Testy: `tests/unit/wlb-hub-db-restore.bats` (7 przypadków,
  w tym kontrola negatywna — brak powrotu huba daje exit 6 i rollback), `tests/fixtures/sqlite_hot_journal.py`
  + `tests/unit/test_sqlite_hot_journal.py` (prawdziwy gorący `-journal`) oraz 4 mutacje w
  `ci/mutations/bash-mutations.tsv`.

- **Dryf locka: `pkgconf` w obrazie, brak w zamrożeniu (odblokowanie etapu 5):** obraz (conda)
  zawiera `pkgconf 3.0.11` jako zależność, której nie było w `envs/python/environment.lock.yml` —
  `ci/lock_drift.py` słusznie zgłaszał `DRYF: pkgconf tylko w obrazie` i blokował etap 5 na **wszystkich**
  PR-ach. Dopisano `pkgconf=3.0.11` do sekcji conda locka (lock = obraz). Klasa jak soupsieve (#311).
- **Logowanie przez Microsoft Entra ID (`AUTH_MODE=entra`, #18):** `WlbEntraAuthenticator`
  (podklasa `AzureAdOAuthenticator`, oauthenticator 17 z TLJH 2.0) loguje na konto wskazane
  w rejestrze przypisań `(tid, oid) -> konto` (`/etc/wlb/entra-accounts`, root 0600, tylko
  identyfikatory) i wymaga roli aplikacji Laboratorium (`ENTRA_REQUIRED_ROLE`). Claim osobowy
  (UPN, e-mail) nie staje się loginem. Zakresy `openid profile` (`oid` wymaga `profile`), ale imię i UPN są odrzucane po odczycie. Sprawdzane są tenant,
  issuer, audience i ważność id_token. `allow_all` nie da się włączyć. Pierwsze logowanie trwale wiąże konto z osobą,
  a przekazanie konta innej osobie jest zablokowane do czasu procedury z odwołaniem poświadczeń (#102 D3).
  Usunięcie wiersza z rejestru blokuje nowe logowania i żądania podlegające odświeżeniu, ale nie zamyka trwających
  połączeń (pełne odcięcie: zatrzymanie serwera). Konta, dane i hasła Native się nie zmieniają. Migracja to procedura
  w oknie serwisowym (zatrzymanie serwerów, rejestr, `AUTH_MODE=entra`), powrót to `AUTH_MODE=native` po resecie
  haseł kont z odebranym dostępem (runbook `RB-entra`). Testy są modułowe (podstawiona odpowiedź tokenu);
  odbiór z tenantem testowym opisuje IMG-011.
  `wlb-firstboot` waliduje całość przed zmianą na VM. Wzór: `cloud-init/examples/lab-user-data-entra.yaml`.
- **Odwołanie poświadczeń przy zmianie sposobu logowania (`wlb-hub-revoke`, #18):** przy każdej zmianie
  `AUTH_MODE` (stan w `/workspace/.wlb-hub/auth-mode`), także przy powrocie do haseł, `wlb-firstboot` przed otwarciem
  huba zatrzymuje hub i serwery kont, zmienia `cookie_id` kont i usuwa ich tokeny API/OAuth oraz kody OAuth. Ciasteczka
  i tokeny z logowania hasłem nie przechodzą więc po migracji na Entra, także po pierwszym logowaniu tej samej osoby
  przez Entra. Plik powiązań kont z osobami zakłada firstboot; jego brak w trakcie pracy wstrzymuje logowanie,
  a odtworzenie bez niego wymaga świadomej reinicjalizacji (`WLB_ENTRA_REINIT=1`, z odwołaniem wszystkich poświadczeń).
  Zdarzenia logowania Entra mają kody przyczyn i pseudonimy (oid albo skrót loginu), bez loginów.
- **`AUTH_MODE=oidc` naprawiony (P0 z audytu #18):** bez `OIDC_ALLOWED_GROUPS` firstboot kończy
  się błędem przed zmianą, zamiast generować `allow_all = True` (dostęp dla każdego użytkownika IdP).
  Konfiguracja z grupami uruchamia się na oauthenticator 17: wcześniej hub nie startował
  (`claim_groups_key requires manage_groups`). Teraz generowane jest `manage_groups` + `auth_state_groups_key`.

- **Target in-session dla testów E2E pulpitu (#277-A):** deterministyczny in-session
  target weryfikacji wejścia myszy i klawiatury w sesji noVNC. Katalog markerów
  `/run/wlb/e2e` (tmpfs 0777, root) z deskryptorem `/run/wlb/e2e/target.json`
  (schema `wlb.e2e-target/v1`, trwały `session_id`, `screen.w/h`, współrzędne przycisku
  `button.x/y/w/h` w pikselach ekranu oraz tytuł okna `keyboard.title`).
  Target myszy `/opt/wlb/e2e/mouse-target.sh` uruchamia `zenity --question`,
  pozycjonuje okno deterministycznie przez `wmctrl`, oblicza współrzędne przycisku OK
  i zapisuje `rc=0` do `/run/wlb/e2e/mouse.txt`. Target klawiatury
  `/opt/wlb/e2e/keyboard-target.sh` w `xfce4-terminal` z fokusem X zapisuje odebrany
  nonce do `/run/wlb/e2e/keyboard.txt`. Skrypt `/opt/wlb/e2e/target-runner.sh`
  zapewnia autostart w sesji XFCE (`/etc/xdg/autostart/wlb-e2e-target.desktop`)
  oraz kafelek w menu (`/usr/share/applications/wlb-e2e-mouse.desktop`). Target instalowany
  WYŁĄCZNIE dla buildów testowych/E2E pod flagą roli `wlb_enable_e2e_target: true`
  (domyślnie wyłączony, nieobecny w obrazie produkcyjnym badacza).

- **Koniec losowych czerwonych bramki SIEM w etapie 5:** forwarding VM→testowy SIEM (rsyslog/TLS)
  jest asynchroniczny — zdarzenie śluzy `sluza_out.export_request` potrafiło dotrzeć sekundy po tym,
  jak akceptacja w VM już przeszła, a `siem_delivery`/`siem_wazuh` sprawdzały log jednorazowo (wyścig;
  pod obciążeniem/OOM bramka czerwieniła się losowo, mimo że dekoder/reguła w etapie 3.5 były OK).
  Dodano polling na dotarcie realnego + podrobionego wpisu (≥2 wystąpienia) z deadline'em
  (`WLB_SIEM_WAIT`, domyślnie 60 s) przed weryfikacją — `verify-log`/Wazuh pozostają jedynym wyrokiem,
  to tylko cierpliwość, bez zmiany semantyki bramki.

- **Koniec konfliktów mapy testów przy równoległych PR-ach:** `.gitattributes` oznacza
  `docs/mapa-testy-zgloszenia.md merge=union` — ten generowany plik (`ci/mapa-testy.py`) dotykany
  przez wiele PR-ów scala się zachowując wiersze z obu stron, zamiast konfliktować N-stronnie.
  Docelowo regeneracja w CI znormalizuje kolejność.
- **Wyniki SAST/IaC w GitHub Code scanning (#257):** raporty SARIF `semgrep` i `checkov` z etapu 3
  trafiają do zakładki Security (kategorie `semgrep`/`checkov`), z adnotacjami w PR, także gdy etap 3
  jest czerwony od znalezisk. `ci/security.sh` zapisuje kod wyjścia każdego skanera i usuwa stary
  raport przed skanem; `ci/sarif_report.py` klasyfikuje wynik (`clean`/`findings`/`error`/`not_run`),
  waliduje SARIF (także notyfikacje `level: error` = analiza niekompletna), eksportuje go z jawnej allowlisty
  pól (sekret z `p/secrets` nie trafia do GitHuba ani do treści wyniku) i zapisuje manifest z wersją skanera
  i skrótem reguł. Surowe SARIF nie trafiają do artefaktów, a log semgrepa/bandita nie zawiera kodu.
  Job 3r potwierdza w API terminalny status przetworzenia (`complete`) każdego `sarif-id` i skrót każdego
  raportu z manifestem. Nowe sprawdzenie etapu 3 „Kontrakt SARIF” uruchamia przypięte semgrep/checkov na
  fixture `tests/fixtures/sarif-contract/` (celowe znaleziska i canary) i sprawdza cały łańcuch eksportu. Publikuje osobny job „3r” — jedyny z `security-events: write`,
  bez wykonywania kodu z repo. Polityka: raport, nie druga bramka; brak publikacji blokuje „Gotowe do
  code review” jako błąd infrastruktury. Runbook: `docs/ci-runbook.md#code-scanning`.

- **Koniec konfliktów CHANGELOG przy równoległych PR-ach:** `.gitattributes` oznacza
  `CHANGELOG.md merge=union` — git scala sekcję „Niewydane" zachowując wpisy z obu stron
  zamiast zgłaszać konflikt. Automatyzuje dotychczasową ręczną regułę „zachowaj wszystkie wpisy",
  także na przycisku merge w GitHub. Przy wydaniu warto sprawdzić kolejność wpisów (union może je poprzeplatać).

- **Testy izolacji Ring3->Ring0 (#288, klasa 2):** rozszerzenie sekcji 6b w `tests/acceptance-remote.sh`
  o aktywne próby naruszenia granic uprawnień jądra z przestrzeni badacza:
  kontrola file-capabilities rozszerzona o `cap_sys_module`, nowa asercja weryfikująca zbiór capabilities
  procesu badacza (`CapEff=0` i `CapAmb=0` w `/proc/self/status`), oraz odmowa odczytu urządzeń pamięci
  i portów jądra (`/dev/mem`, `/proc/kcore`, `/dev/kmem`, `/dev/port`) kończąca się błędem uprawnień
  (`EACCES`/`EPERM`). Brak opcjonalnego urządzenia na obrazie jest zgłaszany jako `SKIP` (fail-secure).

- **E2E UI JupyterLaba w przeglądarce (#288, klasa 5):** nowy `tests/jupyterlab-e2e.py` na tym samym
  stacku Playwrighta co E2E pulpitu (`.tools/venv-e2e`, `ci/install-tools.sh e2e`) dowodzi tego, czego
  nie widać w grepie configu: badacz `u01` loguje się przez formularz Huba i dostaje działający
  JupyterLab. Scenariusze: kafelki Launchera (Python/R/Julia/Help, a Desktop/RStudio zależnie od
  flavora — baza bez GUI to regresja lekkości #105), kernele Python i R liczą `1+1` z UI (Julia, gdy
  kafelek jest), file browser tworzy/edytuje/zapisuje plik (weryfikacja po ponownym otwarciu),
  Download i eksport notebooka są zablokowane w DOM (#284), a `/hub/admin` zwraca 403 i nie ma do
  niego linku. Krok canvasu/wejścia pulpitu zostaje w `tests/desktop-e2e-novnc.py` (#206/#277) — ten
  test tylko pilnuje kafelka. Wpięty w etap 5 obok E2E pulpitu, za bramką `WLB_JLAB_GATING=1`
  (lub `WLB_E2E_GATING=1`); flavor z nazwy logu akceptacji.
- **Sprzatanie scratcha sesji w post_stop_hook (#318):** `pre_spawn` tworzy dedykowany scratch
  per-unit na tmpfs (`/run/wlb/scratch/<unit>`, właściciel = UID badacza) i wstawia go do środowiska
  sesji jako `TMPDIR`; `post_stop` usuwa go w całości. Artefakty X/VNC są reapowane **UID-scoped**
  (właściciel = UID 10000–59999): gniazda/locki X w `/tmp`, pliki TigerVNC `<host>:<d>.pid/.log`
  w `~/.vnc` skorelowane z reapowanym DISPLAY oraz wpis `xauth` dla tych DISPLAY; cały `.Xauthority`
  nie jest usuwany. **Znana granica:** hook nie zna realnie zwalnianego DISPLAY (spawner go nie
  niesie w `post_stop`), więc przy współbieżnych sesjach tego samego UID reapuje artefakty wszystkich
  sesji tego UID. **Deny-lista:** `/workspace` i wszystko pod nim (zwłaszcza `.wlb-export-queue` —
  kolejka eksportu #20) nigdy nie jest czyszczone rekurencyjnie; jedyny, wąski wyjątek to pliki
  TigerVNC w `~/.vnc` skorelowane z DISPLAY — blanket `*.pid`/`*.log` nie jest usuwany (dane badacza
  zostają). Sprzatanie jest fail-secure (awaria = warning, nie blokuje stopu), idempotentne
  i name-agnostic. Testy: jednostkowe w `tests/unit/test_wlb_session_hook.py` (scratch/TMPDIR,
  deny-lista, reaping tylko skorelowanych plików, fail-secure, zakres UID) oraz akceptacyjne w
  `tests/acceptance.d/50-hooki-sesji.sh` (scratch znika, plik-świadek w `/workspace`, w kolejce
  i `~/.vnc/keepme.log` zostaje, ścieżka spoza allowlisty nietknięta).

- **Test dryfu wersji bez fałszywych alarmów (#277/#304):** `ci/lock_drift.py` porównuje wersje
  semantycznie (PEP 440), a nie znakowo. Lock (pip) zapisuje `soupsieve==4.0.0`, a `conda env export`
  w obrazie podaje `4.0` — to to samo wydanie, więc pin jest spełniony i pip nic nie doinstalowuje.
  Wcześniej taki zapis czerwienił etap 5 jako `DRYF` (po bumpie bezpieczeństwa soupsieve), mimo że
  obraz był zgodny z lockiem. Wersje nieparsowalne nadal porównujemy znakowo, a realna różnica
  (np. `4.0.1` vs `4.0.0`) pozostaje błędem.
- **E2E pulpitu bez fałszywych bramek (#277, część B):** `tests/desktop-e2e-novnc.py` nie rozstrzyga
  już o wejściu po diffie pikseli ani liczniku `WebSocket.send` — jedno i drugie jest **wyłącznie
  diagnostyką** w `result.json` (progu diffu nie kalibrujemy). Bramką jest *skutek* wejścia odczytany
  out-of-band z VM: klawiatura wpisuje świeży nonce i root porównuje go z `/run/wlb/e2e/keyboard.txt`,
  mysz klika konkretny przycisk targetu (geometria z `/run/wlb/e2e/target.json`, odświeżona tuż przed
  akcją) i root czyta `/run/wlb/e2e/mouse.txt` (`rc=0`). Katalog markerów czyści się przed każdą akcją.
  Scenariusze launcher/render/pointer/keyboard/resize/reconnect są rozstrzygane niezależnie (mysz OK
  nie zalicza klawiatury), a Launcher→Desktop to wymagany scenariusz bez fallbacku `goto /desktop/`.
  Viewport jest dopasowywany do `target.screen` z kalibracją wysokości paska noVNC (bez zgadywania
  stałej), a resize zmienia go tylko na czas scenariusza i przywraca przed akcją myszy — przy
  `rfb.resizeSession=true` framebuffer X idzie za oknem, więc target publikowany przy starcie
  opisywałby nieaktualną geometrię.
  Wynik v3 (`status: pass|fail|error`, pole `gating`) powstaje na każdej ścieżce, także po deadline;
  test czyta markery jako root (lokalnie `sudo -n` albo `WLB_E2E_SSH`) i wymaga realnego zaufania do
  `WLB_E2E_CA` (tymczasowy NSS DB + `certutil`) — niezaufany certyfikat to ERROR, nie
  `--ignore-certificate-errors`. Etap 5 przekazuje SSH/CA oraz `WLB_E2E_DESKTOP=absent|required`:
  baza jest bezpulpitująca, a flavory (memory, radiologia, histologia) wołają akceptację z `required`.
- **Bramka regresji utwardzenia Lynis (#288):** etap 5 nadal domyślnie tylko raportuje
  (`hardening_index`, ostrzeżenia, sugestie), ale `WLB_LYNIS_GATING=1` promuje wynik do bramki:
  spadek `hardening_index` poniżej `WLB_LYNIS_BASELINE` (domyślnie 72) albo dowolne `warning[]`
  czerwieni etap. Brak raportu przy włączonej bramce = fail-closed. Nie wymagamy absolutnego 100 —
  pilnujemy regresji względem bieżącego baseline. Parser i bramka mają testy offline na fixture
  `tests/fixtures/lynis-report.dat`.
- **Standard biurowy pulpitu — LibreOffice Writer (#269):** edytor tekstu (`.odt`/`.docx`) w roli
  `desktop`, czyli na **każdym** flavorze z pulpitem (memory, histologia, radiologia) — decyzja PO:
  Opcja A, bez wyjątku. Instalowane `libreoffice-writer` + `libreoffice-gtk3` (natywny VCL pod XFCE);
  bez Impress/Base i bez metapakietu `libreoffice`. Pakiet jest przed końcowym sweepem AppArmor,
  więc profil `soffice` z `libreoffice-common` trafia od razu w enforce (CIS 1.6.3). Kafelek stockowy
  `libreoffice-writer.desktop`. Akceptacja `41-biuro.sh`: binarka + kafelek + GTK3 + smoke
  `.txt`→`.odt`→`.docx` (silnik dokumentów, nie tylko `--version`). Koszt: radiologia zyskuje biuro
  (~+240 MB warstwy) — świadomie zaakceptowane.

- **Standard biurowy pulpitu — czytnik PDF (evince) (#270):** przeglądarka dokumentów PDF
  przeniesiona z `neuro_apps` (#200) do ogólnej roli `desktop`, dzięki czemu czytnik PDF jest
  dostępny na **każdym** flavorze z pulpitem (memory, histologia, radiologia) bez podwójnej
  instalacji (deduplikacja). Instalowany pakiet `evince` przed końcowym sweepem AppArmor (CIS 1.6.3).
  Kafelek stockowy `/usr/share/applications/org.gnome.Evince.desktop`. Akceptacja w `41-biuro.sh`:
  weryfikacja binarki, kafelka w menu XFCE oraz headless smoke renderowania PDF bez środowiska
  graficznego (`evince-thumbnailer`).

- **Standard biurowy pulpitu — edytor tekstu Mousepad (#272):** lekki graficzny edytor tekstu
  i kodu (GTK3, podświetlanie składni, numeracja linii) w roli `desktop` na **każdym** flavorze
  z pulpitem (memory, histologia, radiologia) jako linuksowy odpowiednik Notepad++ dla badacza.
  Instalowany pakiet `mousepad` przed końcowym sweepem AppArmor (CIS 1.6.3). Kafelek stockowy
  `/usr/share/applications/org.xfce.mousepad.desktop`. Akceptacja w `41-biuro.sh`.

- **Macierz flavorów i integracja CI (#288):**
  - Uruchomiono nocny harmonogram w `.github/workflows/ci.yml` ostrożnie raz w tygodniu (`0 3 * * 2`, wtorki 03:00 UTC) zsynchronizowany co do znaku z `NIGHTLY_CRON` w `ci/changes.sh`.
  - Etap 5 rozdzielony na jednokrotną budowę bazy `build-base` (`ci/integration.sh build-base` z zapisem `output/` do cache `actions/cache/save`) oraz macierz `integration` (`strategy.matrix` po `flavor: [general, memory, histologia, radiologia]`, `fail-fast: false`, `max-parallel: 2`) odtwarzającą bazę z cache (`actions/cache/restore`).
  - Dodano wariant akceptacji cloud-init dla instalacji pakietów z lokalnego mirrora (`RESEARCHER_PACKAGE_INSTALL=mirror`, `tests/cloud-init/user-data-mirror.yaml`) z asercjami proxy sink.
  - Dodano obsługę i testy fail-secure firstboota dla `AUTH_MODE=oidc` z automatycznym pobieraniem konfiguracji z `/.well-known/openid-configuration` (`OIDC_DISCOVERY_URL`), zachowując blokadę runtime (#18, brak produkcyjnego IdP) w testach akceptacyjnych.
- **Statyczna bramka kafelek → Exec (#314 część A):** nowy fragment akceptacji
  `tests/acceptance.d/43-kafelki-exec.sh` sprawdza **każdy** `/usr/share/applications/wlb-*.desktop`:
  parsuje `Exec=`, odcina field-codes (`%f %F %u %U %i %c %k`), bierze pierwszy token i wymaga
  ścieżki absolutnej albo rozwiązania na **PATH sesji XFCE/jrdp** — nie roota (root ma
  `/usr/local/bin`, sesja go nie ma, #199/#202; `command -v` roota dawał fałszywy zielony).
  Cel musi istnieć i być wykonywalny, a wrapper WLB (`/usr/local/bin`, `/opt/wlb`) musi wskazywać
  istniejący cel (m.in. `fsleyes`/`fsl` przez `FSLDIR`). Do tego **obowiązkowy test negatywny**:
  kopia kafelka ze złym `Exec` musi dać FAIL. Headless i deterministyczna → bramkuje etap 5 (`ko`).
  Parser w `tests/lib/kafelki-exec.sh`, testy jednostkowe `tests/unit/kafelki-exec.bats` (15).

- **Idempotencja Ansible w etapie 5 (#288, klasa 3):** po pierwszym provisioningu VM drugi przebieg
  `ansible/site.yml` jest uruchamiany na tej samej maszynie, a PLAY RECAP musi dać **changed=0**
  (bramka `ci/idempotency.py`, testy `tests/unit/test_idempotency.py`). Żeby bramka była realna,
  przejrzano taski raportujące zmianę przy każdym przebiegu: cache apt wydzielony do osobnego
  tasku z `changed_when: false` (9 miejsc — bezsporny no-op cache'a), a taski, które **realnie
  pracują**, raportują changed przez **sondę różnicy** (hash pliku przed/po), nie przez maskowanie:
  Julia (`Manifest.toml.generated`), pakiety R (`renv.lock.generated`), `R CMD javareconf`
  (`/etc/R/Renviron.site`), `flatpak override` (plik overrides/<app>), `pip` („Successfully
  installed”), `conda env update` („All requested packages already installed”). Eksport locka
  condy zapisuje plik tylko przy `cmp` różnicy, a `fetch`/log diagnostyczny condy to kopie
  artefaktów, nie stan VM. Strefa czasowa używa modułu `timezone`. Blok wersjonowanego prefiksu
  Pythona (#193) jest pomijany, gdy prefiks jest już dowiązaniem — inaczej drugi przebieg
  przełączałby hub.
  **Koszt obserwowalności (znana granica):** sonda widzi tylko zmiany plików, które hashuje —
  np. samo precompile Julii bez zmiany Manifestu albo zmiana cache'ów w `JULIA_DEPOT_PATH` nie
  zostanie zaraportowana jako `changed`; bramka pilnuje no-opu playbooka, nie pełnego stanu
  wewnętrznego narzędzi.

- **E2E wejścia pulpitu w przeglądarce (#277):** krok interakcji `tests/desktop-e2e-novnc.py` przestał
  być best-effort i **deterministycznie potwierdza reakcję** pulpitu. Przyczyną fałszywego
  `before == after` była próbka: czytała tylko lewy-górny róg 200×200, a prawy klik trafiał w ~(640,400)
  — menu xfdesktop powstawało poza próbką, a zrzut robiono już po `Escape`. Teraz porównujemy **pełny
  bufor** canvasu (próg na piksel + minimalna liczba zmienionych pikseli), klikamy przez
  `locator.click(position=…)` (bez ręcznego offsetu paska noVNC) i fotografujemy menu, zanim `Escape`
  je zamknie. Dodatkowo opakowany `WebSocket.send` liczy komunikaty RFB (`PointerEvent`/`KeyEvent`),
  więc wynik rozróżnia „zdarzenie nie dotarło do noVNC” od „noVNC wysłał, pulpit nie zareagował”.
  Krok jest domyślnie wymagany (`WLB_E2E_INTERACTION=required`; `optional`/`off` = tryb raportowy),
  a etap 5 nadal nie bramkuje całości bez `WLB_E2E_GATING=1`. `result.json` ma teraz `status: pass|fail`
  (schemat v2) i sekcję `interaction` z różnicą pikseli, bounding boxem i licznikami RFB.
- **Testy mutacyjne w CI:** nowy blokujący etap **4b** (`ci/mutation.sh`) sprawdza, czy testy
  naprawdę wykrywają błędy, a nie tylko „przechodzą”. Python: `mutmut` mutuje
  `ci/verify_platform_images.py` i uruchamia jego testy; próg `PYTHON_MUTATION_MIN` (domyślnie 85%)
  liczy się z mutantów pokrytych testami („no tests” nie wchodzi do mianownika; globalny próg
  pokrycia etapu 4 nie pilnuje pojedynczego pliku — to znana luka do domknięcia testami `main()`),
  a timeout mutanta jest błędem. Przeżyty mutant spoza allowlisty (`ci/mutations/python-allowlist.txt`
  — tylko mutanty równoważne, z uzasadnieniem) czerwieni pipeline. Powłoka: własny harness
  `ci/mutation-bash.sh` z tabelą `ci/mutations/bash-mutations.tsv` — każda celowa mutacja skryptu
  obrazu (np. reguła huba fazy 2 usunięta, brak znacznika `firstboot.done`, odwrócony warunek
  sweepu AppArmor) MUSI zostać zabita przez wskazany test bats; baseline przed mutacją wymaga
  dokładnie jednego zielonego testu, więc zepsuty test nie udaje „killed”. `--check` pilnuje, że
  fragment do mutacji występuje w pliku dokładnie raz. Lokalnie: `make mutation`.
  Runbook: [docs/ci-runbook.md](docs/ci-runbook.md#mutation).

- **Anty-halucynacja pakietów apt (#294):** etap 3 sprawdza także pakiety OS z zadań Ansible
  (`apt:`/`ansible.builtin.apt`) wobec oficjalnego indeksu Ubuntu noble (noble/updates/security,
  wszystkie komponenty, nazwy wirtualne z `Provides`). Piny wersji są obcinane, nazwy z Jinja
  bez literalnej pętli są raportowane jako pominięte, a pakiety spoza archiwum (PPA/.deb) mają
  allowlistę z uzasadnieniem. Oracle to jednorazowy indeks `Packages.xz` zamiast ~80 zapytań
  do Launchpada na PR (Launchpad rate-limituje i pojedyncze strony timeoutują).
- **Architektura WLB (#226):** [diagramy cyklu życia, kontrakty i macierz odbioru](docs/architektura-wlb.md).
- **AppArmor w warstwie pulpitu (#65, CIS 1.6.3):** rola `desktop` wymusza enforce **po**
  wszystkich swoich pakietach — skrypt `wlb-apparmor-enforce` (`/usr/local/sbin`) przełącza
  profile pozostawione w complain (XFCE/TigerVNC/noVNC oraz aplikacje GUI dokładane w tej
  warstwie, np. planowany LibreOffice Writer z #269). Wcześniej sweep był tylko w
  `memory_apps`/`histo_apps`, więc flavor, który dostał profil w complain od pakietu warstwy
  pulpitu, nie schodził do licznika 0 wymaganego przez `20-apparmor.sh` (dotyczyło to m.in.
  radiologii, gdzie `libreoffice-common` wnosi profil `soffice` w complain). Testy: bats
  (7 przypadków — idempotencja, śmieci z `aa-status`, JSON bez nazw, `aa-enforce` bez efektu,
  profil bez pliku) oraz adaptacyjny `40-pulpit.sh` (realny przebieg skryptu + complain = 0).
  Na radiologii sweep jest no-opem: `base` enforce'uje wcześniej, a pakiety pulpitu nie
  wnoszą profili w complain — bez nowych pakietów.
- **Kontrakt wizualny pulpitu (#204):** wartości wyglądu XFCE (motyw/ikony/kursor/fonty/DPI/
  panel/tapeta/locale/klawiatura/geometria) z jednego źródła w `ansible/group_vars/all.yml`;
  wdrożenie jako systemowe domyślne xfconf (`/etc/xdg/xfce4/...`, bo konta badacza powstają
  `useradd -M`) + `/etc/skel` + plik `/etc/wlb/desktop-contract` dla testów. Akceptacja
  `42-pulpit-wartosci.sh` porównuje wartości efektywne (xfconf-query, xrdb/xfsettingsd,
  fc-match, xdpyinfo, setxkbmap, locale) i rozwiązywalność `Icon=` launcherów; testy
  negatywne dla zmienionej/brakującej wartości i martwej ikony. Kopiowanie ikony FSLeyes
  bez cichego fallbacku (brak pliku = błąd budowy). Kontrakt ma wersję
  (`desktop_contract_version`). Uwaga: `LANG=C.UTF-8` w `/etc/default/locale` jest zmianą
  systemową (formaty, sortowanie, komunikaty), nie tylko pulpitu.

- **Śluza wyjściowa (#208):** pozytywne potwierdzenie przyjęcia do kolejki — po udanym
  przyjęciu badacz znajdzie w `/sluza-potwierdzenia` (0750, jak `/sluza-odrzucone`) plik
  `*.potwierdzenie.*` z metadanymi: liczba plików, łączny rozmiar, `sha256-inventory` i
  identyfikator wniosku; treść (0640, właściciel UID) tylko dla właściciela. Potwierdzenie
  = przyjęcie do kolejki, NIE zgoda na eksport (#20); błąd zapisu potwierdzenia nigdy nie
  przerywa przyjęcia. Prywatność jak `/sluza-odrzucone`: nazwa pliku widoczna dla grupy przez
  listowanie katalogu, treść wyłącznie dla właściciela. Testy bats + akceptacja VM;
  [runbook](docs/runbooks/RB-eksport-kolejka.md).

- **Pulpit (#106/#135):** poprawna składnia konfiguracji TigerVNC na Ubuntu 24.04;
  test rzeczywistego uruchomienia i parametrów blokujących schowek w izolowanym kontenerze.

- **Lokalne metryki stanu (#22):** timer `wlb-health`, agregaty kolejki, spoolu SIEM,
  miejsca, auditd i chrony oraz kontrola kontraktu na odpowiedzi node_exportera.
  Brak zdalnego scrape i alertowania; [runbook](docs/runbooks/RB-wlb-health.md).

- **Ekspozycja metryk dla monitoringu (#22):** opcjonalny `MONITORING_CIDR` (jeden kanoniczny adres
  `/32`) w `lab.env` i narzędzie `wlb-monitoring apply|disable|status` do zmiany na działającej VM —
  bez `wlb-firstboot --force` i bez zamykania huba. Reguła portu 9100 w osobnym łańcuchu
  `monitoring_in` (atomowe `nft -f`, utrwalenie przez `include`), eksporter poza pętlą zależny od zapory
  (`PartOf` + guard w `ExecStartPre`), weryfikacja gniazda i automatyczne cofnięcie przy błędzie.
  Etap 5: próba sieciowa z dozwolonego i innego źródła oraz kontrola identyfikatorów badaczy w pełnej
  odpowiedzi eksportera; `metrics_check.py` zgłasza też nieznane metryki `wlb_*`. Wyłączony kolektor
  `systemd` eksportera (wypisywał jednostki `jupyter-<login>.service` badaczy). Model i odstępstwo
  od OPZ CH.8: [IMG-010](docs/adr/IMG-010-monitoring.md); procedura: [RB-monitoring](docs/runbooks/RB-monitoring.md).
  Nadal brak alertingu po stronie monitoringu i `/hub/metrics`.

- **SIEM / Wazuh (#17):** dekodery RFC 5424, reguły zdarzeń i audytu oraz testy
  na menedżerze Wazuh dla próbki i logu integracyjnego. Instrukcja i ograniczenia:
  [`observability/siem/wazuh/README.md`](observability/siem/wazuh/README.md).
  Retencja oraz wdrożenie i weryfikacja w środowisku docelowym pozostają do uzgodnienia.

## Stan obecny (2026-10-29)

**Czym jest obraz.** Niezmienne (immutable) qcow2 na bazie Ubuntu 24.04 z
[TLJH](https://tljh.jupyter.org/) / JupyterHub 5 (Python + R/HADES + Julia w jednej
sesji JupyterLab). Budowany warstwowo: Packer + QEMU/KVM, provisioning Ansible,
kompresja równoległa zstd. Dane badacza i baza huba żyją na osobnym dysku roboczym;
sam obraz jest wymienny (aktualizacja = podmiana obrazu, workspace zostaje).

**Flavory (warstwy na bazie `wlb-general`):**

| Flavor | Zawartość | Status |
|---|---|---|
| `wlb-general` | baza: hub, kernele, hardening, śluza, obserwowalność | **gotowy** — baza zielona (akceptacja 144/0) |
| `wlb-memory` | + pulpit w przeglądarce (XFCE/noVNC) + GUI pod analizę pamięciową | PoC pulpitu (#106) gotowy; aplikacje GUI w toku (#105) |
| `wlb-radiologia` | + pulpit + stos neuroobrazowania (FSL, FSLeyes, 3DSlicer) | **gotowy technicznie**; zostaje certyfikujący build + kafelki pulpitu (#135) |
| `wlb-histologia` | + pulpit + RStudio + Calc + jamovi (Flatpak) | **gotowy, CI-zielony** (etap 5: Calc/RStudio/jamovi + smoke sandboxa userns #108) |

**Bezpieczeństwo i zgodność (wdrożone):** hub bez sudo w sesji badacza
(SystemdSpawner, `NoNewPrivileges`), TLS huba wymuszony (#18/IMG-005), wymuszony
CIDR dostępu, AppArmor w trybie enforce (#65), sysctl/hardening CIS, izolacja i
limity cgroups demona śluzy wyjściowej (#149), kontrakt obserwowalności + przekaz
do SIEM, skan OVAL/USN CVE jądra (#3), model kont i zakres Administratora Klienta
rozstrzygnięte w ADR-ach (IMG-002, IMG-003).

**Pipeline CI (6 etapów):** 1 lint/sekrety · 2 build-check · 3 bezpieczeństwo (SAST/IaC/SCA/licencje)
· 3.5 kontrakt obserwowalności · 4 testy jednostkowe + pokrycie · 5 integracja na KVM
(build bazy + akceptacja MVP + migracja + dryf locków). Flavor radiologia ma własną
bramkę opt-in (#167).

**Jak zacząć:** budowa i pierwszy test — [`docs/pierwsze-uruchomienie.md`](docs/pierwsze-uruchomienie.md);
konta badaczy i administracja — [`docs/przewodnik-administratora.md`](docs/przewodnik-administratora.md).

---

## [Nieopublikowane]

Zmiany scalone do `main`, jeszcze bez tagu wydania.

### Pulpit i flavory
- **Flavor `wlb-memory`**: rola `memory_apps` na warstwie pulpitu — **LibreOffice Calc** (arkusz,
  warstwa arkuszowa zamiennika Prism), natywny render GTK3 pod XFCE; stockowy kafelek w menu.
  Pierwsza aplikacja GUI #105; kolejne (jamovi, LabPlot/SciDAVis, kafelek Leaf) dojdą do tej roli (#105).
  Etap 5 buduje i testuje `wlb-memory` opt-in (etykieta `build-memory` / zmiana plików flavora / nocny
  build; `WLB_BUILD_MEMORY`) — akceptacja potwierdza LibreOffice Calc i konwersję CSV→ODS na obrazie.
- **Flavor `wlb-radiologia`**: pulpit + FSL/FSLeyes/3DSlicer na warstwie na `wlb-general` (#135, #137).
  Naprawa budowy (błędna flaga instalatora FSL), dopasowanie `run-local` do dużego obrazu (#164),
  komplet bibliotek Qt xcb dla 3DSlicer + smoke faktycznego uruchomienia GUI (#4), bramka CI opt-in (#167).
  Narzędzia z pierwszego wdrożenia: **MRtrix3** (`dwidenoise`/mp-pca, pipeline dMRI) i **evince**
  (czytnik PDF na pulpicie) w roli `neuro_apps` (#200).
- **Flavor `wlb-histologia`**: drugi flavor z pulpitem — **LibreOffice Calc** (#107), **RStudio**
  (R-IDE w przeglądarce przez `jupyter-rsession-proxy`) i **jamovi** przez **Flatpak** na pulpicie (#108).
  jamovi instaluje się z Flathub w warstwie build (ma sieć) i działa lokalnie w runtime (egress zamknięty);
  sandbox jamovi dostaje dostęp do `/workspace`, kafelek XFCE ma absolutny `Exec` (#199). Etap 5 buduje i
  testuje flavor opt-in (`build-histologia` / zmiana plików / nocny build; `WLB_BUILD_HISTOLOGIA`) —
  akceptacja potwierdza Calc (CSV→ODS), RStudio oraz jamovi, w tym **gatingowy smoke startu sandboxa bwrap
  przez nieuprzywilejowane userns** na utwardzonym noble (#63/#65). Build: [RB-build-wlb-histologia.md](docs/runbooks/RB-build-wlb-histologia.md).
- **Rola `desktop` i PoC pulpitu w przeglądarce** (`wlb-memory`): remote-desktop-proxy, XFCE, TigerVNC/noVNC,
  kafelek „Pulpit", render-smoke (#106/#113, #138/#139).
- Kompresja obrazów równoległym zstd zamiast jednowątkowego zlib (#71/#165).

### Obraz bazowy i środowisko badacza
- `prometheus-node-exporter` udostępnia metryki lokalnie na `127.0.0.1:9100`; integracja z siecią monitoringu pozostaje osobnym etapem (#22).
- Jedno jądro w obrazie — purge starych `linux-*` (#9/#89).
- Kernel Julia (IJulia) w bazie + naprawy rejestru/hangów budowy (#111 i pochodne).
- Biblioteki DICOM/neuroobrazowania dla badaczy: pydicom (+gdcm), oro.dicom, nibabel, dcm2niix, snakemake (#128/#133).
- Jawny przełącznik instalacji pakietów przez badacza: `deny`/`mirror` (#23/IMG-004/#159).
- Hooki cyklu życia sesji badacza + korelacja sesji w SIEM (#97/#114).

### Bezpieczeństwo i zgodność
- Opcjonalny wydłużony limit sesji per-Laboratorium: `MAX_SESSION_HOURS` (1–48) w `lab.env` — `wlb-firstboot`
  spójnie ustawia `cull.max_age` oraz TTL ciasteczka/tokenu (`11-wlb-session.py`). Domyślnie 12 h; >12 h to
  świadome odstępstwo §9.5 (dłuższe okno re-auth). Nie czyni obliczenia odpornym na awarię — checkpoint
  dalej konieczny. Runbook podmiany na działającej VM: `docs/runbooks/RB-sesja-48h.md` (#78).
- Konta stanowiskowe `u01`…`uNN` i Administrator Klienta `a01` tworzone przez `wlb-firstboot`
  (`RESEARCHER_ACCOUNTS`), samodzielna rejestracja wyłączona (IMG-002 Faza 1, #102/#185).
  Loginy `u01`–`u99` zarezerwowane dla badaczy; hasło początkowe przez plik `.pending`, więc
  przerwany start nie zostawia konta z nieznanym hasłem. Rejestr przypisań osoba↔konto
  i przekazanie stanowiska pozostają otwarte (#102 Faza 2).
- Wymuszony CIDR dostępu + TLS huba, inkrement 1 (#18/IMG-005/#161).
- AppArmor: dokładny tryb profilu z `aa-status --json`, wymuszenie enforce (#65, #155/#156/#158/#163).
- Sysctl sieciowe + wyłączenie zrzutów pamięci (CIS 1.x/3.x, #63/#94).
- Izolacja i limity cgroups demona śluzy wyjściowej (#149/#153).
- Prywatne kopie i manifest eksportu v1 — podstawa śluzy (#20/#147); decyzje operacyjne w #162.
- Skan OVAL Canonical (USN) obrazu — widoczność CVE jądra niezależnie od osv-scanner (#3/#130).

### CI/CD i jakość
- Rozbicie testów akceptacyjnych na fragmenty `tests/acceptance.d/` — koniec konfliktów append (#127).
- Etap 5 buduje tylko bazę (`-only`), nie flavory równolegle (#144); allowlista na prawdziwym proxy — koniec SKIP (#16/#93).
- Bramka znaczników konfliktu gita + hak pre-commit (#123/#124); trigger Merge Queue (#121).
- Kontrakt zmiennych wdrożeniowych w etapie 3.5 (`ci/deployment_vars.py`): `/etc/wlb/lab.env`,
  `cloud-init/lab.env.example` i przykład `cloud-init/lab-user-data.example.yaml` muszą się zgadzać
  z tym, co czyta `wlb-firstboot` — obraz stawia się wiele razy, a rozjazd parametru był dotąd
  widoczny dopiero na VM. Przykład wdrożenia uzupełniony o `AUTH_MODE`, `LOCAL_TEST_MODE`
  i wzory limitów zasobów.
- Bieżące podbicia zależności i locków pod skan SCA (wiele PR-ów dependabot/ręcznych).

### Decyzje architektoniczne (ADR)
- Faza 1: ADR-y decyzji blokujących pierwsze lokalne Laboratorium (#145), w tym:
  IMG-001 (model VM i limity), IMG-002 (model kont badaczy — docelowo bezosobowe `uNN`),
  IMG-003 (ograniczony zakres Administratora Klienta), IMG-004 (instalacja pakietów),
  IMG-005 (dostęp TLS), IMG-006 (zamknięcie Laboratorium), IMG-007 (przepełnienie logów audytu).
- IMG-009 (integralność plików / AIDE): bez AIDE jako świadome odstępstwo od CIS L1 — dysk systemowy
  jednorazowy, integralność wydania przez SHA-256/SBOM (#12); 3 reguły CIS zapisane w
  `docs/hardening-exceptions.yml` (#68).

---

## Jak prowadzić ten plik

- Każdy PR zmieniający zachowanie obrazu, procedurę lub bezpieczeństwo dopisuje punkt do
  sekcji **[Nieopublikowane]** pod właściwym nagłówkiem, z numerem `#NN`.
- Przy wydaniu: zamień **[Nieopublikowane]** na `## [wersja] – RRRR-MM-DD`, załóż nowy pusty
  blok Nieopublikowane i zaktualizuj „Stan obecny".
- Kategorie: _Dodane_, _Zmienione_, _Naprawione_, _Bezpieczeństwo_, _Usunięte_ — albo
  podział tematyczny jak wyżej, gdy wydań jeszcze nie ma.
