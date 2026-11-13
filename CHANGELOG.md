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

- **Sprzatanie scratcha sesji w post_stop_hook (#318):** `pre_spawn` tworzy dedykowany scratch
  per-unit na tmpfs (`/run/wlb/scratch/<unit>`, właściciel = UID badacza) i wstawia go do środowiska
  sesji jako `TMPDIR`; `post_stop` usuwa go w całości. Artefakty display-scoped (gniazda/locki X
  w `/tmp`, `~/.vnc/*.pid|*.log`, wpis `xauth` dla zwalnianego DISPLAY) są reapowane **tylko** dla
  właściciela o UID 10000–59999; cały `.Xauthority` nie jest usuwany. **Deny-lista absolutna**:
  `/workspace` i wszystko pod nim (zwłaszcza `.wlb-export-queue` — kolejka eksportu #20) nigdy nie
  jest czyszczone rekurencyjnie. Sprzatanie jest fail-secure (awaria = warning, nie blokuje stopu),
  idempotentne i name-agnostic. Testy: jednostkowe w `tests/unit/test_wlb_session_hook.py`
  (scratch/TMPDIR, deny-lista, reaping display, fail-secure, zakres UID) oraz akceptacyjne w
  `tests/acceptance.d/50-hooki-sesji.sh` (scratch znika, plik-świadek w `/workspace` i w kolejce
  zostaje, ścieżka spoza allowlisty nietknięta).

- **Test dryfu wersji bez fałszywych alarmów (#277/#304):** `ci/lock_drift.py` porównuje wersje
  semantycznie (PEP 440), a nie znakowo. Lock (pip) zapisuje `soupsieve==4.0.0`, a `conda env export`
  w obrazie podaje `4.0` — to to samo wydanie, więc pin jest spełniony i pip nic nie doinstalowuje.
  Wcześniej taki zapis czerwienił etap 5 jako `DRYF` (po bumpie bezpieczeństwa soupsieve), mimo że
  obraz był zgodny z lockiem. Wersje nieparsowalne nadal porównujemy znakowo, a realna różnica
  (np. `4.0.1` vs `4.0.0`) pozostaje błędem.
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
- **Bramka regresji utwardzenia Lynis (#288):** etap 5 nadal domyślnie tylko raportuje
  (`hardening_index`, ostrzeżenia, sugestie), ale `WLB_LYNIS_GATING=1` promuje wynik do bramki:
  spadek `hardening_index` poniżej `WLB_LYNIS_BASELINE` (domyślnie 72) albo dowolne `warning[]`
  czerwieni etap. Brak raportu przy włączonej bramce = fail-closed. Nie wymagamy absolutnego 100 —
  pilnujemy regresji względem bieżącego baseline. Parser i bramka mają testy offline na fixture
  `tests/fixtures/lynis-report.dat`.
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
