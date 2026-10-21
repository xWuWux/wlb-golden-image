# RB-05: Aktualizacja obrazu VM Laboratorium i wycofanie (rollback)

**Rola:** Administrator Platformy / Operator DevOps
**Odniesienia:** OPZ DOK.10, §9.5, §20, §22; DoD Tier 4 (#13, #106, #62); #8, #12, #15
**Zależności:** hypervisor (#15), spójna kopia bazy (#8), wydania (#12)

> Procedura techniczna na VM. Proces (okno serwisowe, komunikacja) należy do platformy (BP-VL).

## 1. Fakty o obrazie, na których stoi ta procedura

Zweryfikowane w kodzie — nie zgadywać ścieżek:

| Element | Wartość | Źródło |
|---|---|---|
| Baza huba (konta, hasła) | `/workspace/.wlb-hub/jupyterhub.sqlite` | `group_vars/all.yml` → `tljh_hub_db_path`, `10-wlb.py.j2` |
| Katalog kopii bazy | `/workspace/.wlb-hub/backup/` | `hub_db_backup_dir` |
| Kolejka eksportu | wartość `WLB_EXPORT_QUEUE` z `/etc/wlb/image.conf` (`/workspace/.wlb-export-queue`) | `lab_config` |
| Dysk roboczy `/workspace` | **`/dev/vdb`** (virtio), `LABEL=workspace` | `cloud-init/lab-user-data.example.yaml` |
| Migracja schematu bazy | `c.JupyterHub.upgrade_db = True` — **migruje w miejscu przy starcie huba** | `10-wlb.py.j2` |

**Kluczowe:** hub startuje przy boocie i **migruje bazę ZANIM** zadziała `wlb-firstboot` (cloud-init runcmd). Dlatego kopia sprzed migracji jest robiona automatycznie przez **`ExecStartPre` jednostki jupyterhub** (`/opt/wlb/bin/wlb-hub-db-preupgrade`): przy pierwszym starcie nowej wersji zapisuje `/workspace/.wlb-hub/backup/jupyterhub.sqlite.pre-<poprzednia_wersja>` i nie nadpisuje jej przy kolejnych startach. To jest punkt powrotu rollbacku.

## 2. Warunki wstępne

1. **Okno serwisowe** ogłoszone badaczom (≥24 h). Sesje żyją do 12 h (§9.5, `cull.max_age`).
2. **Kolejka eksportu pusta** albo pisemna zgoda Kontrolera Przesyłu Danych:
   ```sh
   q=$(sed -n 's/^WLB_EXPORT_QUEUE=//p' /etc/wlb/image.conf); ls -A "$q"
   ```
3. **Nowy `user-data` ma `overwrite: false`** na `/dev/vdb` (inaczej formatuje `/workspace`):
   ```yaml
   disk_setup: { /dev/vdb: { overwrite: false } }
   ```
4. Dostępny poprzedni obraz (`.qcow2`) do ewentualnego powrotu.

## 3. Aktualizacja (obraz w przód)

1. **Komunikat i wstrzymanie ruchu** — przez bramkę/portal platformy (poza VM).
2. **Jawna kopia bazy + migawka wolumenu** (podstawowy punkt powrotu, obok automatycznej):
   ```sh
   sudo /opt/tljh/hub/bin/... ; sudo /opt/wlb/bin/wlb-hub-db-backup   # online .backup (#8) do /workspace/.wlb-hub/backup/
   ```
   oraz migawka wolumenu `/workspace` na poziomie storage (Ceph/NFS, #19).
3. **Wymiana dysku systemowego** (roboczy `/dev/vdb` zostaje): odepnij stary obraz systemowy, podepnij nowy (`wlb-general-<nowa>.qcow2` lub `wlb-memory-...`), uruchom VM. Automatycznie: `ExecStartPre` robi kopię `pre-<poprzednia_wersja>`, hub migruje schemat, `wlb-firstboot` odtwarza konta `jupyter-<login>` z `/workspace` i przeładowuje hub.
4. **Weryfikacja** — użyć istniejącego testu zamiast ręcznych kroków:
   ```sh
   sudo tests/migration-remote.sh verify <UID> <HASŁO> <HASŁO_ADMINA>
   ```
   sprawdza: zachowany UID, logowanie starym hasłem badacza i Administratora Klienta, brak nowego hasła admina, działanie huba po migracji, wniosek eksportu w kolejce. Dodatkowo `cat /etc/wlb/image-release` (nowa `WLB_IMAGE_VERSION`), `cat /var/lib/wlb/firstboot.done`.

## 4. Wycofanie (rollback)

Uruchomić przy błędzie krytycznym (nieudana migracja, hub nie wstaje, uszkodzony profil).

1. **Zatrzymaj VM** z hypervisora (`openstack server stop …` / `qm stop <vmid>`).
2. **Przywróć bazę sprzed migracji** — z wolumenem `/workspace` podpiętym (tryb ratunkowy albo przed ponownym startem huba), zatrzymanym hubem:
   ```sh
   sudo systemctl stop jupyterhub traefik
   pre=/workspace/.wlb-hub/backup/jupyterhub.sqlite.pre-<poprzednia_wersja>
   sudo install -o root -g root -m 0600 "$pre" /workspace/.wlb-hub/jupyterhub.sqlite
   ```
   > Przywracamy **na `/workspace`** (tam żyje baza), nie do `/opt/tljh/state`. Stary hub nie odczyta nowego schematu — dlatego kolejność: najpierw przywróć bazę, potem startuj stary obraz.
3. **Podepnij poprzedni obraz systemowy** (`wlb-general-<poprzednia>.qcow2`), uruchom VM.
4. **Weryfikacja** jak w pkt 3.4 (`tests/migration-remote.sh verify …`) — stary hub wstaje ze starym schematem, hasła działają.
5. **Zgłoś incydent** nieudanej aktualizacji wg RB-09.

## 5. Dokumentacja

Wpis w dzienniku zmian Laboratorium (wersja przed/po, wynik), informacja do SIEM o stanie wdrożenia, przywrócenie dostępności portalu.

## 6. Tryby błędów

- **Hub nie wstaje po aktualizacji** → rollback (sekcja 4).
- **Brak `pre-<wersja>`** (np. best-effort `ExecStartPre` zawiodło) → użyj najnowszej kopii z `/workspace/.wlb-hub/backup/` (#8, godzinna) — może być do 1 h starsza.
- **`/workspace` sformatowany** (błąd `overwrite`) → odtworzenie z migawki storage (RB-07c, #19).

## 7. Przećwiczenie (DoD #106/#62)

Scenariusz wycofania automatyzuje `tests/migration.sh <stary.qcow2> <nowy.qcow2> --rollback`: stary → migracja → verify → przywrócenie `pre-<wersja>` → powrót na stary obraz → verify. Pełny test schematu wymaga dwóch obrazów o różnych wersjach JupyterHub.
