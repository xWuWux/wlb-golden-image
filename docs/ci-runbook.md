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
   | 4b | `make mutation` | mutant przeżył (test nie sprawdza tego, co deklaruje) albo wynik mutacji Pythona poniżej progu |
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

## mutation

**Mutant przeżył (stage 4b).** Testy przeszły mimo celowo zmienionego kodu — to luka w testach,
nie w kodzie obrazu. Stage 4b jest **bramkujący**: wynik Pythona poniżej `PYTHON_MUTATION_MIN`
(domyślnie 85%) albo jakakolwiek przeżyta mutacja powłoki czerwieni pipeline.

1. Odtwórz lokalnie: `make mutation` (albo `ci/mutation-bash.sh` dla samej powłoki,
   `mutmut run` + `mutmut results --all true` dla Pythona). Artefakt: `build/mutation/`.
2. Python: `python-summary.md` wypisuje zabite/przeżyte/„no tests”. Mutant „no tests” nie wchodzi do
   progu, ale **globalny** próg pokrycia etapu 4 nie pilnuje pojedynczego pliku — w walidatorze wydania
   ok. 40/145 mutantów jest w `main()`, poza progiem. To znana luka: domknięcie to testy `main()`
   (argv/capsys) albo per-plikowy floor pokrycia dla mutowanego pliku. Przeżyty mutant spoza
   allowlisty = twardy błąd; allowlista (`ci/mutations/python-allowlist.txt`) przyjmuje tylko
   mutanty równoważne i **wymaga uzasadnienia po `#`** (brak uzasadnienia = błąd), a wpis, który
   przestanie przeżywać, jest raportowany jako nieaktualny. Do progu wchodzi `killed + unlisted`:
   mutanty z allowlisty są równoważne, więc nie zaniżają wyniku (104/104 = 100%).
   Komunikaty walidatora są częścią kontraktu CLI (`main()` je wypisuje), dlatego `match=` z anchorami
   celowo zabija mutanty zmieniające tekst — to nie jest „testowanie pod mutanty”, tylko kontrakt. Przeżyty mutant = dopisz asercję w teście (nie obniżaj
   progu); jeśli mutant jest równoważny (nie da się go zabić), uzasadnij to w PR.
3. Powłoka: tabela `ci/mutations/bash-mutations.tsv`. Każdy wiersz ma **baseline**: przed mutacją harness
   uruchamia wybrany test na niezmienionej kopii i wymaga dokładnie 1 zielonego testu — zepsuty test
   nie może udawać „zabitej” mutacji. Allowlisty dla powłoki nie ma: survivor = twardy błąd. Każdy wiersz to celowa zmiana skryptu obrazu
   i test bats, który MUSI ją zabić. Nowy wiersz dodawaj razem z testem; `ci/mutation-bash.sh --check`
   pilnuje, że fragment do mutacji nadal występuje w pliku dokładnie raz (tabela nie może się rozjechać).

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

## code-scanning

**Publikacja SARIF w GitHub Code scanning (job „3r. Publikacja Code scanning”, #257).**
Etap 3 zapisuje raporty `semgrep` i `checkov`, a osobny job wysyła je do zakładki *Security → Code
scanning* (kategorie `semgrep` i `checkov`). PR-y dostają adnotacje w diffie, a alerty mają historię
i triage.

**Polityka: raport, nie druga bramka.** Znaleziska blokuje wyłącznie `ci/security.sh` (job
„3. Security & compliance”), z tymi samymi regułami co dotąd. Code scanning nie dodaje drugiego progu
podatności i nie jest wymaganym sprawdzeniem reguł ochrony gałęzi. Job publikacji jest za to
**kontrolą infrastrukturalną**: jeśli raport nie dotarł (brak, niepoprawny albo odrzucony), „Gotowe do
code review” jest czerwone, bo zielony wynik bez publikacji byłby fałszywym „czysto”.

Trzy wyniki są rozdzielone i każdy ma własne miejsce w podsumowaniu przebiegu:

| Co się stało | Gdzie widać | Stan |
|---|---|---|
| skan wykrył problem | job 3 czerwony, tabela „Raporty SARIF” | `findings` — raport i tak jest publikowany |
| skaner zwrócił kod 0, ale raport ma aktywne wyniki (np. soft-fail lub próg w konfiguracji narzędzia) | job 3 zielony, tabela „Raporty SARIF” | `findings` — tylko alert w Code scanning (semgrep z `--error` przy aktywnych wynikach zwraca 1, niezależnie od severity) |
| skaner nie wykonał analizy (awaria, timeout, brak/uszkodzony raport) | job 3 czerwony, tabela „Raporty SARIF” | `error` / `not_run` — **niczego nie publikujemy**; brak raportu nie zamyka starych alertów |
| raport nie został dostarczony | job 3r czerwony, tabela „Publikacja Code scanning” | `failed` / `cancelled` |

Stany skanera (`ci/sarif_report.py`): `clean` (kod 0, brak aktywnych wyników), `findings` (aktywne
wyniki), `error` (kod ≥ 2, niespójny kod wyjścia lub raport odrzucony przez walidator), `not_run`
(brak `build/sca/<narzędzie>.exit`, np. skaner zabity przez strażnika). Raport jest też `error`, gdy
skaner zgłosił w nim notyfikację `level: error` (analiza niekompletna) — nawet przy kodzie 0 i zerze
wyników nie publikujemy wtedy pustego zamiennika. Stany publikacji: `processed` (krok „Potwierdzenie
przetworzenia” odczytał z API terminalny status `complete` dla konkretnego `sarif-id`; sam zielony
`upload-sarif` nie wystarcza, bo po własnym limicie oczekiwania akcja tylko ostrzega), `failed`
(upload nieudany albo status `failed`/`pending` po terminie 5 minut), `cancelled`,
`pending` (brak terminalnego statusu w terminie — blokuje), `unsupported` (kontekst bez publikacji — niżej). Wyniki wyciszone w kodzie (`# nosemgrep`,
`checkov:skip`) nie liczą się do `findings` i **nie są publikowane**: GitHub ignoruje pole SARIF
`suppressions` i pokazałby je jako otwarte alerty, choć bramka ich nie liczy, a uzasadnienie jest w
kodzie. Ich liczbę podaje manifest (`suppressed_count`).

**Konteksty zdarzeń.** SHA i ref analizy pochodzą z kontekstu przebiegu, nigdy z raportu.

| Zdarzenie | Publikacja |
|---|---|
| `pull_request` (także fork i Dependabot) | tak — ref `refs/pull/N/merge`; GitHub przyjmuje upload z `pull_request` mimo tokena tylko do odczytu |
| `push` do `main`, `schedule`, `workflow_dispatch` | tak — ref gałęzi |
| `merge_group` | `unsupported` — ref kolejki znika po scaleniu, a analiza kolejki nie może uchodzić za wynik `main` |
| przebieg `dependabot[bot]` poza `pull_request`, także `push` commitu jego autorstwa (squash-merge) | `unsupported` — token tylko do odczytu |

W kontekście `unsupported` job kończy się sukcesem z jawnym powodem w podsumowaniu, a raporty
(po eksporcie) zostają w artefakcie `code-scanning-sarif`. Nie obchodzimy odmowy tokena przez PAT,
`pull_request_target` ani `workflow_run`.

**Uprawnienia.** `security-events: write` ma wyłącznie job 3r. Nie uruchamia on skryptów z repo,
lokalnych actions ani instalacji: pobiera artefakt `code-scanning-sarif` z tego samego przebiegu,
sprawdza, że manifest wskazuje ten sam przebieg i SHA (`run_id`, `sha`), robi checkout bez zapisanych
poświadczeń (tylko do mapowania ścieżek i fingerprintów), wywołuje `upload-sarif` i odpytuje API o status
przetworzenia (`curl` + `jq`). Job skanujący zostaje tylko do odczytu. Pilnuje tego test
`tests/unit/test_code_scanning_workflow.py`, który także wykonuje skrypty kroków joba 3r.

**Zakres ochrony eksportu (prywatność).** Repozytorium jest publiczne: kod, logi CI i artefakty może
czytać każdy zalogowany użytkownik, a Code scanning — osoby z uprawnieniami do alertów. Skanery
widzą dopasowany kod, więc przy `p/secrets` mogłyby wynieść wykryty sekret poza historię Git.
Ustalony zakres:

| Kanał | Co trafia | Ochrona |
|---|---|---|
| Code scanning i artefakt `code-scanning-sarif` | raport po `export_sarif` | **jawny schemat (allowlista pól)**: reguły narzędzia, `ruleId`, poziom, `uri` + linie/kolumny, `partialFingerprints`. Treść wyniku (`message`) zastąpiona tekstem reguły (semgrep wkleja w nią dopasowane metazmienne); bez `snippet`, `contextRegion`, `relatedLocations`, `codeFlows`, `fingerprints`, `properties`; notyfikacje narzędzia tylko z identyfikatorem |
| artefakt `security-reports` | `build/sca/` **bez `*.sarif`** | surowe SARIF nie opuszczają runnera |
| log joba 3 | semgrep: tylko `reguła plik:linia`; bandit: `plik:linia test poziom`; checkov `--compact` (bez bloków kodu) | stdout semgrepa idzie do `/dev/null` |
| manifest, podsumowanie, `GITHUB_OUTPUT` | liczniki, wersje, skróty, powody błędów | nigdy treść raportu |

Testy z sekretem-canary (`tests/unit/test_sarif_report.py`) wstawiają go w pola spoza allowlisty i w
treść wyniku; nie może się pojawić w żadnym z kanałów. Pełną treść znaleziska (z kodem) zobaczysz
lokalnie: `make security` albo w kodzie pod wskazaną linią. Wykryty sekret trzeba unieważnić —
usunięcie pliku nie usuwa go z historii Git. Do repozytorium nie wolno wkładać danych badaczy.

**Powtarzalność.** Manifest (`manifest.json` w artefakcie) wiąże raporty z `run_id`, `run_attempt`, SHA i
refem oraz zapisuje wersję skanera, skrót każdego publikowanego pliku (`sha256`, sprawdzany w jobie 3r)
i `sarif_rules_metadata_digest` — skrót **metadanych** reguł z SARIF. To nie jest dowód wersji
implementacji reguł: semgrep pobiera zestawy `p/*` z rejestru, więc ten sam SHA repo może po czasie dać
inny wynik, a zmiana wzorca przy tych samych metadanych nie zmieni skrótu; zestaw deskryptorów checkova
zależy od zgłoszonych wyników. Ponowienie joba 3r publikuje ten sam raport; nowy skan (z bieżącymi
regułami) to nowy przebieg etapu 3.

**Ograniczenia skanu.** Liczba reguł nie mówi, ile plików zbadano. Semgrep pomija domyślnie m.in. katalogi
`tests/` i `build/` oraz pliki, których nie sparsuje (notyfikacje `warning` w raporcie: np. szablony
Jinja/Ansible, część skryptów powłoki). Checkov `--framework secrets` w używanej wersji nie zgłasza
checków — sekrety pokrywają gitleaks (etap 1) i semgrep `p/secrets`. Dlatego etap 3 ma sprawdzenie
**„Kontrakt SARIF na przypiętych skanerach”**: te same wersje semgrep i checkov skanują
`tests/fixtures/sarif-contract/` (celowy sekret-canary i workflow z `write-all`), a `prepare` musi dać
`findings` z oczekiwanymi regułami, bez canary w publikowanym SARIF, manifeście i logu. Po aktualizacji
narzędzia czerwony kontrakt oznacza zmianę formatu wyjścia albo pokrycia — zbadaj przed podbiciem.
Walidator przyjmuje jawny podzbiór SARIF 2.1.0 używany przez te dwa narzędzia (dokładne nazwy
narzędzi, jeden przebieg, limity rozmiaru i zagnieżdżenia), nie deklaruje pełnej zgodności ze schematem.

### Co zrobić

1. **Job 3 czerwony, w tabeli `findings`.** Zwykła ścieżka [test](#test): popraw kod albo uzasadnij
   wyjątek. Alert w Code scanning jest tym samym znaleziskiem z historią.
2. **`error` / `not_run`.** Skaner nie dał wiarygodnego wyniku (także: notyfikacja `level: error`, czyli
   analiza niekompletna). Sprawdź log kroku skanera
   (`build/sca/<narzędzie>.exit`, `reason` w manifeście). Nie podkładaj pustego raportu.
3. **Job 3r `failed` / `pending`.** Status `forbidden` (401/403) przy odczycie statusu przetwarzania to brak
   uprawnień, nie sukces; `unavailable` (429/5xx) i `pending` — usługa GitHuba nie potwierdziła w terminie.
   Etap 3 nie jest powtarzany: „Re-run failed jobs” uruchamia tylko job 3r, który
   publikuje **ten sam** artefakt z tego przebiegu (nie skanuje od nowa). Powtarzający się błąd
   uprawnień (403) albo odrzucenie SARIF zgłoś jako issue; nie dopisuj `continue-on-error`.
4. **Brak adnotacji w PR.** Adnotacja pojawia się tylko dla wyniku w zmienionych liniach i gdy
   gałąź bazowa ma analizę tej samej kategorii. Wynik poza diffem sprawdzaj w rekordzie analizy:
   `gh api repos/{owner}/{repo}/code-scanning/analyses --jq '.[] | {category, ref, commit_sha, results_count}'`.

**Triage.** Alerty przegląda właściciel repozytorium (tymczasowo; docelowo zespół bezpieczeństwa).
Zamknięcie alertu jako *false positive* / *won't fix* wymaga komentarza z uzasadnieniem; wyciszenie w
kodzie (`# nosemgrep: <reguła>`, `# checkov:skip=<id>: <powód>`) zawsze z powodem. Termin reakcji
na nowy alert ustala właściciel projektu (do potwierdzenia w #257).

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

### Macierz kontraktów etapu 4b (#340)

`make mutation` publikuje wynik każdej pary w `build/mutation/contracts.json`.
Przy czerwonym wyniku znajdź logi `<kontrakt>.<mutacja>.<konsument>.{base,mutant}.log`.
Popraw najpierw baseline lub selektor. Przy `survived` sprawdź osiągalność zmienionego
fragmentu i niezależną asercję efektu. Błąd procesu, timeout i pominięty test blokują bramkę.
Wynik wymagany dla każdego pliku macierzy to 100% par. Zakres i odpowiedzialność opisuje
[macierz kontraktów](mutation-abstractions.md).
