# shellcheck shell=bash
# Fragment akceptacji sklejany na hoście przez tests/acceptance.sh (po acceptance-remote.sh).
# Funkcje (expect_ok/expect_fail/skip/as/hub_login/hub_spawn) i zmienne (R1, PW, QUEUE, HUB)
# pochodzą z prefiksu — nie definiuj ich tu.
#
# DR drill (#288): próba odtworzenia bazy huba z kopii po symulowanym uszkodzeniu.
# Waliduje procedurę RB-07b (docs/runbooks/RB-07-odtworzenie-po-awarii.md) krok po kroku:
# świeża kopia -> stop huba -> uszkodzenie jupyterhub.sqlite -> kopia bezpieczeństwa ->
# install z najnowszej kopii (0600 root:root) -> start huba -> logowanie u01/a01 starym hasłem.
# Baza huba to jedyne trwałe źródło kont/haseł na `/workspace`; ten test jest dowodem, że
# runbook działa, a nie tylko że da się go przeczytać.
DR_DB=/workspace/.wlb-hub/jupyterhub.sqlite
DR_BK_DIR=/workspace/.wlb-hub/backup

if ! command -v sqlite3 >/dev/null 2>&1 || [[ ! -f $DR_DB ]] || ! systemctl cat jupyterhub >/dev/null 2>&1; then
  skip "DR drill bazy huba (#288): brak huba/sqlite3/bazy — nie dotyczy tego obrazu"
else
  echo "== Próba odtworzenia po awarii bazy huba (DR drill, RB-07b, #288) =="
  DR_ADMIN_PW=$(cat /root/wlb-hub-admin-initial-password)

  # 0. Kontrola pozytywna: hub i logowanie DZIAŁAJĄ przed symulacją awarii.
  # Bez tego nie odróżnimy „DR nie działa” od „hub był zepsuty już wcześniej”.
  expect_ok "DR: hub odpowiada przed symulacją awarii (#288)" \
    curl -sf -o /dev/null "$HUB/hub/api"
  expect_ok "DR: badacz $R1 loguje się przed symulacją awarii (#288)" \
    test "$(hub_login "$R1" "${PW[$R1]}")" = 302

  # 1. Świeża kopia na żądanie: timer rotuje ~24 h, a test ma odtwarzać AKTUALNY stan
  # (konta i hasła z firstboot), nie przypadkową kopię sprzed godzin.
  expect_ok "DR: kopia bazy huba wykonana na żądanie przed symulacją awarii (#288)" \
    systemctl start wlb-hub-db-backup.service
  dr_latest=$(find "$DR_BK_DIR" -maxdepth 1 -type f -name 'jupyterhub-*.sqlite' | sort | tail -1)
  expect_ok "DR: świeża kopia do odtworzenia istnieje (#288)" test -n "$dr_latest"
  expect_ok "DR: kopia spójna przed symulacją awarii (PRAGMA integrity_check, #288)" \
    bash -c "[[ \$(sqlite3 '$dr_latest' 'PRAGMA integrity_check;') == ok ]]"
  dr_users_before=$(sqlite3 "$dr_latest" 'SELECT count(*) FROM users;')
  expect_ok "DR: kopia zawiera konta (users > 0, #288)" test "${dr_users_before:-0}" -gt 0

  # 2. Symulacja awarii: zatrzymanie huba i celowe uszkodzenie jupyterhub.sqlite.
  # Hub musi być zatrzymany, żeby nie nadpisał uszkodzonej bazy przy zamknięciu.
  expect_ok "DR: hub zatrzymany przed uszkodzeniem bazy (#288)" systemctl stop jupyterhub
  expect_ok "DR: hub nieaktywny po zatrzymaniu (#288)" \
    bash -c '! systemctl is-active --quiet jupyterhub'
  # Stary WAL/SHM nie może zostać doklejony do odtworzonej bazy (runbook RB-07b).
  rm -f "$DR_DB-wal" "$DR_DB-shm"
  # Nadpisujemy nagłówek i pierwszy blok bazy — SQLite nie rozpozna pliku jako bazy.
  printf 'CORRUPTED_WLB_DR_DRILL\n' >"$DR_DB"
  dd if=/dev/urandom of="$DR_DB" bs=512 count=1 conv=notrunc status=none

  expect_fail "DR: uszkodzona baza nie przechodzi integrity_check (#288)" \
    bash -c "[[ \$(sqlite3 '$DR_DB' 'PRAGMA integrity_check;' 2>&1) == ok ]]"
  expect_fail "DR: odczyt kont z uszkodzonej bazy niemożliwy (#288)" \
    bash -c "sqlite3 '$DR_DB' 'SELECT count(*) FROM users;' >/dev/null 2>&1"

  # 3. Procedura odtworzenia ściśle według RB-07b.
  expect_ok "DR: wybór najnowszej kopii do odtworzenia (#288)" test -n "$dr_latest"
  expect_ok "DR: potwierdzenie spójności wybranej kopii (RB-07b, #288)" \
    bash -c "[[ \$(sqlite3 '$dr_latest' 'PRAGMA integrity_check;') == ok ]]"

  dr_pre="$DR_DB.przed-odtworzeniem-$(date -u +%Y%m%dT%H%M%SZ)"
  expect_ok "DR: kopia bezpieczeństwa uszkodzonej bazy przed odtworzeniem (RB-07b, #288)" \
    cp -a "$DR_DB" "$dr_pre"

  expect_ok "DR: odtworzenie bazy z najnowszej kopii (install 0600 root:root, #288)" \
    install -m 0600 -o root -g root "$dr_latest" "$DR_DB"
  expect_ok "DR: odtworzona baza ma uprawnienia 0600 root:root (#288)" \
    bash -c "[[ \$(stat -c %a:%u:%g '$DR_DB') == 600:0:0 ]]"
  expect_ok "DR: odtworzona baza przeszła PRAGMA integrity_check (#288)" \
    bash -c "[[ \$(sqlite3 '$DR_DB' 'PRAGMA integrity_check;') == ok ]]"
  dr_users_after=$(sqlite3 "$DR_DB" 'SELECT count(*) FROM users;')
  expect_ok "DR: liczba kont w bazie zgodna z kopią (#288)" \
    test "$dr_users_after" = "$dr_users_before"
  expect_ok "DR: konto badacza $R1 obecne w odtworzonej bazie (#288)" \
    bash -c "sqlite3 '$DR_DB' 'SELECT name FROM users;' | grep -qx '$R1'"

  # 4. Start huba i weryfikacja logowania STARYM hasłem (dowód, że hasła z kopii działają).
  expect_ok "DR: start huba po odtworzeniu (#288)" systemctl start jupyterhub
  dr_up=0
  for _ in $(seq 1 60); do
    curl -sf -o /dev/null "$HUB/hub/api" && {
      dr_up=1
      break
    }
    sleep 1
  done
  expect_ok "DR: hub działa i odpowiada na API po odtworzeniu (RB-07b, #288)" test "$dr_up" = 1
  expect_ok "DR: badacz $R1 loguje się starym hasłem po odtworzeniu (RB-07b, #288)" \
    test "$(hub_login "$R1" "${PW[$R1]}")" = 302
  expect_ok "DR: serwer notebooków $R1 startuje po odtworzeniu (#288)" \
    hub_spawn "$R1"
  expect_ok "DR: Administrator Klienta a01 loguje się starym hasłem po odtworzeniu (RB-07b, #288)" \
    test "$(hub_login a01 "$DR_ADMIN_PW")" = 302
  expect_ok "DR: timer kopii bazy wlb-hub-db-backup aktywny po procedurze DR (RB-07 §4, #288)" \
    systemctl is-active --quiet wlb-hub-db-backup.timer

  # Porządki: kopia „przed odtworzeniem” to artefakt diagnostyczny, nie kopia rotowana.
  rm -f "$dr_pre"
fi
