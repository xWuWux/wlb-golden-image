#!/usr/bin/env bats
# wlb-hub-db-restore.bats — testy jednostkowe skryptu odtworzenia bazy huba (#306, #288, RB-07b).
#
# Testuje REALNY skrypt ansible/roles/tljh/files/wlb-hub-db-restore (nie inline cp/install),
# więc mutacje stage 4b (ci/mutations/bash-mutations.tsv) go zabijają. Pokrywa kluczowe
# ustalenia recenzji: przeniesienie -journal (nie tylko -wal/-shm), test -s przed integrity_check,
# atomową podmianę i — co najważniejsze — KONTROLĘ NEGATYWNĄ: gdy hub nie wstaje, skrypt zwraca 6
# i wykonuje rollback do bazy sprzed odtworzenia.

load helpers.bash

RESTORE="$REPO_ROOT/ansible/roles/tljh/files/wlb-hub-db-restore"
FIXTURES="$REPO_ROOT/tests/fixtures"

setup() {
  setup_sandbox
  command -v sqlite3 >/dev/null 2>&1 || skip "brak sqlite3"
  command -v python3 >/dev/null 2>&1 || skip "brak python3"

  HUB_DB="$SANDBOX/workspace/.wlb-hub/jupyterhub.sqlite"
  BACKUP_DIR="$SANDBOX/workspace/.wlb-hub/backup"
  FORENSIC_DIR="$SANDBOX/workspace/.wlb-hub/przed-odtworzeniem"
  mkdir -p "$(dirname "$HUB_DB")" "$BACKUP_DIR"
  export HUB_DB BACKUP_DIR FORENSIC_DIR
  export HUB_UNIT=jupyterhub-test TIMER_UNIT=wlb-hub-db-backup-test.timer
  export DB_OWNER="" # test jako nie-root: pomiń chown
  export HUB_API_URL="http://127.0.0.1/hub/api"

  # Stuby: systemctl zawsze OK; curl domyślnie OK (hub odpowiada). Testy negatywne nadpisują.
  # sleep 0, bo skrypt czeka do 60 s na API — bez tego test negatywny trwałby minutę
  # i przekraczał limit 60 s harnessu mutacji (etap 4b).
  stub systemctl 0
  stub curl 0
  stub sleep 0
}

# czysta kopia z rozpoznawalną zawartością (a01, u01) — to, co ma trafić do bazy po odtworzeniu
_backup_copy() {
  python3 - "$BACKUP_DIR/jupyterhub-20260101T000000Z.sqlite" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
c.executemany("INSERT INTO users(name) VALUES (?)", [("a01",), ("u01",)])
c.commit()
c.close()
PY
}

# żywa baza z PRAWDZIWYM gorącym dziennikiem (fixture opencode): zawiera konta baseline-*,
# a obok leży -journal, który przy pierwszym otwarciu cofnąłby/uszkodził NIEprzeniesioną kopię.
_hot_live() {
  python3 - "$HUB_DB" <<PY
import sys
sys.path.insert(0, "$FIXTURES")
from sqlite_hot_journal import make_hot_journal
make_hot_journal(sys.argv[1])
PY
}

@test "restore: baza = kopia, gorący -journal przeniesiony (nie cofa odtworzenia) (#306)" {
  _backup_copy
  _hot_live
  [ -f "$HUB_DB-journal" ] # fixture zostawił gorący dziennik

  run env PATH="$PATH" "$RESTORE"
  [ "$status" -eq 0 ]

  # Baza zawiera konta z KOPII (a01,u01), nie baseline z żywej bazy → podmiana się odbyła
  run sqlite3 "$HUB_DB" "SELECT count(*) FROM users WHERE name IN ('a01','u01');"
  [ "$output" = "2" ]
  # Gorący dziennik NIE leży już obok bazy (przeniesiony do katalogu dowodowego)
  [ ! -e "$HUB_DB-journal" ]
  # sha256 odtworzonej bazy == kopia
  [ "$(sha256sum "$HUB_DB" | cut -d' ' -f1)" = "$(sha256sum "$BACKUP_DIR/jupyterhub-20260101T000000Z.sqlite" | cut -d' ' -f1)" ]
}

@test "restore: baza i dzienniki trafiają do katalogu dowodowego (#306)" {
  _backup_copy
  _hot_live
  run env PATH="$PATH" "$RESTORE"
  [ "$status" -eq 0 ]
  # w FORENSIC_DIR/<ts>/ jest zarówno stara baza, jak i jej -journal
  run bash -c "find '$FORENSIC_DIR' -name 'jupyterhub.sqlite' | head -1"
  [ -n "$output" ]
  run bash -c "find '$FORENSIC_DIR' -name 'jupyterhub.sqlite-journal' | head -1"
  [ -n "$output" ]
}

@test "restore: pusta kopia nie udaje spójnej → exit 3 (#306)" {
  : >"$BACKUP_DIR/jupyterhub-20260101T000000Z.sqlite" # pusty plik
  _hot_live
  run env PATH="$PATH" "$RESTORE"
  [ "$status" -eq 3 ]
}

@test "restore: brak jakiejkolwiek kopii → exit 3, bez zmian w bazie (#306)" {
  _hot_live
  local before
  before=$(sha256sum "$HUB_DB" | cut -d' ' -f1)
  run env PATH="$PATH" "$RESTORE"
  [ "$status" -eq 3 ]
  # baza nietknięta (nie zatrzymano/nie przeniesiono niczego)
  [ "$(sha256sum "$HUB_DB" | cut -d' ' -f1)" = "$before" ]
}

@test "restore: błędne użycie → exit 2 (#306)" {
  run env PATH="$PATH" "$RESTORE" --nieznana-flaga
  [ "$status" -eq 2 ]
}

@test "restore: hub nie wstaje → exit 6 i rollback do bazy sprzed odtworzenia (#306)" {
  _backup_copy
  _hot_live
  # hub nie odpowiada na API: curl zawsze błąd → pętla startu kończy się exit 6
  stub curl 1

  run env PATH="$PATH" "$RESTORE"
  [ "$status" -eq 6 ]

  # ROLLBACK: baza sprzed odtworzenia (żywa, baseline-*) wróciła — NIE zostaje kopia (a01/u01)
  [ -e "$HUB_DB" ]
  run sqlite3 "$HUB_DB" "SELECT count(*) FROM users WHERE name IN ('a01','u01');"
  [ "$output" = "0" ]
  run sqlite3 "$HUB_DB" "SELECT count(*) FROM users WHERE name LIKE 'baseline-%';"
  [ "$output" -gt 0 ]
}

@test "restore: --no-start nie startuje huba i kończy sukcesem (#306)" {
  _backup_copy
  _hot_live
  stub curl 1 # nawet gdy hub nie odpowiadałby, --no-start nie sprawdza API
  run env PATH="$PATH" "$RESTORE" --no-start
  [ "$status" -eq 0 ]
  run sqlite3 "$HUB_DB" "SELECT count(*) FROM users WHERE name IN ('a01','u01');"
  [ "$output" = "2" ]
}
