# Runbook: kopia i odtworzenie bazy huba (#8)

Baza huba (konta Native Authenticator, hasła, uprawnienia admina) leży na dysku roboczym:
`/workspace/.wlb-hub/jupyterhub.sqlite`. Backup dysku roboczego robi się na poziomie storage
(snapshot Ceph), a snapshot **działającej** bazy SQLite bywa niespójny. Dlatego timer robi spójną
migawkę online (`sqlite3 .backup`) do katalogu, który wchodzi do snapshotu jako gotowy plik.

## Jak to działa

- **Skrypt:** `/usr/local/sbin/wlb-hub-db-backup` — `sqlite3 .backup` (spójna kopia działającej bazy),
  `PRAGMA integrity_check`, atomowy `mv`, rotacja. Nie failuje, gdy bazy jeszcze nie ma (przed
  pierwszym logowaniem); failuje, gdy kopia nie przejdzie `integrity_check` (nie rotuje wtedy dobrych
  kopii).
- **Usługa/timer:** `wlb-hub-db-backup.service` (oneshot) + `wlb-hub-db-backup.timer`
  (`OnBootSec=5min`, `OnCalendar=hourly`, `Persistent=true`).
- **Kopie:** `/workspace/.wlb-hub/backup/jupyterhub-<UTC>.sqlite`, prawa `0600` root, rotacja do
  `hub_db_backup_keep` (domyślnie 24 — przy `hourly` ~1 doba na dysku roboczym; dłuższa historia
  jest w snapshotach storage).
- **Konfiguracja** (`ansible/group_vars/all.yml`): `hub_db_backup_dir`, `hub_db_backup_keep`,
  `hub_db_backup_oncalendar`.

## Sprawdzenie stanu

```bash
systemctl status wlb-hub-db-backup.timer          # następne uruchomienie
systemctl list-timers wlb-hub-db-backup.timer
ls -l /workspace/.wlb-hub/backup/                  # kopie, czasy, rozmiary
journalctl -t wlb-hub-db-backup -n 20             # log ostatnich przebiegów (→ SIEM)
```

## Kopia na żądanie (np. przed ryzykowną operacją)

```bash
systemctl start wlb-hub-db-backup.service
```

## Odtworzenie bazy z kopii

Kryterium: po odtworzeniu konta i hasła badaczy działają. Odtwarzamy przy **zatrzymanym** hubie i **zatrzymanym** timerze kopii zapasowych,
żeby nie nadpisać kopii bieżącym (być może uszkodzonym) stanem.

### Podstawowa ścieżka odtworzenia (jedno źródło prawdy: `wlb-hub-db-restore`)

Standardową, zautomatyzowaną metodą przywrócenia bazy jest skrypt `/usr/local/sbin/wlb-hub-db-restore` (#288, #306).
Skrypt weryfikuje spójność kopii przed jakimkolwiek zatrzymaniem usług, zabezpiecza bieżącą bazę oraz wszystkie dzienniki
(`-wal`, `-shm`, `-journal`) w katalogu dowodowym, wykonuje atomową podmianę i zapewnia automatyczny rollback w razie błędu.

```bash
# Domyślnie z najnowszej spójnej kopii w /workspace/.wlb-hub/backup/:
/usr/local/sbin/wlb-hub-db-restore

# Ze wskazanej kopii (np. wyciągniętej ze snapshotu Ceph lub innego katalogu):
/usr/local/sbin/wlb-hub-db-restore --from /workspace/.wlb-hub/backup/jupyterhub-20261119T100000Z.sqlite
```

**Interfejs CLI i zmienne środowiskowe:**
- `wlb-hub-db-restore [--from PLIK] [--no-start]`
  - `--from PLIK` — ścieżka do pliku kopii SQLite (domyślnie najnowsza poprawna z `BACKUP_DIR`).
  - `--no-start` — pomija uruchomienie usługi huba po odtworzeniu.
- Zmienne środowiskowe:
  - `HUB_DB` (`/workspace/.wlb-hub/jupyterhub.sqlite`) — ścieżka docelowa bazy huba.
  - `BACKUP_DIR` (`/workspace/.wlb-hub/backup`) — katalog z kopiami.
  - `FORENSIC_DIR` (`/workspace/.wlb-hub/przed-odtworzeniem`) — katalog na kopię dowodową uszkodzonej bazy.
  - `HUB_UNIT` (`jupyterhub`) — jednostka systemd huba.
  - `TIMER_UNIT` (`wlb-hub-db-backup.timer`) — jednostka timera kopii.
  - `DB_OWNER` (`root:root`) — uprawnienia właściciela bazy po instalacji.
  - `HUB_API_URL` (`http://127.0.0.1/hub/api`) — URL sprawdzany sondą curl po restarcie.
- Kody wyjścia:
  - `0` — sukces (baza odtworzona, spójna, hub odpowiada na API).
  - `2` — błędne parametry CLI.
  - `3` — brak spójnej kopii (brak zmian w systemie).
  - `4` — hub nadal aktywny (nie można zatrzymać usługi).
  - `5` — nieudana podmiana bazy / błąd integrity_check (automatyczny rollback).
  - `6` — hub nie odpowiada na API po podmianie (automatyczny rollback).

> [!WARNING]
> **RPO i spójność kont po odtworzeniu (do 1h utraty zmian):**
> Odtworzenie bazy przywraca stan z momentu wykonania wybranej kopii. Oznacza to, że:
> - Konta utworzone po wykonaniu kopii nie będą istniały w bazie (wymagają ponownego założenia).
> - Konta usunięte lub zablokowane po wykonaniu kopii **zostaną przywrócone jako aktywne**!
> - Hasła zmienione po wykonaniu kopii zostaną cofnięte do stanu sprzed kopii.
> **Wymagane działanie operatora:** Po zakończeniu procedury odtworzenia operator ma obowiązek uzgodnić listę kont i przypisane role z autorytatywnym rejestrem źródłowym (wnioski o dostęp, system IAM / BP-VL) i natychmiast zablokować lub usunąć konta, które nie powinny mieć dostępu.

### Awaryjna procedura ręczna (manual fallback)

Jeśli skrypt `wlb-hub-db-restore` nie jest dostępny, operator wykonuje odtworzenie ręcznie wg poniższego schematu:

```bash
BK=/workspace/.wlb-hub/backup
DB=/workspace/.wlb-hub/jupyterhub.sqlite

# 1. Wybierz najnowszą kopię przez find (nie ls) i potwierdź jej spójność PRZED zatrzymaniem usług:
LATEST=$(find "$BK" -maxdepth 1 -type f -name 'jupyterhub-*.sqlite' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
[[ -n "$LATEST" ]] || { echo "BŁĄD: brak kopii w $BK" >&2; exit 1; }

# Pusta baza w SQLite daje 'ok' na PRAGMA integrity_check, dlatego test -s jest obowiązkowy:
test -s "$LATEST" || { echo "BŁĄD: kopia $LATEST jest pusta" >&2; exit 1; }
[[ $(sqlite3 "$LATEST" 'PRAGMA integrity_check;' 2>/dev/null) == ok ]] || { echo "BŁĄD: niespójna kopia" >&2; exit 1; }

# 2. Zatrzymaj hub oraz timer kopii (timer nie może wystartować w trakcie podmiany):
systemctl stop jupyterhub
systemctl stop wlb-hub-db-backup.timer

# 3. Zabezpieczenie dowodowe PRZED podmianą — przenieś bazę i wszystkie dzienniki (nigdy rm!):
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

# 5. Uruchomienie huba i timera oraz weryfikacja:
systemctl start jupyterhub
systemctl start wlb-hub-db-backup.timer
curl -sf -o /dev/null http://127.0.0.1/hub/api && echo "hub OK"
# zaloguj się kontem badacza/admina — hasła sprzed kopii działają
```

Jeśli odtwarzasz **cały dysk roboczy** ze snapshotu storage, kopie `jupyterhub-*.sqlite` są w nim
razem z resztą `/workspace` — użyj skryptu `wlb-hub-db-restore --from <ścieżka>` lub procedury awaryjnej jak wyżej.

## Powiązania

- Test odtworzenia (żywa VM): `tests/acceptance-remote.sh` sekcja 9 i `tests/acceptance.d/99-dr-odtworzenie-bazy.sh` (DR drill po uszkodzeniu bazy, #288); testy jednostkowe skryptu:
  `tests/unit/wlb-hub-db-restore.bats` (restore) i `tests/unit/wlb-hub-db-backup.bats` (kopia).
- Migracja/wymiana obrazu z zachowaniem bazy: `tests/migration-remote.sh`.
- DoD: domyka częściowo #61 (kopia przed snapshotem) i uzupełnia #49 (scenariusz odtworzenia).
