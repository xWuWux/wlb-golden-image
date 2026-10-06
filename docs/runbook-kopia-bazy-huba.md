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

Kryterium: po odtworzeniu konta i hasła badaczy działają. Odtwarzamy przy **zatrzymanym** hubie,
żeby nie nadpisać kopii bieżącym (być może uszkodzonym) stanem.

```bash
BK=/workspace/.wlb-hub/backup
DB=/workspace/.wlb-hub/jupyterhub.sqlite

# 1. Wybierz kopię (domyślnie najnowsza) i potwierdź jej spójność
LATEST=$(ls -1 "$BK"/jupyterhub-*.sqlite | sort | tail -1); echo "$LATEST"
sqlite3 "$LATEST" 'PRAGMA integrity_check;'        # ma zwrócić: ok

# 2. Zatrzymaj hub i zrób kopię bezpieczeństwa bieżącej bazy
systemctl stop jupyterhub
cp -a "$DB" "$DB.przed-odtworzeniem-$(date -u +%Y%m%dT%H%M%SZ)"

# 3. Podmień bazę na kopię (zachowaj właściciela i prawa) i wystartuj hub
install -m 0600 -o root -g root "$LATEST" "$DB"
systemctl start jupyterhub

# 4. Weryfikacja
curl -sf -o /dev/null http://127.0.0.1/hub/api && echo "hub OK"
# zaloguj się kontem badacza/admina — hasła sprzed kopii działają
```

Jeśli odtwarzasz **cały dysk roboczy** ze snapshotu storage, kopie `jupyterhub-*.sqlite` są w nim
razem z resztą `/workspace` — użyj najnowszej spójnej kopii tak samo jak wyżej.

## Powiązania

- Test odtworzenia (żywa VM): `tests/acceptance-remote.sh` sekcja 9; testy jednostkowe skryptu:
  `tests/unit/wlb-hub-db-backup.bats`.
- Migracja/wymiana obrazu z zachowaniem bazy: `tests/migration-remote.sh`.
- DoD: domyka częściowo #61 (kopia przed snapshotem) i uzupełnia #49 (scenariusz odtworzenia).
