# Runbook CI: co robić, gdy pipeline nie przechodzi

Kiedy PR nie przechodzi, job **„Gotowe do code review”** dołącza sekcję **„Diagnoza przebiegu”**.
Każdy nieudany job ma tam jedną z kategorii opisanych niżej i link do właściwej sekcji tego dokumentu.
Tę samą diagnozę można uruchomić lokalnie:

```bash
GITHUB_TOKEN=$(gh auth token) python3 ci/ci_failures.py diagnose --repo xWuWux/wlb-golden-image --run-id <ID>
gh run view <ID> --log-failed        # logi nieudanych kroków
gh run download <ID> -D build/ci-run # artefakty: integration-logs, security-reports, coverage…
```

## Zasady

1. **Każdy etap działa pod strażnikiem** (`ci/guard.sh`) z limitem czasu i pamięci. Pamięć jest
   ograniczona do całej pamięci maszyny minus 1 GB, więc proces, który się rozrośnie, zostaje zabity
   sam, a agent runnera przeżywa, zapisuje logi i artefakty. Każdy wynik trafia do
   `build/ci-logs/guard.jsonl` i do adnotacji przebiegu.
2. **Automatycznie ponawiane są tylko awarie infrastruktury,** jeden raz i tylko dla najnowszego
   commita (`.github/workflows/ci-retry.yml`). Błędów testów, OOM ani przekroczeń czasu nie ponawiamy,
   bo zwykle wynikają z kodu i powtórzą się.
3. **Kroki raportowe nie blokują** (`--optional`), np. skan podatności pakietów w obrazie.
   Ich niepowodzenie jest ostrzeżeniem.
4. **Nie obniżamy progów** (pokrycie, budżety wydajności, limity) po to, żeby przeszedł PR.
   Zmiana progu wymaga uzasadnienia w opisie PR.

## test

**Błąd testu lub narzędzia.** Krok zakończył się kodem różnym od zera.

1. Otwórz nieudany krok. Skrypty `ci/*.sh` kończą się listą „Nie przeszło”, a każda pozycja ma
   komunikat `BŁĄD: …` w logu.
2. Odtwórz błąd lokalnie tym samym poleceniem:

   | Etap | Lokalnie | Typowe przyczyny |
   |---|---|---|
   | 1 | `make lint` (`FIX=1 make lint` poprawia formatowanie) | formatowanie, shellcheck, ansible-lint |
   | 2 | `make check` | składnia Packera/Ansible, schemat cloud-init, reguły nft |
   | 3 | `make security` | nowe CVE w zamrożonych wersjach, licencja spoza polityki |
   | 3.5 | `make observability` | zmieniony format logu bez aktualizacji `observability/contract.yml` |
   | 4 | `make unit` | test jednostkowy, spadek pokrycia poniżej progu |
   | 5 | `make integration` (KVM) | budowanie obrazu, kryterium akceptacji, migracja, dryf locków, SIEM |

3. Dla etapu 5 pobierz artefakt `integration-logs`. W `build/ci-logs/` są:
   `acceptance.log` (wynik każdego kryterium), `migration.log`, `*-journal.log` (dziennik VM),
   `*-serial.log` (konsola VM), `packer.log` (budowanie) i `siem.log` (co dotarło do testowego SIEM).
   Przy nieudanym `wlb-firstboot` jego ostatnie wpisy są też w logu joba.
4. Popraw kod. Jeśli znalazłeś nowy rodzaj błędu, dopisz go do listy w `przewodnik-vm.sh bledy`.

## oom

**Brak pamięci.** Strażnik zabił proces po przekroczeniu limitu (adnotacja `OOM: <etap>`).

1. Sprawdź w `guard.jsonl`, który krok i przy jakim limicie został zabity.
2. Zmierz zużycie lokalnie, zawsze z limitem, żeby nie zablokować własnej maszyny:
   ```bash
   ci/guard.sh --name pomiar --memory 3G --timeout 10m -- <polecenie>
   ```
3. Najpierw zmniejsz zużycie (dziel dane na mniejsze porcje, pomijaj niepotrzebne wejście).
   Dopiero potem podnoś limit albo przenoś krok na większy runner.

Przykład: `osv-scanner` dla `dpkg-status` (około 1000 pakietów Ubuntu) przekraczał 3 GB w niecałą minutę.
Na runnerze z 7 GB zabijał agenta GitHub Actions („The operation was canceled”, brak artefaktów).
Rozwiązanie polegało na usunięciu tego wejścia ze skanu. Pakiety systemowe są aktualne z definicji,
a w `image-release` zapisywane jest `PENDING_UPGRADES`.

## timeout

**Przekroczony limit czasu** (adnotacja `TIMEOUT: <etap>` albo `timeout-minutes` joba).

1. W logu znajdź ostatni wypisany krok. Tam proces utknął.
2. Typowe przyczyny w etapie 5: VM nie wstaje (zob. `*-serial.log`), `cloud-init` czeka na sieć,
   pobieranie pakietów z zewnętrznego serwera jest bardzo wolne.
3. Podnoś limit tylko wtedy, gdy krok naprawdę potrzebuje więcej czasu. Uzasadnienie wpisz w PR.
   Telemetria CI (`ci-telemetry`, p90 czasu jobów) pokazuje, czy czas rośnie stopniowo.

## infra

**Awaria infrastruktury.** Runner przerwał job bez błędu testu: „The operation was canceled”,
utrata runnera, krok oznaczony jako `cancelled`, choć nikt przebiegu nie anulował. Do tej kategorii
należą też runner bez KVM (adnotacja `INFRA:` z `ci/enable-kvm.sh`) oraz przejściowe błędy usług zewnętrznych, np. HTTP 504 z `releases.hashicorp.com`
przy instalacji Packera, timeouty, błędy DNS czy limity API. Narzędzia CI pobiera `ci/install-tools.sh`,
który sam ponawia pobieranie (`curl --retry-all-errors`) i sprawdza sumy SHA-256.

1. **Nic nie rób od razu.** `ci-retry.yml` ponawia nieudane joby automatycznie, jeden raz.
2. Jeśli ponowienie też padnie, awaria się powtarza, więc to raczej nie przypadek:
   - uruchom etap lokalnie pod strażnikiem i zmierz pamięć (zob. [oom](#oom)). Brak pamięci całej
     maszyny wygląda z zewnątrz dokładnie jak awaria infrastruktury,
   - sprawdź stan GitHub Actions: https://www.githubstatus.com,
   - ręczne ponowienie: `gh run rerun <ID> --failed`.
3. Jeśli awaria dotyczy ciągle tego samego kroku, oznacz go jako problem do zbadania (issue)
   i dopisz obejście do przewodnika.

## cancelled

**Anulowane.** Nowszy commit w PR przerwał poprzedni przebieg (`cancel-in-progress`) albo ktoś
anulował go ręcznie. Nic nie trzeba robić, liczy się najnowszy przebieg.
Jeśli nie chcesz przerywać długiego etapu 5, wypychaj zmiany dopiero po jego zakończeniu.
