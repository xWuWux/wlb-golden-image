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
- **Flavor `wlb-radiologia`**: pulpit + FSL/FSLeyes/3DSlicer na warstwie na `wlb-general` (#135, #137).
  Naprawa budowy (błędna flaga instalatora FSL), dopasowanie `run-local` do dużego obrazu (#164),
  komplet bibliotek Qt xcb dla 3DSlicer + smoke faktycznego uruchomienia GUI (#4), bramka CI opt-in (#167).
- **Rola `desktop` i PoC pulpitu w przeglądarce** (`wlb-memory`): remote-desktop-proxy, XFCE, TigerVNC/noVNC,
  kafelek „Pulpit", render-smoke (#106/#113, #138/#139).
- Kompresja obrazów równoległym zstd zamiast jednowątkowego zlib (#71/#165).

### Obraz bazowy i środowisko badacza
- Jedno jądro w obrazie — purge starych `linux-*` (#9/#89).
- Kernel Julia (IJulia) w bazie + naprawy rejestru/hangów budowy (#111 i pochodne).
- Biblioteki DICOM/neuroobrazowania dla badaczy: pydicom (+gdcm), oro.dicom, nibabel, dcm2niix, snakemake (#128/#133).
- Jawny przełącznik instalacji pakietów przez badacza: `deny`/`mirror` (#23/IMG-004/#159).
- Hooki cyklu życia sesji badacza + korelacja sesji w SIEM (#97/#114).

### Bezpieczeństwo i zgodność
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
- Bieżące podbicia zależności i locków pod skan SCA (wiele PR-ów dependabot/ręcznych).

### Decyzje architektoniczne (ADR)
- Faza 1: ADR-y decyzji blokujących pierwsze lokalne Laboratorium (#145), w tym:
  IMG-001 (model VM i limity), IMG-002 (model kont badaczy — docelowo bezosobowe `uNN`),
  IMG-003 (ograniczony zakres Administratora Klienta), IMG-004 (instalacja pakietów),
  IMG-005 (dostęp TLS), IMG-006 (zamknięcie Laboratorium), IMG-007 (przepełnienie logów audytu).

---

## Jak prowadzić ten plik

- Każdy PR zmieniający zachowanie obrazu, procedurę lub bezpieczeństwo dopisuje punkt do
  sekcji **[Nieopublikowane]** pod właściwym nagłówkiem, z numerem `#NN`.
- Przy wydaniu: zamień **[Nieopublikowane]** na `## [wersja] – RRRR-MM-DD`, załóż nowy pusty
  blok Nieopublikowane i zaktualizuj „Stan obecny".
- Kategorie: _Dodane_, _Zmienione_, _Naprawione_, _Bezpieczeństwo_, _Usunięte_ — albo
  podział tematyczny jak wyżej, gdy wydań jeszcze nie ma.
