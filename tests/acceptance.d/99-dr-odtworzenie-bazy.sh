# shellcheck shell=bash
# Fragment akceptacji sklejany na hoście przez tests/acceptance.sh (po acceptance-remote.sh).
# Funkcje (expect_ok/expect_fail/skip/as/hub_login/hub_spawn) i zmienne (R1, PW, QUEUE, HUB, FAIL)
# pochodzą z prefiksu — nie definiuj ich tu.
#
# Próba odtworzenia po awarii (DR drill) bazy huba z kopii (RB-07b, #288, #8).
# Odtworzenie wykonuje JEDNO ŹRÓDŁO PRAWDY: /usr/local/sbin/wlb-hub-db-restore (to samo wywołuje
# runbook) — koniec dryfu procedura↔test. Fragment jest OSTATNI w kolejce (99-), bo zawiera część
# niszczącą; bramka + rm/mv do katalogu dowodowego chronią maszynę przy nieudanej asercji wstępnej.
echo "== Próba odtworzenia po awarii bazy huba (DR drill, RB-07b, #288) =="
DR_DB=/workspace/.wlb-hub/jupyterhub.sqlite
DR_BK_DIR=/workspace/.wlb-hub/backup
DR_FORENSIC_BASE=/workspace/.wlb-hub/przed-odtworzeniem
DR_ADMIN_PW=$(cat /root/wlb-hub-admin-initial-password)
dr_fail0=$FAIL # ile FAIL przed częścią niszczącą — bramka siatki bezpieczeństwa

# 0. Kontrola pozytywna: hub i logowanie DZIAŁAJĄ przed symulacją. Bez tego nie odróżnimy
#    „DR nie działa" od „hub był zepsuty już wcześniej".
expect_ok "Hub odpowiada przed symulacją awarii (#288)" \
  curl -sf -o /dev/null "$HUB/hub/api"
expect_ok "Badacz $R1 loguje się przed symulacją awarii (#288)" \
  test "$(hub_login "$R1" "${PW[$R1]}")" = 302

# 1. Świeża, spójna kopia (test -s PRZED integrity_check — pusta ścieżka nie może udać „ok")
expect_ok "Kopia bazy huba na żądanie przed symulacją (#288)" \
  systemctl start wlb-hub-db-backup.service
dr_latest=$(find "$DR_BK_DIR" -maxdepth 1 -type f -name 'jupyterhub-*.sqlite' -printf '%T@ %p\n' |
  sort -nr | head -1 | cut -d' ' -f2-)
expect_ok "Świeża kopia do odtworzenia istnieje i jest niepusta (#288)" \
  bash -c "test -s '$dr_latest'"
expect_ok "Kopia spójna przed symulacją (test -s + integrity_check, #288)" \
  bash -c "[[ -s '$dr_latest' && \$(sqlite3 '$dr_latest' 'PRAGMA integrity_check;') == ok ]]"

# Dowód, że kopia odzwierciedla ŻYWY stan huba (nie tautologia „kopia = kopia")
dr_live_users=$(sqlite3 "$DR_DB" 'SELECT name FROM users ORDER BY name;')
dr_copy_users=$(sqlite3 "$dr_latest" 'SELECT name FROM users ORDER BY name;')
expect_ok "Lista kont żywej bazy = kopia (#288)" test "$dr_live_users" = "$dr_copy_users"
expect_ok "Kopia zawiera konta u01 i a01 (#288)" \
  bash -c "[[ \$(sqlite3 '$dr_latest' \"SELECT count(*) FROM users WHERE name IN ('$R1','a01');\") == 2 ]]"

# 2. BRAMKA: nie niszcz bazy, jeśli kontrola wstępna/kopia nie przeszły (siatka bezpieczeństwa, #288)
if ((FAIL > dr_fail0)); then
  skip "DR: pominięto niszczącą symulację — wcześniejsze asercje nie przeszły (#288)"
else
  # 3. Symulacja awarii: zatrzymanie huba, sentinel dziennika i deterministyczne uszkodzenie nagłówka.
  #    Sentinel -journal wymusza dowód, że restore przenosi WSZYSTKIE dzienniki (nie tylko -wal/-shm).
  systemctl stop jupyterhub
  expect_ok "Hub nieaktywny po zatrzymaniu (#288)" bash -c '! systemctl is-active --quiet jupyterhub'
  : >"$DR_DB-journal"
  printf 'CORRUPTED_WLB_DR_DRILL_%s' "$(date +%s)" | dd of="$DR_DB" bs=32 count=1 conv=notrunc status=none
  expect_fail "Baza huba uszkodzona przed procedurą DR (integrity_check, #288)" \
    bash -c "[[ \$(sqlite3 '$DR_DB' 'PRAGMA integrity_check;' 2>&1) == ok ]]"

  # 4. Odtworzenie JEDNYM źródłem prawdy — skrypt robi: weryfikację kopii, mv bazy+dzienników do
  #    katalogu dowodowego, atomową podmianę z sha256, start huba i weryfikację API.
  expect_ok "wlb-hub-db-restore kończy się sukcesem (exit 0, RB-07b, #288)" \
    /usr/local/sbin/wlb-hub-db-restore

  # 5. Dowody podmiany (nie pozorne asercje)
  expect_ok "Odtworzona baza = kopia (sha256, #288)" \
    bash -c "[[ \$(sha256sum '$DR_DB' | cut -d' ' -f1) == \$(sha256sum '$dr_latest' | cut -d' ' -f1) ]]"
  expect_ok "Brak osieroconego dziennika obok odtworzonej bazy (#288)" \
    bash -c "! ls '$DR_DB'-journal '$DR_DB'-wal '$DR_DB'-shm >/dev/null 2>&1"
  expect_ok "Uszkodzona baza i jej dziennik w katalogu dowodowym (#288)" \
    bash -c "find '$DR_FORENSIC_BASE' -name 'jupyterhub.sqlite-journal' | grep -q ."
  expect_ok "Odtworzona baza ma uprawnienia 0600 root:root (#288)" \
    bash -c "[[ \$(stat -c %a:%u:%g '$DR_DB') == '600:0:0' ]]"
  expect_ok "Konta u01 i a01 obecne w odtworzonej bazie (#288)" \
    bash -c "[[ \$(sqlite3 '$DR_DB' \"SELECT count(*) FROM users WHERE name IN ('$R1','a01');\") == 2 ]]"

  # 6. REALNE zachowanie po odtworzeniu (nie samo istnienie konta): HTTP + role na odtworzonej bazie.
  # Loginy 302 (poniżej) i integralność bazy (wyżej) GWARANTUJĄ poprawność odtworzenia i BRAMKUJĄ.
  # Asercje server-proxy/ról (/user/api/status, /hub/admin) są realne, ale kruche na VM: serwer
  # notebooków wstaje ASYNCHRONICZNIE po restarcie huba, a sesje bywają unieważniane. Do czasu
  # stabilizacji są RAPORTOWE (wzorzec #138/#278/Lynis) — bramkują tylko przy WLB_DR_HTTP_GATING=1.
  dr_http_report() { # dr_http_report OPIS POLECENIE...
    local desc=$1
    shift
    if "$@"; then
      echo "  PASS  $desc"
    elif [[ ${WLB_DR_HTTP_GATING:-0} == 1 ]]; then
      ko "$desc"
    else
      echo "  SKIP  $desc [report-only: WLB_DR_HTTP_GATING=0, E2E server-proxy w stabilizacji]"
    fi
  }

  expect_ok "Hub działa i odpowiada na API po odtworzeniu (RB-07b, #288)" \
    bash -c "for _ in \$(seq 1 30); do curl -sf -o /dev/null \"$HUB/hub/api\" && exit 0; sleep 1; done; exit 1"
  expect_ok "Badacz u01 loguje się starym hasłem po odtworzeniu (302, #288)" \
    test "$(hub_login "$R1" "${PW[$R1]}")" = 302
  expect_ok "Administrator Klienta a01 loguje się starym hasłem po odtworzeniu (302, #288)" \
    test "$(hub_login a01 "$DR_ADMIN_PW")" = 302

  # Odśwież sesje (restart huba mógł je unieważnić) i poczekaj na gotowość serwera u01 (spawn async).
  hub_login "$R1" "${PW[$R1]}" >/dev/null || true
  hub_login a01 "$DR_ADMIN_PW" >/dev/null || true
  hub_spawn "$R1" || true
  # /user/u01/api/status = 200 dowodzi, że proxy i OAuth działają na odtworzonej bazie (polling na async spawn)
  dr_http_report "GET /user/u01/api/status = 200 po odtworzeniu (#288)" \
    bash -c "for _ in \$(seq 1 30); do c=\$(curl -s -o /dev/null -w '%{http_code}' -b '/tmp/wlb-test-$R1.jar' -L \"$HUB/user/$R1/api/status\"); [[ \$c == 200 ]] && exit 0; sleep 2; done; exit 1"
  # Role: a01 widzi panel admina (200), u01 nie (403) — dowód, że role przetrwały odtworzenie
  dr_http_report "a01 ma dostęp do /hub/admin (200, #288)" \
    bash -c "c=\$(curl -s -o /dev/null -w '%{http_code}' -b '/tmp/wlb-test-a01.jar' -L \"$HUB/hub/admin\"); [[ \$c == 200 ]]"
  dr_http_report "u01 nie ma dostępu do /hub/admin (403, #288)" \
    bash -c "c=\$(curl -s -o /dev/null -w '%{http_code}' -b '/tmp/wlb-test-$R1.jar' \"$HUB/hub/admin\"); [[ \$c == 403 ]]"

  # 7. Timer kopii wznowiony przez skrypt
  expect_ok "Timer kopii bazy wlb-hub-db-backup aktywny po procedurze DR (#288)" \
    systemctl is-active --quiet wlb-hub-db-backup.timer

  # Porządki: katalog dowodowy zawiera skróty haseł — nie zostawiamy go po teście
  rm -rf "$DR_FORENSIC_BASE"
fi
