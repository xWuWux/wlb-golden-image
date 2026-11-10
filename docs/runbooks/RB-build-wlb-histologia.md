# RB: Budowa i weryfikacja flavora wlb-histologia

**Rola:** Administrator Platformy / Operator budowy obrazu
**Odniesienia:** #108 (jamovi / statystyka z GUI), #107 (Calc), #106 (pulpit), #63/#65 (utwardzenie, userns)
**Co to:** warstwowy obraz `wlb-histologia` = `wlb-general` + pulpit (rola `desktop`) + RStudio (rola `rstudio`) + stos histologii (rola `histo_apps`: LibreOffice Calc, jamovi przez Flatpak). Obraz bazowy zostaje lekki.

## 1. Wymagania wstępne

- KVM i narzędzia: `make doctor` zielone.
- **Sieć w trakcie buildu** (gotowa VM jest offline): mirror apt (LibreOffice), S3 (`s3.amazonaws.com` — .deb RStudio), **Flathub** (`flathub.org` i `dl.flathub.org`) — stamtąd ciągną się aplikacja jamovi i jej runtime.
  - ⚠️ **Na zamkniętej allowliście budowania dopisz Flathub** (`flathub.org`, `dl.flathub.org`) obok mirrorów apt/PyPI/CRAN — bez tego task `Instalacja jamovi z Flathub` padnie na braku sieci. To JEDYNY nietypowy wymóg sieciowy tego flavora.
- **Miejsce i czas:** jamovi (app + runtime `org.freedesktop.Platform`) to ~2 GB pobrania; `histologia_disk_size` = 50G. Build bazy ~30 min + warstwa (LibreOffice + RStudio .deb + pobranie Flatpaka).

## 2. Przypięte wersje / parametry (w `ansible/group_vars/all.yml`)

- `jamovi_flatpak_id: org.jamovi.jamovi` · `jamovi_flathub_repo_url` (Flathub) · `jamovi_data_path: /workspace` (katalog danych badacza udostępniany sandboxowi jamovi).
- `rstudio_server_deb_url` · `rstudio_rsession_proxy_spec` — współdzielone z wlb-memory.
- jamovi z Flathub instaluje **najnowszą stabilną** wersję z kanału (brak przypięcia po wersji — Flatpak nie wersjonuje jak apt/pin). Jeśli potrzebne powtarzalne wydanie, przypnij commit runtime/branch w tasku instalacji.

## 3. Budowa

```bash
# 3.1 Baza (jak zwykle)
make build
BASE=$(ls -t output/wlb-general-*/wlb-general-*.qcow2 | head -1)

# 3.2 Flavor histologii (warstwowo na bazie):
packer build -only='wlb-histologia.*' \
  -var image_version=0.1.0 -var base_image="$BASE" packer/
```
Wynik: `output/wlb-histologia-0.1.0-<DATA>/wlb-histologia-0.1.0-<DATA>.qcow2` + checksum + manifest.

Po udanej budowie `ci/integration.sh` (etap 5) raportuje pojemność wirtualną i alokację qcow2 przez `ci/image-size-report.sh` (jak dla radiologii). Opcjonalny próg `WLB_IMAGE_SIZE_MAX_GIB` (ciąg cyfr, GiB) kończy krok przed akceptacją przy przekroczeniu.

## 4. Weryfikacja

### 4.1 Automatyczna (akceptacja)
Fragment `tests/acceptance.d/47-histologia.sh` (adaptacyjny — aktywny tylko na wlb-histologia) sprawdza: Calc (CSV→ODS), RStudio (`rserver`, usługa samodzielna wyłączona, `jupyter_rsession_proxy`) oraz jamovi (instalacja Flatpak, kafelek, override `/workspace` i — **gatingowo** — start sandboxa bwrap przez nieuprzywilejowane userns). Uruchom: `make test-up` (z tym obrazem) + `make test`.

### 4.2 Ręczna (w uruchomionej VM, jako root)
```bash
grep -x "WLB_IMAGE_NAME=wlb-histologia" /etc/wlb/image-release
flatpak info --system org.jamovi.jamovi                     # jamovi zainstalowany
flatpak info --system --show-permissions org.jamovi.jamovi  # ma filesystem=/workspace
flatpak run --command=sh org.jamovi.jamovi -c 'echo OK'     # sandbox bwrap startuje (userns)
test -x /usr/lib/rstudio-server/bin/rserver && echo RStudio-OK
libreoffice --headless --version | head -1
```

### 4.3 GUI (przez pulpit)
Zaloguj się do huba, kafelek **„Desktop"** w Launcherze → pulpit XFCE → uruchom **jamovi** (kafelek w menu Nauka) i **Calc**. RStudio: osobny kafelek **„RStudio"** w Launcherze JupyterLab (proxy, nie pulpit).

## 5. Tryby błędów

| Objaw | Przyczyna / naprawa |
|---|---|
| task `Instalacja jamovi z Flathub` timeout/sieć | build wymaga dostępu do `flathub.org`/`dl.flathub.org` — dopisz do allowlisty/proxy (patrz §1) |
| akceptacja: `sandbox bwrap startuje (userns)` FAIL | utwardzenie bazy twardo zablokowało nieuprzywilejowane userns (#63/#65). Potrzebny profil AppArmor dopuszczający `bwrap`/flatpak mimo `apparmor_restrict_unprivileged_userns` — dodać w roli base/histo_apps (follow-up) |
| jamovi nie widzi plików z `/workspace` | brak/utrata override — `flatpak override --system --filesystem=/workspace org.jamovi.jamovi` (task w roli) |
| kafelek jamovi „No such file or directory" w menu | `Exec` nieabsolutny — musi być `/usr/bin/flatpak run org.jamovi.jamovi` (#199) |
| RStudio: osobna usługa `rstudio-server` aktywna | ma być **wyłączona** (dostęp tylko przez hub); patrz rola `rstudio` |
| `No space left` w buildzie | podbij `histologia_disk_size` |

## 5a. Bramka CI (opt-in, #108)

Flavor jest budowany i testowany w CI (etap 5), ale **tylko na żądanie** — bez kosztu na każdym PR:
- etykieta **`build-histologia`** na PR, **albo**
- zmiana plików flavora (`ansible/roles/{histo_apps,desktop,rstudio}`, `ansible/histologia.yml`, `packer/wlb-histologia.pkr.hcl`, `tests/acceptance.d/{40-pulpit,47-histologia}.sh`) — wykrywa `ci/changes.sh` (`histologia_change`), **albo**
- nocny pełny build.

Wtedy po bazie `ci/integration.sh` buduje histologię (`histologia_flavor`) i uruchamia tę samą akceptację. Łapie błędy runtime (instalacja jamovi, start sandboxa userns), których lint nie wykryje. Ręczny build z tego runbooka pozostaje zawsze dostępny.

## 6. Uwagi

- jamovi niesie **własny, sandboxowany R** (w Flatpaku) — niezależny od CRAN R obrazu używanego przez RStudio. To świadome: dwa niezależne stosy statystyczne, bez kolizji ABI.
- To warstwa; zmiana aplikacji = edycja roli `histo_apps` + ponowny build warstwy (baza bez zmian).
- jamovi/JASP odrzucone na wlb-memory (lekki flavor) jako Flatpak; tu akceptujemy Flatpak, bo flavor ma pulpit i dedykowaną pojemność.
