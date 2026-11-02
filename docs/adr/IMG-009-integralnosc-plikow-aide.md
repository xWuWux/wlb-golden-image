# IMG-009: Integralność plików systemowych (AIDE) na jednorazowym dysku — udokumentowane odstępstwo

* **Status:** Przyjęta
* **Data:** 2026-11-02
* **Autorzy / decyduje:** Właściciel Platformy
* **Powiązania:** OPZ: profil CIS Ubuntu 24.04 L1 Server · Regulamin: §21 (rozliczalność) · Zgłoszenia/PR: #68, #12 (SHA-256 + SBOM przy wydaniu), #11 (raport skanu utwardzenia), #14 (odstępstwa) · ADR: IMG-003 (ograniczony Administrator Klienta) · Pliki: `docs/hardening-exceptions.yml`

## Kontekst i problem

Profil **CIS Ubuntu 24.04 L1 Server** wymaga AIDE — trzy reguły: `package_aide_installed`, `aide_build_database`, `aide_periodic_checking_systemd_timer`. W obrazie WLB AIDE nie ma, więc skan utwardzenia (#11) raportuje te reguły jako niespełnione.

AIDE to narzędzie do wykrywania nieautoryzowanych zmian plików na **trwałym** systemie. Model WLB jest inny: dysk systemowy Laboratorium jest **jednorazowy i niezmienny** — wymiana obrazu = nowy dysk, pliki systemowe są niezmienne z definicji, a integralność wydania weryfikujemy **sumą SHA-256 i SBOM przy wydaniu obrazu** (#12). Realna luka to wyłącznie zmiany wprowadzane przez Administratora Platformy w **żywym** systemie — dziś śladem są jedynie reguły audytu konfiguracji (`wlb_*`) i `execve` badaczy, bez bazy integralności plików.

## Rozważane opcje

1. **Opcja A — bez AIDE, udokumentowane odstępstwo.** Najtaniej, spójne z „Brak automatycznych aktualizacji" i modelem immutable. Integralność wydania przez SHA-256/SBOM (#12), zmiany konfiguracji przez reguły audytu `wlb_*`, ograniczony admin (IMG-003). Nie wykrywa zmian plików na żywym systemie poza audytem konfiguracji.
2. **Opcja B — AIDE z bazą budowaną przy `wlb-firstboot`** i timerem rzadkim (np. tygodniowo). Łapie zmiany admina na żywym systemie, ale: baza musi powstawać przy firstboot (nie w obrazie — montują się udziały), wymaga wykluczeń katalogów zmiennych (`/var/log`, `/workspace`, `/sluza-*`), nowego zdarzenia w kontrakcie obserwowalności, buildu i testu etapu 5. Przy immutable-disk wartość ograniczona, koszt i ryzyko fałszywych alarmów realne.
3. **Opcja C — AIDE „offline".** Porównanie z sumami kontrolnymi z wydania (#12) przy starcie VM, bez pakietu. Średni koszt; również kończy się udokumentowanym odstępstwem dla 3 reguł CIS.

## Decyzja

**Opcja A — bez AIDE, świadome udokumentowane odstępstwo.** Na jednorazowym, niezmiennym dysku systemowym baza integralności plików dubluje gwarancje, które już mamy taniej i pewniej: weryfikacja SHA-256 + SBOM przy wydaniu (#12), reguły audytu konfiguracji (`wlb_*`), sesje badaczy bez sudo i ograniczony Administrator Klienta (IMG-003). Odstępstwo dla trzech reguł CIS zapisujemy w `docs/hardening-exceptions.yml` z uzasadnieniem i odnośnikiem do tego ADR, aby raport skanu (#11) traktował je jako świadome, a nie milczące.

Decyzja jest odwracalna: gdy pojawi się realny wymóg audytu zmian plików na żywym systemie, wracamy do Opcji B (zakres „Do zrobienia" w #68 pozostaje gotowy).

## Odstępstwo od specyfikacji

* **Czy stanowi odstępstwo:** Tak.
* **Uzasadnienie / cytat:** CIS Ubuntu 24.04 L1 Server wymaga AIDE (`package_aide_installed` i reguły pochodne). Odchodzimy, bo dysk systemowy jest immutable i jednorazowy, a integralność wydania weryfikuje SHA-256/SBOM przy wydaniu (#12) — AIDE na trwałym systemie rozwiązuje problem, którego ten model nie ma.

## Konsekwencje

* **Pozytywne:** brak pakietu i timera AIDE (prostszy, lżejszy obraz); brak fałszywych alarmów z katalogów zmiennych; spójność z modelem immutable i z weryfikacją wydania (#12); odstępstwo jest jawne i rozliczalne.
* **Negatywne / dług techniczny:** zmiany plików systemowych wprowadzone przez Administratora Platformy na **żywym** systemie nie są wykrywane przez bazę integralności (pozostają reguły audytu konfiguracji `wlb_*` i rozliczalność SSH). Mitygacja: ograniczony admin (IMG-003), re-image przy aktualizacji kasuje ewentualny dryf, SHA-256/SBOM przy każdym wydaniu. Do zrobienia: przy przyszłej integracji raportu skanu (#11) konsumować `docs/hardening-exceptions.yml`, żeby te 3 reguły pokazywały się jako odstępstwo.
* **Świadomie pominięte:** pakiet `aide`, baza przy firstboot i timer `aidecheck` (Opcja B); porównanie offline z sumami wydania (Opcja C).
