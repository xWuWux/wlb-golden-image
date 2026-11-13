#!/usr/bin/env bats
# Testy jednostkowe spójnej kopii bazy huba (#8) w piaskownicy.

load helpers

setup() {
  setup_sandbox
  command -v sqlite3 >/dev/null || skip "sqlite3 niedostępne"
  BACKUP="$REPO_ROOT/ansible/roles/tljh/files/wlb-hub-db-backup"
  export HUB_DB="$SANDBOX/workspace/.wlb-hub/jupyterhub.sqlite"
  export BACKUP_DIR="$SANDBOX/workspace/.wlb-hub/backup"
  mkdir -p "$(dirname "$HUB_DB")"
}

make_db() { # make_db PLIK [liczba_kont] — minimalna baza w stylu huba (tabela users)
  local db=$1 n=${2:-3} i
  sqlite3 "$db" "CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT);"
  for ((i = 1; i <= n; i++)); do sqlite3 "$db" "INSERT INTO users(name) VALUES('u$i');"; done
}
copies() { find "$BACKUP_DIR" -maxdepth 1 -type f -name 'jupyterhub-*.sqlite' | sort; }

@test "robi spójną kopię działającej bazy, z prawami tylko dla roota" {
  make_db "$HUB_DB" 3
  run "$BACKUP"
  [ "$status" -eq 0 ]
  mapfile -t c < <(copies)
  [ "${#c[@]}" -eq 1 ]
  [ "$(sqlite3 "${c[0]}" 'PRAGMA integrity_check;')" = ok ]
  [ "$(sqlite3 "${c[0]}" 'SELECT count(*) FROM users;')" -eq 3 ]
  [ "$(stat -c %a "${c[0]}")" = 600 ]
  [ "$(stat -c %a "$BACKUP_DIR")" = 700 ]
  [[ $output == *"kopii w rotacji: 1/24"* ]]
}

@test "nie zostaje plik częściowy (.part)" {
  make_db "$HUB_DB" 1
  run "$BACKUP"
  [ "$status" -eq 0 ]
  refute compgen -G "$BACKUP_DIR/*.part"
}

@test "rotacja zostawia KEEP najnowszych kopii" {
  make_db "$HUB_DB" 1
  mkdir -p "$BACKUP_DIR"
  # cztery starsze kopie (nazwy z czasem sortują się chronologicznie)
  for ts in 20260101T000000Z 20260102T000000Z 20260103T000000Z 20260104T000000Z; do
    : >"$BACKUP_DIR/jupyterhub-$ts.sqlite"
  done
  KEEP=3 run "$BACKUP"
  [ "$status" -eq 0 ]
  mapfile -t c < <(copies)
  [ "${#c[@]}" -eq 3 ]
  # najstarsze dwie (0101, 0102) usunięte; 0103 i 0104 zostają obok nowej
  refute test -e "$BACKUP_DIR/jupyterhub-20260101T000000Z.sqlite"
  refute test -e "$BACKUP_DIR/jupyterhub-20260102T000000Z.sqlite"
  [ -e "$BACKUP_DIR/jupyterhub-20260104T000000Z.sqlite" ]
}

@test "brak bazy huba — pomija bez błędu (przed pierwszym logowaniem)" {
  run "$BACKUP"
  [ "$status" -eq 0 ]
  [[ $output == *"jeszcze nie istnieje"* ]]
  refute compgen -G "$BACKUP_DIR/jupyterhub-*.sqlite"
}

@test "uszkodzona baza źródłowa nie psuje istniejących kopii (fail-secure)" {
  make_db "$HUB_DB" 1
  "$BACKUP" # pierwsza dobra kopia
  dobra=$(copies)
  printf 'to nie jest baza danych' >"$HUB_DB" # uszkodzenie źródła
  run "$BACKUP"
  [ "$status" -ne 0 ]
  [ -e "$dobra" ]                        # dobra kopia nietknięta
  refute compgen -G "$BACKUP_DIR/*.part" # bez pliku częściowego
}

@test "nieprawidłowe KEEP przerywa" {
  make_db "$HUB_DB" 1
  KEEP=dużo run "$BACKUP"
  [ "$status" -ne 0 ]
  [[ $output == *"KEEP musi być liczbą"* ]]
}

@test "odtworzenie bazy z najnowszej kopii przywraca spójność po uszkodzeniu (DR drill, RB-07b, #288)" {
  make_db "$HUB_DB" 3
  "$BACKUP" # spójna kopia bazy
  mapfile -t c < <(copies)
  [ "${#c[@]}" -eq 1 ]
  latest="${c[0]}"

  # Symulacja uszkodzenia bazy
  printf 'USZKODZENIE_BAZY_WLB_DISASTER' >"$HUB_DB"
  run sqlite3 "$HUB_DB" 'PRAGMA integrity_check;'
  [ "$status" -ne 0 ] || [ "$output" != "ok" ]

  # Procedura z runbooka RB-07b:
  # 1. Sprawdź spójność wybranej kopii
  [ "$(sqlite3 "$latest" 'PRAGMA integrity_check;')" = ok ]

  # 2. Kopia bezpieczeństwa uszkodzonej bazy przed odtworzeniem
  pre_restore="$HUB_DB.przed-odtworzeniem-$(date -u +%Y%m%dT%H%M%SZ)"
  cp -a "$HUB_DB" "$pre_restore"
  [ -f "$pre_restore" ]

  # 3. Podmień bazę na kopię z uprawnieniami 0600
  install -m 0600 "$latest" "$HUB_DB"

  # 4. Weryfikacja spójności, uprawnień i danych
  [ "$(sqlite3 "$HUB_DB" 'PRAGMA integrity_check;')" = ok ]
  [ "$(sqlite3 "$HUB_DB" 'SELECT count(*) FROM users;')" -eq 3 ]
  [ "$(stat -c %a "$HUB_DB")" = 600 ]
}
