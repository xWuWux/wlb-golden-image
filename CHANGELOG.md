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
