# RB: Budowa i weryfikacja flavora wlb-radiologia

**Rola:** Administrator Platformy / Operator budowy obrazu
**Odniesienia:** #135 (flavor), #106 (pulpit), #134 (decyzje/licencja FSL), #71 (storage/rozmiar)
**Co to:** warstwowy obraz `wlb-radiologia` = `wlb-general` + pulpit (rola `desktop`) + stos neuroobrazowania (rola `neuro_apps`: FSL z FSLeyes, 3DSlicer). Obraz bazowy zostaje lekki.

## 1. Wymagania wstępne

- KVM i narzędzia: `make doctor` zielone.
- **Sieć w trakcie buildu** (gotowa VM jest offline): conda-forge, serwery FSL (`fsl.fmrib.ox.ac.uk`), Kitware (`slicer-packages.kitware.com`).
- **Dużo miejsca i czasu:** FSL (conda-based) to dziesiątki GB; `radiologia_disk_size` = 80G. Build bazy ~30 min + instalacja FSL (długa) + 3DSlicer (~0,5 GB pobrania).
- Zasoby (stack DICOM na porcie 8080): przy równoległej pracy ustaw `VM_MEMORY=6144`.

## 2. Przypięte wersje (w `ansible/group_vars/all.yml`)

- `fsl_version: 6.0.7.22` · `slicer_version: 5.12.4` (+ URL item Kitware i `slicer_sha512`).
- **Aktualizacja wersji** (gdy trzeba): FSL — manifest `https://fsl.fmrib.ox.ac.uk/fsldownloads/fslconda/releases/manifest.json`; 3DSlicer — redirect `https://download.slicer.org/download?os=linux&stability=release` → item Kitware; sumę weź z `…/item/<id>/files` (pole `sha512`).

## 3. Budowa

```bash
# 3.1 Baza (jak zwykle)
make build
BASE=$(ls -t output/wlb-general-*/wlb-general-*.qcow2 | head -1)

# 3.2 Flavor radiologiczny (warstwowo na bazie). Buduje też wlb-memory — można zawęzić:
packer build -only='wlb-radiologia.*' \
  -var image_version=0.1.0 -var base_image="$BASE" packer/
```
Wynik: `output/wlb-radiologia-0.1.0-<DATA>/wlb-radiologia-0.1.0-<DATA>.qcow2` + checksum + manifest.

Rozmiar sprawdź od razu: `qemu-img info output/wlb-radiologia-*/*.qcow2`.

## 4. Weryfikacja

### 4.1 Automatyczna (akceptacja)
Fragment `tests/acceptance.d/70-radiologia.sh` (adaptacyjny — aktywny tylko na wlb-radiologia) sprawdza: `/etc/wlb/image-release`, `fslversion`, `fslmaths`, `fsleyes`, `Slicer`. Uruchom akceptację na zbudowanym obrazie przez `make test-up` (z tym obrazem) + `make test`.

### 4.2 Ręczna (w uruchomionej VM, jako root)
```bash
grep -x "WLB_IMAGE_NAME=wlb-radiologia" /etc/wlb/image-release
cat /usr/local/fsl/etc/fslversion                      # wersja FSL
/usr/local/fsl/share/fsl/bin/fslmaths                  # wypisze pomoc = działa
test -x /usr/local/fsl/share/fsl/bin/fsleyes && echo FSLeyes-OK
Slicer --help | head                                   # symlink /usr/local/bin/Slicer
```

### 4.3 GUI (przez pulpit)
Zaloguj się do huba, kafelek **„Desktop"** w Launcherze → pulpit XFCE → uruchom **FSLeyes** i **3DSlicer**. (Zgodność pulpitu — idle culler/OOM/schowek — wg runbooka #106.)

## 5. Tryby błędów

| Objaw | Przyczyna / naprawa |
|---|---|
| `fslinstaller` pada / zła flaga | `python3 fslinstaller.py --help`; dostosuj polecenie/`fsl_version` w roli `neuro_apps` |
| `fslmaths`/`fsleyes` nie ma pod `share/fsl/bin` | nowsza struktura FSL — popraw ścieżki w `/etc/profile.d/fsl.sh` (rola) i w `70-radiologia.sh` |
| 3DSlicer: `checksum mismatch` | wersja się zmieniła → zaktualizuj `slicer_url` (item) + `slicer_sha512` (z `item/<id>/files`) |
| `No space left` w buildzie | podbij `radiologia_disk_size` |
| timeout/sieć przy FSL/Kitware | build wymaga internetu; sprawdź proxy/mirror |

## 6. Uwagi

- **Rozmiar qcow2** będzie bardzo duży (FSL) — uwzględnij w storage/wydaniach (#71).
- Licencja FSL: użytek niekomercyjny/akademicki — potwierdzone (#134).
- To warstwa; zmiana wersji FSL/Slicer = edycja `group_vars` + ponowny build warstwy (baza bez zmian).
