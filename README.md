# WLB — golden image VM Laboratorium (JupyterHub)

Obraz bazowy VM dla Wirtualnych Laboratoriów Badawczych GUMed IP_CMC, zgodny ze
„Specyfikacją VM z JupyterHub dla badacza — MVP”. Jedna VM na Laboratorium,
The Littlest JupyterHub, kategoria **ogólnego przeznaczenia** (bez GPU).

Obraz budujemy raz Packerem z Ansible, a wynikiem jest `qcow2` dla Proxmoxa i OpenStacka.
Wszystko, co zależy od konkretnego Laboratorium (hostname, klucz SSH, udziały, proxy, SIEM,
administrator huba), przychodzi przy starcie przez cloud-init. Na żywej VM nic nie
zmieniamy ręcznie.

## Struktura

```
packer/                 definicja budowania (QEMU/KVM, obraz chmurowy Ubuntu 24.04 z przypiętego wydania)
ansible/                playbook i role instalujące zawartość obrazu
  roles/base            aktualizacja, pakiety, SSH tylko dla administratorów platformy, utwardzenie
  roles/storage         katalogi §10, katalogi domowe w /workspace, śluza wyjściowa
  roles/tljh            TLJH, Native Authenticator, idle culling 30 min, limit 12 h, izolacja sesji
  roles/python_env      kernel Python (envs/python)
  roles/r_env           R, IRkernel, HADES, sterownik JDBC PostgreSQL (envs/r)
  roles/julia_env       Julia + kernel IJulia (envs/julia)
  roles/rstudio         RStudio przez JupyterLab (opcjonalnie, domyślnie wyłączone)
  roles/desktop         pulpit XFCE w przeglądarce przez remote-desktop-proxy (flavor wlb-memory, #106)
  roles/audit           reguły auditd (śluzy, polecenia badaczy, odmowy; konta, czas, moduły,
                        sesje, usunięcia/DAC, AppArmor — §21/CIS), blokada -e 2
  roles/logging         journald -> rsyslog, historia poleceń powłoki
  roles/lab_config      wlb-firstboot: konfiguracja per-Lab przy pierwszym starcie
envs/python/            environment.yml (+ environment.lock.yml po zamrożeniu)
envs/r/                 hades-packages.txt, renv.lock, skrypt instalacji
cloud-init/             przykładowy user-data i opis zmiennych Laboratorium (lab.env)
tests/                  lokalne uruchomienie obrazu, kryteria akceptacji MVP, test migracji
tests/unit/             testy jednostkowe (bats: skrypty powłoki, pytest: Python)
ci/                     etapy pipeline'u CI (te same skrypty lokalnie i w GitHub Actions)
.github/workflows/      GitHub Actions: kolejność etapów, KVM, artefakty
```

## Wymagania (WSL2 / Linux)

**Pierwsze uruchomienie krok po kroku, z typowymi problemami: [`docs/pierwsze-uruchomienie.md`](docs/pierwsze-uruchomienie.md).**

- Repozytorium w systemie plików WSL/Linuksa (`~/…`), **nie na dysku Windows (`/mnt/c/…`)**: tam pliki mają
  prawa 0777 (ssh odrzuca klucz budowania) i zakończenia linii CRLF.
- QEMU/KVM z dostępem do `/dev/kvm` (użytkownik w grupie `kvm`; w WSL po dodaniu grupy
  uruchom `wsl --shutdown`), `cloud-image-utils`, `genisoimage`, `python3-venv`
- Packer i Ansible w przypiętych wersjach instaluje `make tools` (do `.tools/`, bez sudo)
- ok. 40 GB miejsca, 6 GB RAM dla maszyny budującej, 8 GB dla VM testowej

`make doctor` sprawdza wszystkie wymagania i podaje polecenie naprawcze dla każdego braku.

## Budowanie

Wszystkie polecenia `make` uruchamia się w katalogu głównym repozytorium:

```bash
make tools                      # narzędzia projektu do .tools/ (raz; make dodaje je do PATH sam)
make doctor                     # sprawdzenie środowiska
make init                       # wtyczki Packera (raz)
make validate
make build IMAGE_VERSION=0.1.0  # -> output/wlb-general-0.1.0-<data>/*.qcow2 + sha256 + manifest
```

Pierwsze budowanie trwa długo: kompilacja i instalacja pakietów HADES może zająć godzinę albo dłużej.

### Zamrożone wersje pakietów

Po budowaniu w `build/artifacts/<obraz>/` lądują `environment.lock.yml`
i `renv.lock` z dokładnymi wersjami. `make freeze` przenosi je do `envs/` i mówi, czy coś się zmieniło.
Zmiana wersji trafia na osobną gałąź i do PR (opiekun repozytorium); „Bez zmian” oznacza zgodność.

Od tej chwili każde budowanie odtwarza te same wersje. Zmiana pakietów wygląda tak:
edycja `environment.yml` lub `hades-packages.txt`, usunięcie locka, budowanie, `make freeze`, commit.
Wersje CRAN wyznacza też data snapshotu Posit Package Managera (`r_cran_snapshot_date`).

Czasami pakiet zmienia menedżera (np. `markupsafe` chcą zależności conda i pip) — wtedy `conda env export`
zapisuje go w innym dziale przy tej samej wersji. Test dryfu traktuje to jako uwagę, nie błąd; suchy dryf
jest wtedy, gdy różni się wersja. Który menedżer zainstalował pakiet widać w `conda-env-update.log`
(artefakty etapu 5).

## Test lokalny

```bash
make test-up     # VM z obrazu + cloud-init Laboratorium testowego (tests/cloud-init/)
make test        # kryteria akceptacji MVP
make test-down
```

Hub jest dostępny pod `http://localhost:8080`, a SSH przez
`ssh -p 2222 -i build/test/id_ed25519 wlbadmin@127.0.0.1`.
Hasło początkowe administratora huba (`admin-klienta`) wypisuje `make test-password`
(w VM: `sudo cat /root/wlb-hub-admin-initial-password`).

W teście nie ma udziałów sieciowych, proxy ani SIEM. Katalogi §10 są lokalne, a
`EGRESS_ALLOW` wskazuje nieistniejący adres, więc każde wyjście badacza musi się nie udać.

## Pipeline CI

Każdy PR przechodzi etapy po kolei. Następny etap startuje dopiero wtedy, gdy poprzedni się powiedzie.
Logika jest w `ci/*.sh`, więc lokalnie uruchamia się ją tak samo (`make tools`, potem `make ci`).

| Etap | Skrypt | Co sprawdza | Kiedy |
|---|---|---|---|
| 1. Lint, format, sekrety | `ci/lint.sh` | shellcheck, shfmt, ruff, yamllint, ansible-lint (profil production), actionlint, packer fmt, gitleaks (historia + drzewo) | zawsze |
| 2. Build test | `ci/build-check.sh` | packer validate, syntax-check Ansible, render szablonów i kompilacja wyniku, parsowanie R, schemat cloud-init, `nft -c` i `rsyslogd -N1` na konfiguracji z `wlb-firstboot` | zawsze |
| 3. Security & compliance | `ci/security.sh` | SAST (semgrep, bandit), IaC (checkov), podatności zamrożonych zależności (osv-scanner), licencje (`ci/license-policy.yml`) | zawsze |
| 3.5. Kontrakt obserwowalności | `ci/observability.sh` | zdarzenia z `observability/contract.yml` zgodne z kodem obrazu: źródła logów, pola, klucze audytu, prefiksy zapory, przekazywanie do SIEM | zawsze |
| 4. Testy jednostkowe | `ci/unit.sh` | bats + kcov (próg 85%), pytest + coverage z gałęziami (próg 90%) | zawsze |
| 5. Integracja i migracja | `ci/integration.sh` | budowanie obrazu na KVM, kryteria akceptacji MVP w VM, zdarzenia z kontraktu w logu centralnym (testowy SIEM), migracja na istniejący dysk roboczy, dryf locków, podatności pakietów w obrazie (raport) | zmiany poza dokumentacją |
| 6a. Benchmarki | `ci/perf.sh` | start VM, logowanie, spawn, pandas, ładowanie HADES, dysk — względem `ci/perf-budget.env` | etykieta PR `perf` lub ręcznie |
| 6b. Wdrożenie tymczasowe | `ci/ephemeral-openstack.sh` | obraz, wolumen i VM w projekcie testowym OpenStack, kryteria akceptacji, sprzątanie | etykieta `deploy-test`, po konfiguracji |
| Gotowe do code review | `ci/ready.sh` | etapy 1–4 zaliczone, 5 zaliczony (jeśli dotyczy), 6 nie zawiódł | zawsze |

Uwagi:
- **Koszt:** etap 5 buduje cały obraz (1–2 h na runnerze GitHub). W repozytorium prywatnym zużywa to
  minuty Actions z limitu planu. Zmiany samej dokumentacji go pomijają.
- **Wymagany status check:** ustaw „Gotowe do code review” jako wymagany dla `main`
  (Settings → Branches). Ochrona gałęzi w repozytoriach prywatnych wymaga planu GitHub Pro lub Team.
- **Etap 6b** wymaga zmiennych repozytorium `OPENSTACK_EPHEMERAL=true`, `OS_CLOUD`, `OS_TEST_FLAVOR`,
  `OS_TEST_NETWORK`, opcjonalnie `OPENSTACK_RUNNER` (runner self-hosted z dostępem do chmury), oraz
  environment `openstack-test` z sekretem `OPENSTACK_CLOUDS_YAML`. Skrypt odmawia pracy na zasobach
  z „prod” w nazwie.
- **SCA** w etapie 3 obejmuje zamrożone wersje, więc zaczyna działać po pierwszym `make freeze`.
  Do tego czasu podatności zależności sprawdza tylko raport z etapu 5.
- Cotygodniowy przebieg (poniedziałek) powtarza etapy 1–4, żeby wyłapać nowe CVE i zmiany licencji.
- Nocny przebieg (codziennie 03:00) powtarza **pełny** pipeline (etapy 1–6, bez zależności od zakresu zmian) —
  łapie dryf zamrożonych wersji i nowe CVE, zanim uderzą w czyjś PR.

## Obsługa błędów CI

Szczegółowa ścieżka dla każdego typu awarii jest w [`docs/ci-runbook.md`](docs/ci-runbook.md).

- **Strażnik zasobów** (`ci/guard.sh`). Każdy etap działa z limitem czasu i pamięci. Pamięć
  jest ograniczona cgroup do całej pamięci maszyny minus 1 GB. Proces, który się rozrośnie, zostaje
  zabity sam (adnotacja `OOM` albo `TIMEOUT`), a runner zapisuje logi i artefakty. Wcześniej brak pamięci
  zabijał agenta GitHub Actions i job kończył się bez logów komunikatem „The operation was canceled”.
- **Diagnoza.** Kiedy PR nie przechodzi, „Gotowe do code review” klasyfikuje każdy nieudany job
  (`test`, `oom`, `timeout`, `infra`, `cancelled`) i podaje link do właściwej sekcji runbooka
  (`ci/ci_failures.py`).
- **Automatyczne ponowienie** (`.github/workflows/ci-retry.yml`). Tylko kategoria `infra`, jeden raz,
  tylko dla najnowszego commita. Błędy testów, OOM i przekroczenia czasu wymagają poprawki.
  Podobnie jak telemetria działa dopiero po scaleniu do `main`.
- **Kroki raportowe** (np. skan podatności pakietów w obrazie) mają flagę `--optional`: zgłaszają
  ostrzeżenie, ale nie blokują.
- **Przypięte akcje.** Wszystkie akcje GitHub są przypięte do SHA commitów (ochrona przed podmianą
  tagu). Aktualizuje je Dependabot.

## Obserwowalność

Są dwie warstwy i obie działają przy każdym PR bez dodatkowej pracy.

**1. Kontrakt obserwowalności obrazu** (`observability/contract.yml`). To katalog zdarzeń, które
VM musi emitować i dostarczać do SIEM, wraz z polami, formatem i paragrafem Regulaminu:

- zdarzenia: `sluza_out.export_request`, `shell.command`, `hub.login`, `firstboot.done`,
  `network.egress_deny` i inne,
- klucze audytu `wlb_*`,
- pola korelacji: `user`, `uid`, `session`.

Kontrakt jest sprawdzany na dwa sposoby:
- **etap 3.5 (statycznie):** każde źródło logów w obrazie jest opisane w kontrakcie, a kod emituje
  dokładnie zadeklarowane pola. Klucze audytu i prefiksy logów zapory zgadzają się w obie strony.
  Zmiana formatu logu bez zmiany kontraktu zatrzymuje PR.
- **etap 5 (dynamicznie):** VM testowa wysyła logi rsyslogiem do testowego odbiornika SIEM na hoście
  (`tests/syslog_sink.py`). Po teście akceptacyjnym `ci/observability_contract.py verify-log` sprawdza,
  że każde zdarzenie oznaczone `acceptance: true` dotarło do logu centralnego z poprawnymi wartościami.
  To pokrywa kryterium MVP „wszystkie zdarzenia widoczne w logu centralnym”.

Reguły korelacji i dashboardy w Wazuh lub OpenSearch warto budować na nazwach pól z kontraktu.

**2. Obserwowalność potoku CI** (`.github/workflows/ci-observability.yml`, `ci/ci_telemetry.py`).
Po każdym przebiegu CI powstają w formacie OpenTelemetry:
- ślad: przebieg, joby i kroki, z czasem oczekiwania w kolejce, wynikiem i runnerem,
- metryki: `wlb.ci.run.duration`, `wlb.ci.job.duration`, `wlb.ci.job.queue_time`,
  `wlb.ci.job.success_ratio`, `wlb.ci.job.duration_p90` i `wlb.ci.job.flaky_commits`
  (z 30 ostatnich przebiegów),
- logi: rekord JSON na każdy job i krok, z `trace_id` i `span_id`.

Wyniki trafiają do artefaktu `ci-telemetry` i podsumowania. Po ustawieniu zmiennej
`OTEL_EXPORTER_OTLP_ENDPOINT` (i opcjonalnie sekretu `OTEL_EXPORTER_OTLP_HEADERS`) są też wysyłane
do kolektora OTLP/HTTP. Działa to dopiero po scaleniu do `main`, bo GitHub uruchamia `workflow_run`
tylko z gałęzi domyślnej.

**Czego celowo nie ma:**
- **śladów rozproszonych w VM,** bo nie ma tam usług wywołujących się nawzajem (zdarzenia koreluje się
  po `user`, `uid` i `session`),
- **metryk VM** (np. `prometheus-node-exporter`, `/hub/metrics` JupyterHuba). Wymagają wyboru systemu
  monitoringu i otwarcia portu z sieci monitoringu. Kiedy ta decyzja zapadnie, metryki dopisuje się
  do kontraktu, a sprawdzenia rozszerza tym samym mechanizmem.

## Wdrożenie obrazu

OpenStack:
```bash
openstack image create wlb-general-0.1.0 --disk-format qcow2 --container-format bare \
  --file output/wlb-general-0.1.0-*/wlb-general-0.1.0-*.qcow2 \
  --property hw_disk_bus=virtio --property hw_qemu_guest_agent=yes --private
openstack server create lab-example01 --image wlb-general-0.1.0 --flavor wlb.general \
  --network lab-example01-net --user-data cloud-init/lab-user-data.example.yaml \
  --block-device source_type=blank,destination_type=volume,volume_size=200,delete_on_termination=false
```

Proxmox: `qm importdisk <vmid> <obraz>.qcow2 <storage>`, dysk cloud-init oraz
`qm set <vmid> --cicustom user=snippets:lab-example01.yaml`.

Każda nowa instancja potrzebuje własnego user-data według wzoru `cloud-init/lab-user-data.example.yaml`
(zmienne opisuje `cloud-init/lab.env.example`). Do czasu zakończenia `wlb-firstboot`
VM przyjmuje z sieci wyłącznie SSH.

## Kryteria akceptacji MVP

| Kryterium | Realizacja | Test lokalny |
|---|---|---|
| Badacz loguje się swoim kontem i widzi tylko własny katalog | Native Authenticator; `HOME=/workspace`, `HOME_MODE 0700`, `/workspace` 0711 | tak |
| Notebook Python, R i Julia w tej samej sesji | kernele `python3` + `ir` (IRkernel, HADES) + `julia-*` (IJulia) w jednym JupyterLab | tak (nbconvert) |
| Odczyt `/data-mart` bez modyfikacji | udział `ro` + prawa 0750 + `ReadOnlyPaths` w jednostce systemd | tak |
| Zapis do `/sluza-in` kończy się odmową | jw. | tak |
| Plik w `/sluza-out` znika i trafia do kolejki | katalog 1730 (bez listowania) + `wlb-sluza-out` przenosi do kolejki | tak |
| Połączenie poza allowlistą się nie udaje | nftables per UID badacza (obrona w głębi) + proxy i sieć Laboratorium | częściowo (brak proxy) |
| Po 12 h sesja kończy się niezależnie od aktywności | culler `--max-age=43200`, ciasteczko i tokeny 12 h | konfiguracja; faktyczny czas — ręcznie |
| Zdarzenia widoczne w logu centralnym | auditd + journald -> rsyslog -> SIEM (`SIEM_HOST`) | lokalnie tak, SIEM — na klastrze |

Test ręczny 12 h: ustaw w VM testowej
`tljh-config set services.cull.max_age 300 && tljh-config reload hub`, zaloguj się
i sprawdź, czy serwer zostanie zatrzymany po 5 minutach mimo aktywności.

## Decyzje i odstępstwa od specyfikacji

- **TLJH 2.0.0** (JupyterHub 5) zamiast 1.x. To aktualne wydanie, wersja przypięta w `group_vars/all.yml`.
- **Admini huba bez sudo.** TLJH domyślnie daje administratorom huba pełne sudo. Wyłączyliśmy to, bo
  Administrator Klienta nie powinien móc zmieniać logów (§21) ani instalować oprogramowania (§24.c).
- **Konta badaczy** zakłada Administrator Klienta, zatwierdzając wniosek w `/hub/authorize`,
  albo administrator platformy przez `wlb-hub-user <login>`. Samodzielna rejestracja
  (`open_signup`) jest wyłączona.
- **UID badaczy od 10000.** Reguły audytu i zapory odróżniają w ten sposób badaczy od
  administratorów platformy (w user-data `uid: 1001`).
- **RStudio** działa przez JupyterLab (`jupyter-rsession-proxy`), a nie na osobnym porcie. Konta
  tworzone przez TLJH nie mają haseł systemowych, więc logowanie PAM do samodzielnego RStudio
  Server nie zadziała. Dzięki temu limity sesji obejmują też RStudio.
- **Reguły audytu** są ładowane po zamontowaniu udziałów i blokowane (`auditctl -e 2`).
  Zmiana reguł wymaga restartu VM.
- **Brak automatycznych aktualizacji.** Poprawki bezpieczeństwa wchodzą przez nową wersję obrazu.
- **Baza huba na dysku roboczym** (`/workspace/.wlb-hub/`). Dysk systemowy jest jednorazowy, więc bez
  tego nowa wersja obrazu kasowałaby konta w hubie. `wlb-firstboot` odtwarza też konta systemowe badaczy
  z tym samym UID co właściciel katalogu domowego, a hasło Administratora Klienta zostaje bez zmian.
  Sprawdza to test migracji w etapie 5.
- **Spójna kopia bazy huba przed snapshotem storage (#8).** Snapshot działającej bazy SQLite bywa
  niespójny, więc timer `wlb-hub-db-backup.timer` robi migawkę online (`sqlite3 .backup`) do
  `/workspace/.wlb-hub/backup/` — gotowy, spójny plik, który wchodzi do snapshotu Ceph. Harmonogram i
  rotacja w `group_vars/all.yml` (`hub_db_backup_oncalendar` domyślnie `hourly`, `hub_db_backup_keep`
  domyślnie 24). Procedura odtworzenia: [`docs/runbook-kopia-bazy-huba.md`](docs/runbook-kopia-bazy-huba.md);
  test odtworzenia (konta i hasła działają) w etapie 5.
- **Blokada pobierania plików jest częściowa (#7, §14, §24.e).** Traefik przed hubem zwraca 403 dla
  `/user/*/files`, `/nbconvert` i `/view` (przycisk Download, „Export Notebook As”, bezpośredni URL), a każda
  odmowa trafia do SIEM (`hub.download_denied`). Przyciski pobierania są ukryte w JupyterLab, ale to tylko
  wygoda: blokadę daje serwer. **Otwarte zostają:** `/api/contents`, przez które JupyterLab otwiera i zapisuje
  każdy plik, schowek i zrzuty ekranu. Pełną egzekucję daje dopiero dostęp przez VDI (#18), zgodnie ze
  specyfikacją. Koszt: obrazki wstawione w Markdown (`![](plik.png)`) się nie wyświetlają, bo JupyterLab
  ładuje je przez `/files`. Wykresy w wynikach komórek działają normalnie.
- **Limity zasobów badaczy (#30)** wylicza `wlb-firstboot` z RAM i vCPU danej VM, bo kategorie VM się różnią:
  - rezerwa na usługi (audyt, logi, hub, SSH): max(3 GB, 10% RAM),
  - pozostała pula: wspólny limit `wlb-badacze.slice`,
  - na badacza: pula / `RESEARCHERS_PER_VM` i vCPU / `RESEARCHERS_PER_VM` (co najmniej 1) oraz 2048 procesów.
    Domyślnie `RESEARCHERS_PER_VM=1` (VM na badacza, ADR IMG-001); przy kilku kontach na jednej VM ustawia
    się ich liczbę w `lab.env`.

  Wszystkie wartości można nadpisać w `lab.env`. `OOMPolicy=continue`: przekroczenie limitu zabija proces
  (zwykle kernel), a nie cały serwer notebooków. Usługi systemowe mają ujemne `OOMScoreAdjust`, audyt -1000.
  Model przydziału VM opisuje `docs/adr/IMG-001-model-vm-i-limity-zasobow.md`.
- **Licencja `inspectomop` to AGPL-3.0.** Jest wpisana jako wyjątek w `ci/license-policy.yml` z adnotacją
  „do potwierdzenia przez dział prawny”. Bez tej decyzji pakiet należy usunąć ze środowiska.

## Otwarte kwestie

- Historia poleceń obejmuje terminal (syslog `wlb-shell`) i każde uruchomienie procesu (auditd
  `execve`). Kod wykonywany w komórkach notebooków nie jest osobno logowany.
- DNS: procesy badaczy rozwiązują nazwy przez lokalny `systemd-resolved`. Filtrowanie DNS
  (ochrona przed tunelowaniem) trzeba zrobić na poziomie sieci Laboratorium.
- `pip install --user` przez mirror PyPI jest technicznie możliwe. Trzeba zdecydować, czy mirror
  ma być dostępny dla badaczy (§24.c), czy tylko dla budowania obrazu.
- Uwierzytelnianie: domyślnie Native Authenticator (`AUTH_MODE=native`). `AUTH_MODE=oidc` przełącza na
  SSO przez OpenID Connect (Entra ID / Keycloak, MFA po stronie IdP) — `wlb-firstboot` z `OIDC_*` w `lab.env`
  pisze `70-wlb-auth.py` z `GenericOAuthenticator`. Wymaga rejestracji aplikacji w IdP, HTTPS (#18) oraz
  mapowania claimu na istniejące konta `jupyter-<login>` i grup IdP zamiast `allow_all` (decyzje w #18).
- HTTPS: hub nasłuchuje na porcie 80 i zakłada TLS na portalu WLB lub bramce VDI. Ewentualnie
  można włączyć `https.*` w TLJH.
- GPU (RTX PRO 6000, passthrough), wybór Proxmox vs OpenStack, dostęp testera (portal czy
  bezpośrednio), rozmiar `/workspace` i `/data-mart` — zgodnie z listą otwartych pytań w specyfikacji.
