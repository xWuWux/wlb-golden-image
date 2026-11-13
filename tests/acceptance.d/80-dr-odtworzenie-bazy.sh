# shellcheck shell=bash
# Fragment akceptacji sklejany na hoście przez tests/acceptance.sh (po acceptance-remote.sh).
# Funkcje (expect_ok/expect_fail/as/hub_login/hub_spawn) i zmienne (R1, PW, QUEUE, HUB)
# pochodzą z prefiksu — nie definiuj ich tu.
#
# Próba odtworzenia po awarii (DR drill) bazy huba z kopii (RB-07b, #288, #8).
# Symuluje uszkodzenie jupyterhub.sqlite, odtwarza z najnowszego backupu wg runbooka
# i weryfikuje start huba oraz logowanie badacza u01 i Administratora Klienta a01.
echo "== Próba odtworzenia po awarii bazy huba (DR drill, RB-07b, #288) =="
DR_DB=/workspace/.wlb-hub/jupyterhub.sqlite
DR_BK_DIR=/workspace/.wlb-hub/backup
DR_ADMIN_PW=$(cat /root/wlb-hub-admin-initial-password)

# 0. Kontrola pozytywna: hub i logowanie DZIAŁAJĄ przed symulacją awarii. Bez tego nie odróżnimy
#    „DR nie działa” od „hub był zepsuty już wcześniej” (diagnostyka awarii vs. stanu wyjściowego).
expect_ok "Hub odpowiada przed symulacją awarii (#288)" \
  curl -sf -o /dev/null "$HUB/hub/api"
expect_ok "Badacz $R1 loguje się przed symulacją awarii (#288)" \
  test "$(hub_login "$R1" "${PW[$R1]}")" = 302

# 1. Przygotowanie: upewnij się, że mamy aktualną i spójną kopię bazy przed symulacją awarii
expect_ok "Kopia bazy huba wykonana na żądanie przed symulacją awarii (#288)" \
  systemctl start wlb-hub-db-backup.service
dr_latest=$(find "$DR_BK_DIR" -maxdepth 1 -type f -name 'jupyterhub-*.sqlite' | sort | tail -1)
expect_ok "Świeża kopia do odtworzenia istnieje (#288)" test -n "$dr_latest"
expect_ok "Kopia bazy spójna przed symulacją awarii (PRAGMA integrity_check, #288)" \
  bash -c "[[ \$(sqlite3 '$dr_latest' 'PRAGMA integrity_check;') == ok ]]"
dr_users_before=$(sqlite3 "$dr_latest" 'SELECT count(*) FROM users;')
expect_ok "Kopia zawiera konta (users > 0, #288)" test "${dr_users_before:-0}" -gt 0

# 2. Symulacja awarii: zatrzymanie huba i celowe uszkodzenie jupyterhub.sqlite
systemctl stop jupyterhub
expect_ok "Hub nieaktywny po zatrzymaniu (#288)" bash -c '! systemctl is-active --quiet jupyterhub'
rm -f "$DR_DB-wal" "$DR_DB-shm"
# Nadpisujemy nagłówek i losowe bloki bazy, niszcząc strukturę SQLite
printf 'CORRUPTED_WLB_DR_DRILL_%s\n' "$(date +%s)" | dd of="$DR_DB" bs=64 count=1 conv=notrunc status=none
dd if=/dev/urandom of="$DR_DB" seek=1 bs=1024 count=4 conv=notrunc status=none

expect_fail "Baza huba uszkodzona przed procedurą DR (integrity_check, #288)" \
  bash -c "[[ \$(sqlite3 '$DR_DB' 'PRAGMA integrity_check;' 2>&1) == ok ]]"
expect_fail "Odczyt tabeli użytkowników z uszkodzonej bazy niemożliwy (#288)" \
  bash -c "sqlite3 '$DR_DB' 'SELECT count(*) FROM users;'"

# 3. Procedura odtworzenia bazy z kopii ściśle według runbooka RB-07b
# Krok 1 z runbooka: Wybierz kopię (najnowsza) i potwierdź jej spójność
dr_chosen=$(find "$DR_BK_DIR" -maxdepth 1 -type f -name 'jupyterhub-*.sqlite' | sort | tail -1)
expect_ok "Wybór najnowszej kopii do odtworzenia (#288)" test -n "$dr_chosen"
expect_ok "Potwierdzenie spójności wybranej kopii (PRAGMA integrity_check, #288)" \
  bash -c "[[ \$(sqlite3 '$dr_chosen' 'PRAGMA integrity_check;') == ok ]]"

# Krok 2 z runbooka: Hub zatrzymany, wykonaj kopię bezpieczeństwa uszkodzonej bazy
dr_pre_ts=$(date -u +%Y%m%dT%H%M%SZ)
cp -a "$DR_DB" "$DR_DB.przed-odtworzeniem-$dr_pre_ts"
expect_ok "Kopia bezpieczeństwa uszkodzonej bazy utworzona (RB-07b, #288)" \
  test -f "$DR_DB.przed-odtworzeniem-$dr_pre_ts"

# Krok 3 z runbooka: Podmień bazę na kopię (prawa 0600 root:root) i wystartuj hub
install -m 0600 -o root -g root "$dr_chosen" "$DR_DB"
expect_ok "Odtworzona baza ma uprawnienia 0600 root:root (#288)" \
  bash -c "[[ \$(stat -c %a:%u:%g '$DR_DB') == '600:0:0' ]]"
expect_ok "Odtworzona baza przeszła PRAGMA integrity_check (#288)" \
  bash -c "[[ \$(sqlite3 '$DR_DB' 'PRAGMA integrity_check;') == ok ]]"
dr_users_after=$(sqlite3 "$DR_DB" 'SELECT count(*) FROM users;')
expect_ok "Liczba kont w bazie zgodna z kopią (#288)" test "$dr_users_after" = "$dr_users_before"
# shellcheck disable=SC2016
expect_ok "Konta u01 i a01 obecne w odtworzonej bazie (#288)" \
  bash -c "sqlite3 '$DR_DB' \"SELECT name FROM users WHERE name IN ('$R1', 'a01');\" | grep -qx '$R1'"

systemctl start jupyterhub

# 4. Weryfikacja działania huba i logowania kont po procedurze odtworzenia
# shellcheck disable=SC2016
expect_ok "Hub działa i odpowiada na API po odtworzeniu (RB-07b, #288)" \
  bash -c 'for _ in $(seq 1 30); do curl -sf -o /dev/null "$HUB/hub/api" && exit 0; sleep 1; done; exit 1'
expect_ok "Badacz u01 loguje się starym hasłem po odtworzeniu (RB-07b, #288)" \
  test "$(hub_login "$R1" "${PW[$R1]}")" = 302
expect_ok "Serwer notebooków badacza u01 startuje po odtworzeniu (#288)" \
  hub_spawn "$R1"
expect_ok "Administrator Klienta a01 loguje się starym hasłem po odtworzeniu (RB-07b, #288)" \
  test "$(hub_login a01 "$DR_ADMIN_PW")" = 302
expect_ok "Timer kopii bazy wlb-hub-db-backup aktywny po procedurze DR (#288)" \
  systemctl is-active --quiet wlb-hub-db-backup.timer

# Porządki po teście DR
rm -f "$DR_DB.przed-odtworzeniem-$dr_pre_ts"
