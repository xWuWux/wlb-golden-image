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

Objaw: hub nie wstaje albo konta/hasła nie działają, ale pliki w `/workspace` są. Odtwarzamy przy **zatrzymanym** hubie i **zatrzymanym** timerze kopii zapasowych, żeby nie nadpisać kopii bieżącym (uszkodzonym) stanem. Pełna procedura: `docs/runbook-kopia-bazy-huba.md`.

#### Podstawowa ścieżka odtworzenia (jedno źródło prawdy: `wlb-hub-db-restore`)

Do odtworzenia bazy służy skrypt `/usr/local/sbin/wlb-hub-db-restore` (#288, #306). Zapewnia on atomową podmianę bazy, weryfikację spójności przed zatrzymaniem usług, zabezpieczenie bieżącego stanu do katalogu dowodowego oraz automatyczny rollback w razie błędu.

```bash
# Odtworzenie z najnowszej spójnej kopii w /workspace/.wlb-hub/backup/:
/usr/local/sbin/wlb-hub-db-restore

# Lub odtworzenie ze wskazanej kopii (np. ze snapshotu storage):
/usr/local/sbin/wlb-hub-db-restore --from /workspace/.wlb-hub/backup/jupyterhub-20261119T100000Z.sqlite
```

**Interfejs CLI i zmienne środowiskowe:**
- `wlb-hub-db-restore [--from PLIK] [--no-start]`
  - `--from PLIK` — ścieżka do pliku kopii (domyślnie najnowsza poprawna kopia z `BACKUP_DIR`).
  - `--no-start` — pomija uruchomienie huba po odtworzeniu (np. przed inspekcją offline).
- Zmienne środowiskowe (z wartościami domyślnymi):
  - `HUB_DB` (`/workspace/.wlb-hub/jupyterhub.sqlite`) — lokalizacja bazy huba.
  - `BACKUP_DIR` (`/workspace/.wlb-hub/backup`) — katalog z kopiami zapasowymi.
  - `FORENSIC_DIR` (`/workspace/.wlb-hub/przed-odtworzeniem`) — katalog dowodowy na stan sprzed odtworzenia.
  - `HUB_UNIT` (`jupyterhub`) — nazwa jednostki systemd huba.
  - `TIMER_UNIT` (`wlb-hub-db-backup.timer`) — timer cyklicznych kopii bazy.
  - `DB_OWNER` (`root:root`) — uprawnienia właściciela bazy.
  - `HUB_API_URL` (`http://127.0.0.1/hub/api`) — URL sondy zdrowia huba po restarcie.
- Kody wyjścia:
  - `0` — sukces (baza odtworzona, spójna, hub odpowiada na API).
  - `2` — błędne użycie (nieprawidłowe opcje CLI).
  - `3` — brak spójnej kopii (brak zmian w systemie, hub i timer nietknięte).
  - `4` — nie można zatrzymać huba (hub nadal aktywny).
  - `5` — nieudana podmiana bazy / błąd spójności po podmianie (automatyczny rollback).
  - `6` — hub nie wystartował lub nie odpowiada na API w zadanym czasie (automatyczny rollback).

> [!WARNING]
> **RPO i spójność kont po odtworzeniu (do 1h utraty zmian):**
> Odtworzenie bazy przywraca stan z momentu wykonania wybranej kopii. Oznacza to, że:
> - Konta utworzone po wykonaniu kopii nie będą istniały w bazie (wymagają ponownego założenia).
> - Konta usunięte lub zablokowane po wykonaniu kopii **zostaną przywrócone jako aktywne**!
> - Hasła zmienione po wykonaniu kopii zostaną cofnięte do stanu sprzed kopii.
> **Wymagane działanie operatora:** Po zakończeniu procedury odtworzenia operator ma obowiązek uzgodnić listę kont i przypisane role z autorytatywnym rejestrem źródłowym (wnioski o dostęp, system IAM / BP-VL) i natychmiast zablokować lub usunąć konta, które nie powinny mieć dostępu.

#### Awaryjna procedura ręczna (manual fallback)

Jeśli skrypt `wlb-hub-db-restore` jest niedostępny, należy ściśle wykonać poniższe kroki (zachowując zabezpieczenie dowodowe i zatrzymanie timera):

```bash
BK=/workspace/.wlb-hub/backup
DB=/workspace/.wlb-hub/jupyterhub.sqlite

# 1. Wybór najnowszej kopii przez find (nie ls) i weryfikacja spójności PRZED zatrzymaniem usług:
LATEST=$(find "$BK" -maxdepth 1 -type f -name 'jupyterhub-*.sqlite' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
[[ -n "$LATEST" ]] || { echo "BŁĄD: brak kopii w $BK" >&2; exit 1; }

# Pusta baza w SQLite daje 'ok' na PRAGMA integrity_check, dlatego test -s jest obowiązkowy:
test -s "$LATEST" || { echo "BŁĄD: kopia $LATEST jest pusta" >&2; exit 1; }
[[ $(sqlite3 "$LATEST" 'PRAGMA integrity_check;' 2>/dev/null) == ok ]] || { echo "BŁĄD: niespójna kopia" >&2; exit 1; }

# 2. Zatrzymanie huba oraz timera kopii (timer nie może wystartować w trakcie podmiany):
systemctl stop jupyterhub
systemctl stop wlb-hub-db-backup.timer

# 3. Zabezpieczenie dowodowe PRZED podmianą — przeniesienie bazy i dzienników (nigdy nie rm!):
# Usuwanie plików przed podmianą jest zabronione. SQLite doklei stary -wal, -shm lub -journal do nowej bazy,
# niszcząc jej spójność, dlatego wszystkie pliki stanu przenosimy atomowo do katalogu dowodowego:
FORENSIC="/workspace/.wlb-hub/przed-odtworzeniem/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$FORENSIC"
chmod 0700 "$FORENSIC"
for ext in "" "-wal" "-shm" "-journal"; do
  [[ -f "$DB$ext" ]] && mv -f "$DB$ext" "$FORENSIC/"
done

# 4. Atomowa instalacja kopii z weryfikacją sumy sha256 i testem spójności:
part="$DB.part"
install -m 0600 -o root -g root "$LATEST" "$part"
sync
[[ $(sha256sum "$part" | cut -d' ' -f1) == $(sha256sum "$LATEST" | cut -d' ' -f1) ]] || {
  rm -f "$part"
  echo "BŁĄD: rozbieżność sum sha256" >&2
  # Rollback:
  for f in "$FORENSIC"/*; do [[ -e "$f" ]] && mv -f "$f" "$(dirname "$DB")/"; done
  systemctl start wlb-hub-db-backup.timer
  exit 1
}
mv -f "$part" "$DB"
test -s "$DB" && [[ $(sqlite3 "$DB" 'PRAGMA integrity_check;' 2>/dev/null) == ok ]] || {
  echo "BŁĄD: odtworzona baza niespójna" >&2
  # Rollback:
  rm -f "$DB" "$DB-wal" "$DB-shm" "$DB-journal"
  for f in "$FORENSIC"/*; do [[ -e "$f" ]] && mv -f "$f" "$(dirname "$DB")/"; done
  systemctl start wlb-hub-db-backup.timer
  exit 1
}

# 5. Uruchomienie huba i timera oraz weryfikacja API:
systemctl start jupyterhub
systemctl start wlb-hub-db-backup.timer
curl -sf -o /dev/null http://127.0.0.1/hub/api && echo "hub OK"
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
- Testy (żywa VM): `tests/acceptance-remote.sh` sekcja 9 i `tests/acceptance.d/99-dr-odtworzenie-bazy.sh` (DR drill — próba odtworzenia po uszkodzeniu bazy, #288), `tests/migration-remote.sh` (wymiana obrazu z zachowaniem bazy).
- DoD: #49 (scenariusz odtworzenia), #61 (kopia przed snapshotem).
