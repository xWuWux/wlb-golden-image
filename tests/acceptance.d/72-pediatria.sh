# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-pediatria sprawdza stos danych (PostgreSQL 16 + DBeaver, #271);
# na innych flavorach pomija.
if grep -qx "WLB_IMAGE_NAME=wlb-pediatria" /etc/wlb/image-release 2>/dev/null; then
  echo "== Stos bazy danych i DBeaver (PostgreSQL 16 + DBeaver CE, #271) =="

  # --- Usługa systemowa PostgreSQL --------------------------------------------------------
  expect_ok "Usługa PostgreSQL 16 aktywna (postgresql@16-main)" \
    systemctl is-active --quiet postgresql@16-main

  # --- Ograniczenie sieciowe: nasłuch WYŁĄCZNIE na 127.0.0.1:5432 -------------------------
  expect_ok "PostgreSQL nasłuchuje na 127.0.0.1:5432" \
    bash -c 'ss -ltn | grep -q "127\.0\.0\.1:5432"'

  expect_fail "PostgreSQL NIE nasłuchuje na 0.0.0.0 (wszystkie IPv4)" \
    bash -c 'ss -ltn | grep -q "0\.0\.0\.0:5432"'

  expect_fail "PostgreSQL NIE nasłuchuje na IPv6 (:::5432)" \
    bash -c 'ss -ltn | grep -q ":::5432"'

  # --- Trwałość klastra na /workspace -----------------------------------------------------
  expect_ok "Klaster PostgreSQL zainicjalizowany na /workspace/pgdata" \
    test -f /workspace/pgdata/PG_VERSION

  # --- Dostęp i uwierzytelnianie PostgreSQL: peer i scram-sha-256 -------------------------
  # Badacz u01 (jupyter-u01) ma dostęp do swojej bazy db_u01 jako rola u01
  expect_ok "Badacz $R1 może połączyć się z własną bazą db_$R1 (peer ident)" \
    as "$R1" psql -d "db_$R1" -U "$R1" -c "SELECT 1"

  # Badacz u02 (jupyter-u02) NIE ma dostępu do bazy db_u01 (izolacja per-uNN)
  expect_fail "Badacz $R2 NIE ma dostępu do bazy badacza $R1 (db_$R1)" \
    as "$R2" psql -d "db_$R1" -U "$R2" -c "SELECT 1"

  # Badacz u01 nie może połączyć się jako obca rola u02 przez peer (pg_ident mapa)
  expect_fail "Badacz $R1 nie może podszyć się pod rolę $R2 (pg_ident odmowa)" \
    as "$R1" psql -d "db_$R2" -U "$R2" -c "SELECT 1"

  # --- Plik .pgpass dla badacza ($R1 = u01) -----------------------------------------------
  PGPASS_R1="/workspace/jupyter-$R1/.pgpass"
  expect_ok "Plik .pgpass badacza $R1 istnieje" \
    test -f "$PGPASS_R1"

  # shellcheck disable=SC2016
  expect_ok "Plik .pgpass badacza $R1 ma uprawnienia 0600" \
    bash -c '[ "$(stat -c %a "'"$PGPASS_R1"'")" = "600" ]'

  # shellcheck disable=SC2016
  expect_ok "Właścicielem .pgpass badacza $R1 jest jupyter-$R1" \
    bash -c '[ "$(stat -c %U:%G "'"$PGPASS_R1"'")" = "jupyter-'"$R1"':jupyter-'"$R1"'" ]'

  expect_ok "Format .pgpass zawiera 127.0.0.1:5432:db_$R1:$R1:<haslo>" \
    grep -qE "^127\.0\.0\.1:5432:db_${R1}:${R1}:[A-Za-z0-9]{32}$" "$PGPASS_R1"

  # --- Sterownik pgJDBC i konfiguracja offline -------------------------------------------
  JDBC_JAR="/opt/wlb/drivers/postgres/postgresql-42.7.14.jar"
  expect_ok "Sterownik pgJDBC 42.7.14 obecny w /opt/wlb/drivers/postgres/" \
    test -f "$JDBC_JAR"

  expect_ok "Plik konfiguracji sterowników DBeaver wlb-drivers.xml istnieje" \
    test -f /usr/share/dbeaver-ce/wlb-drivers.xml

  expect_ok "wlb-drivers.xml wskazuje na offline pgJDBC jar" \
    grep -q "$JDBC_JAR" /usr/share/dbeaver-ce/wlb-drivers.xml

  # --- Konfiguracja /usr/share/dbeaver-ce/dbeaver.ini (air-gap, pamięć) -------------------
  expect_ok "dbeaver.ini ogranicza pamięć do -Xmx512m (#271)" \
    grep -Fxq -- "-Xmx512m" /usr/share/dbeaver-ce/dbeaver.ini

  expect_ok "dbeaver.ini wskazuje plik sterowników offline" \
    grep -Fxq -- "-Ddbeaver.drivers.configuration-file=/usr/share/dbeaver-ce/wlb-drivers.xml" /usr/share/dbeaver-ce/dbeaver.ini

  expect_ok "dbeaver.ini wyłącza aktualizacje (policy.software.update.disabled)" \
    grep -Fxq -- "-Dpolicy.software.update.disabled=true" /usr/share/dbeaver-ce/dbeaver.ini

  expect_ok "dbeaver.ini wyłącza instalację wtyczek (policy.software.install.disabled)" \
    grep -Fxq -- "-Dpolicy.software.install.disabled=true" /usr/share/dbeaver-ce/dbeaver.ini

  expect_ok "dbeaver.ini wyłącza asystenta AI (ai.disabled)" \
    grep -Fxq -- "-Dai.disabled=true" /usr/share/dbeaver-ce/dbeaver.ini

  # --- Szablon profilu DBeaver i wrapper /usr/local/bin/dbeaver --------------------------
  expect_ok "Szablon data-sources.template.json obecny" \
    test -f /etc/wlb/dbeaver/data-sources.template.json

  expect_ok "Wrapper /usr/local/bin/dbeaver wykonywalny" \
    test -x /usr/local/bin/dbeaver

  # Test wrappera: uruchomienie jako badacz $R1 (w trybie SKIP_EXEC) generuje data-sources.json
  # shellcheck disable=SC2016
  expect_ok "Wrapper dbeaver instancjonuje data-sources.json dla badacza $R1" \
    bash -c '
      as "'"$R1"'" env WLB_DBEAVER_SKIP_EXEC=1 /usr/local/bin/dbeaver
      f="/workspace/jupyter-'"$R1"'/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
      test -f "$f" && [ "$(stat -c %a "$f")" = "600" ]
    '

  # shellcheck disable=SC2016
  expect_ok "data-sources.json wskazuje poprawną bazę db_$R1 i rolę $R1 bez zapisanego hasła" \
    bash -c '
      f="/workspace/jupyter-'"$R1"'/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
      grep -q "\"database\": \"db_'"$R1"'\"" "$f" &&
      grep -q "\"user\": \"'"$R1"'\"" "$f" &&
      (! grep -iq "password" "$f" || grep -q "\"save-password\": false" "$f")
    '

  # --- Kafelek pulpitu XFCE ---------------------------------------------------------------
  expect_ok "Kafelek DBeaver obecny w /usr/share/applications/wlb-dbeaver.desktop" \
    test -f /usr/share/applications/wlb-dbeaver.desktop

  expect_ok "Kafelek DBeaver wskazuje absolutną ścieżkę do wrappera (Exec)" \
    grep -Eq '^Exec=/usr/local/bin/dbeaver' /usr/share/applications/wlb-dbeaver.desktop

  if command -v desktop-file-validate >/dev/null 2>&1; then
    expect_ok "Kafelek wlb-dbeaver.desktop przechodzi desktop-file-validate" \
      desktop-file-validate /usr/share/applications/wlb-dbeaver.desktop
  fi
fi
