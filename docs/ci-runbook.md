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
   | 3.5 | `make observability` | zmieniony format logu bez aktualizacji `observability/contract.yml`, nowa zmienna `lab.env` bez wpisu w `cloud-init/lab.env.example` i w przykładzie user-data |
   | 4 | `make unit` | test jednostkowy, spadek pokrycia poniżej progu |
   | 5 | `make integration` (KVM) | budowanie obrazu, kryterium akceptacji, migracja, dryf locków, SIEM |

3. Dla etapu 5 pobierz artefakt `integration-logs`. W `build/ci-logs/` są:
   `acceptance.log` (wynik każdego kryterium), `migration.log`, `*-journal.log` (dziennik VM),
   `*-serial.log` (konsola VM), `packer.log` (budowanie) i `siem.log` (co dotarło do testowego SIEM).
   Przy nieudanym `wlb-firstboot` jego ostatnie wpisy są też w logu joba.
   W `build/artifacts/<wersja>/` są zamrożone locki z obrazu oraz `conda-env-update.log` — przebieg
   `conda env update`, po którym widać, który menedżer zainstalował pakiet.
   Linia `uwaga: … zmienił menedżera conda → pip, wersja bez zmian` nie jest błędem: to migracja pakietu
   między menedżerami. Failuje dopiero `DRYF:` z różnymi wersjami — wtedy podbij wersję w
   `envs/python/environment.lock.yml` w tym dziale, w którym pokazał ją `conda env export` z obrazu
   (`make freeze` robi to automatycznie).
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
Bisekcja wskazała jeden pakiet źródłowy, `linux` (jądro, około 4000 rekordów podatności), zgłoszony jako
[google/osv-scanner#3105](https://github.com/google/osv-scanner/issues/3105). Rozwiązanie:
`ci/osv-scanner-image.toml` pomija pakiet źródłowy `linux`. Override musi używać nazwy z pola `Source:`,
a nie `Package:`. Skan 1066 pakietów trwa wtedy 19 s przy szczycie 1,3 GB. CVE jądra obsługujemy
aktualizacją jądra w każdej wersji obrazu.

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

## dependabot-sca

**Stage 3 SCA rzuca CVE, którego łata jest już na `main`.** PR Dependabota (lub dowolny inny bot)
utworzony przed scaleniem fixu widzi starszy lockfile i failuje osv-scanner. Objaw: w „Diagnozie
przebiegu" kategoria `test`, błąd `BŁĄD: SCA: podatności zależności (osv-scanner)`, a w tabeli CVE
kolumna „Fixed Version" jest niższa lub równa wersji na `main`.

1. Potwierdź, że fix jest na `main`:
   ```bash
   git fetch origin --prune
   git checkout main && git pull --ff-only
   rg -n "<pakiet>" envs/python/environment.lock.yml envs/python/environment.yml
   ```
   Jeśli wersja na `main` jest starsza niż „Fixed Version" z tabeli CVE — fix nie istnieje. Najpierw
   utwórz `fix/<pakiet>-cve-<wersja>`, scal, a potem wróć do tej procedury.

2. Znajdź gałąź PR i pobierz ją lokalnie:
   ```bash
   gh pr list --state open --author "app/dependabot" \
     --json number,title,headRefName
   git fetch origin <headRefName>:pr-<num>
   git checkout pr-<num>
   ```

3. Zrebase'uj na `main` i zweryfikuj lokalnie:
   ```bash
   git rebase origin/main
   python3 ci/sca_requirements.py envs/python/environment.lock.yml build/sca/requirements.txt
   grep -n "^<pakiet>==" build/sca/requirements.txt
   osv-scanner scan source --no-resolve --format markdown \
     -L envs/r/renv.lock -L build/sca/requirements.txt
   ```
   Oczekiwane: wersja pakietu zgodna z `main`, „No issues found". Alternatywnie pełny Stage 3:
   `./ci/guard.sh --name "3. Security" --timeout 25m --memory auto -- ci/security.sh`.

4. Wypchnij z `--force-with-lease` (bezpieczne dla gałęzi Dependabota) i obserwuj CI:
   ```bash
   git push --force-with-lease origin pr-<num>:<headRefName>
   gh pr checks <num> --watch
   ```

5. Po zielonym CI wyczyść lokalną gałąź: `git checkout main && git branch -D pr-<num>`.

**Pułapki.** `git push --force` bez `--with-lease` nadpisuje bez sprawdzenia — zawsze z `--with-lease`.
Cherry-pick zamiast rebase tworzy duplikat commitu fixującego i po scaleniu PR wywoła konflikt na
`main`. `build/sca/requirements.txt` to artefakt — ręczna edycja nie przetrwa, fix musi trafić do
`envs/python/environment.lock.yml`. PR już merge'owany z `main` nie wymaga rebase — sprawdź
`git log origin/main..HEAD` (jeśli puste, gałąź ma już wszystko).

**Case study: PR #103 (2026-10-20).** Dependabot `actions/upload-artifact 7.0.1 → 7.0.2` zablokowany
przez 3 CVE w `aiohttp 3.14.3` (GHSA-2g87 8.7, GHSA-494j, GHSA-5wr8 8.2). Fix już na `main` w commicie
`503a0d0` (PR #119, `fix/aiohttp-cve-3144`). Naprawa: `git rebase origin/main` + `push --force-with-lease`.
Czas z runbookiem: ~8 min (wcześniej ~30 min diagnozy).

**Kiedy nie stosować.** CVE jest świeże, a fixu nie ma na `main` — utwórz PR z bumpem zależności.
Zależność zablokowana constraint w `pyproject.toml` — wymaga zmiany constraint-u. Podatności w
`renv.lock` — `renv::update()`, inne pliki. Podatności w pakietach conda — `conda update` + `conda-lock`.
