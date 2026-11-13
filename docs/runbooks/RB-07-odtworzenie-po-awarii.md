# RB-07: Odtworzenie Laboratorium po awarii (VM, dysk roboczy, baza huba, kolejka)

**Rola:** Administrator Platformy / Operator DevOps
**Odniesienia:** Regulamin §22 (kopie/DR, retencja ≥30 dni); DoD Tier 4 (#13, #49, #61); #8 (kopia bazy huba), #15 (hypervisor), #19 (storage/snapshot)
**Zależności:** hypervisor (#15), storage ze snapshotami (#19, Ceph), kopia bazy huba (#8)

> Procedura techniczna na VM i platformie. Decyzja *kiedy* odtwarzać i komunikacja z badaczami należą do platformy (BP-VL); snapshoty i crypto-erase wolumenu to warstwa storage (#19).

## 1. Fakty (zweryfikowane w kodzie)

Nie zgadywać ścieżek:

| Element | Wartość | Źródło |
|---|---|---|
| Dysk roboczy `/workspace` | **`/dev/vdb`** (virtio), `LABEL=workspace`, ext4 — **trwały** | `cloud-init/lab-user-data.example.yaml` |
| Dysk systemowy | z obrazu, **jednorazowy** (wymieniany przy aktualizacji) | tamże (komentarz „systemowy … jednorazowy") |
| Ochrona przed reformatem | `disk_setup: /dev/vdb: overwrite: false`; `fs_setup` pomija istniejący ext4 | tamże |
| Baza huba (konta, hasła) | `/workspace/.wlb-hub/jupyterhub.sqlite` | `group_vars/all.yml` → `tljh_hub_db_path` |
| Kopie bazy (rotacja 24, ~1 doba) | `/workspace/.wlb-hub/backup/jupyterhub-<UTC>.sqlite` | `hub_db_backup_dir`; timer `wlb-hub-db-backup` |
| Kopia sprzed migracji (rollback) | `/workspace/.wlb-hub/backup/jupyterhub.sqlite.pre-<wersja>` | `ExecStartPre` → `/opt/wlb/bin/wlb-hub-db-preupgrade` |
| Kolejka eksportu | `WLB_EXPORT_QUEUE` z `/etc/wlb/image.conf` (`/workspace/.wlb-export-queue`) | `lab_config` |
| Migracja schematu bazy | `c.JupyterHub.upgrade_db = True` — w miejscu przy starcie huba | `10-wlb.py.j2` |

**Kluczowe:** wszystko, co trwałe (konta, hasła, dane badaczy, kolejka eksportu, kopie bazy), leży na **`/workspace` (`/dev/vdb`)**. Dysk systemowy jest odtwarzalny z obrazu. Dlatego DR sprowadza się do: **odzyskać wolumen roboczy → wstać hub → (w razie potrzeby) odtworzyć bazę → sprawdzić kolejkę.**

## 2. Kolejność odtwarzania (zawsze ta sama)

`wolumen /workspace` → `hub` → `baza huba` → `kolejka eksportu`.

Odwrotna kolejność grozi migracją lub nadpisaniem bazy, zanim potwierdzisz jej spójność (hub przy starcie migruje bazę **w miejscu**).

## 3. Scenariusze awarii

### RB-07a — VM nie startuje / uszkodzony dysk systemowy (dysk roboczy nienaruszony)

Dysk systemowy jest jednorazowy. Odtwarzamy VM z obrazu i **ponownie podłączamy** istniejący `/dev/vdb`.

1. Zatrzymaj/odłącz uszkodzoną VM — **nie kasuj wolumenu roboczego** `/dev/vdb`.
2. Potwierdź, że `user-data` ma `disk_setup: /dev/vdb: overwrite: false` (inaczej re-provision **sformatuje** `/workspace`).
3. Utwórz nową VM z tego samego obrazu + tego samego `user-data`/`lab.env`; podłącz istniejący wolumen jako `/dev/vdb`.
4. Boot. Hub przy starcie migruje bazę w miejscu (kopia sprzed migracji powstaje automatycznie przez `ExecStartPre`); `wlb-firstboot` odtwarza prawa i udziały.
5. Weryfikacja (sekcja 4).

> Jeśli po boocie `/workspace` jest pusty lub świeżo sformatowany → to był błąd `overwrite`; przejdź do **RB-07c** (odtworzenie ze snapshotu).

### RB-07b — baza huba uszkodzona (dysk roboczy OK)

Objaw: hub nie wstaje albo konta/hasła nie działają, ale pliki w `/workspace` są. Odtwarzamy przy **zatrzymanym** hubie, żeby nie nadpisać kopii bieżącym (uszkodzonym) stanem. Pełna procedura: `docs/runbook-kopia-bazy-huba.md`.

```bash
BK=/workspace/.wlb-hub/backup
DB=/workspace/.wlb-hub/jupyterhub.sqlite

LATEST=$(ls -1 "$BK"/jupyterhub-*.sqlite | sort | tail -1); echo "$LATEST"
sqlite3 "$LATEST" 'PRAGMA integrity_check;'                       # ma zwrócić: ok

systemctl stop jupyterhub
# 2a. Usuń stary WAL/SHM: bez tego SQLite doklei dziennik do odtworzonej bazy
#     i „spójna” kopia może w praktyce wrócić uszkodzona.
rm -f "$DB-wal" "$DB-shm"
cp -a "$DB" "$DB.przed-odtworzeniem-$(date -u +%Y%m%dT%H%M%SZ)"
install -m 0600 -o root -g root "$LATEST" "$DB"
systemctl start jupyterhub
```

> Nieudana **aktualizacja obrazu** (rollback) ma własny punkt powrotu `jupyterhub.sqlite.pre-<wersja>` — patrz **RB-05**, nie ta procedura.

### RB-07c — dysk roboczy `/workspace` utracony/uszkodzony/sformatowany (#19)

Jedyny scenariusz, w którym tracimy dane, jeśli nie ma snapshotu. Źródłem DR jest **snapshot storage (Ceph)**.

1. **(Warstwa storage, #19)** Odtwórz wolumen roboczy z najnowszego **spójnego** snapshotu Ceph.
2. Podłącz odtworzony wolumen jako `/dev/vdb`; zamontuj `LABEL=workspace` → `/workspace`.
3. Kopie bazy (`.wlb-hub/backup/`) są w snapshocie. Jeśli `jupyterhub.sqlite` z snapshotu jest niespójny, odtwórz jak w **RB-07b** z najnowszej spójnej kopii znalezionej w snapshocie.
4. Boot / start huba → weryfikacja.

> Historia snapshotów dłuższa niż ~1 doba jest po stronie storage (lokalne kopie bazy rotują ~24 h). Dobór snapshotu = kompromis RPO uzgodniony z Liderem Projektu.

### RB-07d — kolejka eksportu utknęła/uszkodzona

Objaw: nowe pliki nie znikają ze śluzy, kolejka wstrzymana (badacz zgłasza przez HelpDesk).

1. Sprawdź stan kolejki:
   ```bash
   q=$(sed -n 's/^WLB_EXPORT_QUEUE=//p' /etc/wlb/image.conf); ls -la "$q"
   ```
2. Diagnoza i działania operatora wg **tabeli punktów awarii** w `docs/runbooks/RB-eksport-kolejka.md` (zablokowany wpis, uszkodzony manifest v1).
3. Odblokuj kolejkę. **Nie** publikuj ani nie kasuj wpisów wg wymyślonej retencji — retencja/usuwanie to IMG-006/IMG-007 (patrz RB-08).

## 4. Weryfikacja po odtworzeniu

```bash
curl -sf -o /dev/null http://127.0.0.1/hub/api && echo "hub OK"
findmnt /workspace                                   # LABEL=workspace, ext4
ls -ld /workspace/.wlb-hub /workspace/.wlb-export-queue
systemctl is-active jupyterhub wlb-hub-db-backup.timer
```

- Zaloguj się kontem badacza/administratora — hasła sprzed awarii działają.
- Dane badaczy w `/workspace/jupyter-<login>` obecne.
- Obserwowalność: `systemctl is-active prometheus-node-exporter wlb-health` (patrz `RB-wlb-health`).

## 5. Czego ta procedura NIE obejmuje

- Decyzji *kiedy* odtwarzać i komunikacji okna serwisowego — proces platformy (BP-VL), jak w RB-05.
- Mechaniki snapshotów i crypto-erase wolumenu — warstwa storage (#19).
- Aktualizacji i rollbacku wersji obrazu — **RB-05**.
- Trwałego usunięcia danych przy zamknięciu projektu — **RB-08** (IMG-006).

## Powiązania

- Kopia i odtworzenie bazy huba: `docs/runbook-kopia-bazy-huba.md` (#8).
- Aktualizacja i rollback obrazu: `RB-05` (punkt powrotu `jupyterhub.sqlite.pre-<wersja>`).
- Kolejka eksportu: `RB-eksport-kolejka.md`.
- Zamknięcie Laboratorium / trwałe usunięcie: `RB-08` (#13, IMG-006).
- Incydent nieudanego odtworzenia: `RB-09`.
- Testy (żywa VM): `tests/acceptance-remote.sh` sekcja 9 i `tests/acceptance.d/80-dr-odtworzenie-bazy.sh` (DR drill — próba odtworzenia po uszkodzeniu bazy, #288), `tests/migration-remote.sh` (wymiana obrazu z zachowaniem bazy).
- DoD: #49 (scenariusz odtworzenia), #61 (kopia przed snapshotem).
