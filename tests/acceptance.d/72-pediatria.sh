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
  expect_ok "data-sources.json wskazuje db_$R1, u01 i zawiera hasło z .pgpass (save-password: true)" \
    bash -c '
      f="/workspace/jupyter-'"$R1"'/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
      p="/workspace/jupyter-'"$R1"'/.pgpass"
      pw_pgpass=$(awk -F: "{print \$5}" "$p")
      pw_dbeaver=$(grep -oE "\"userPassword\": \"[^\"]+\"" "$f" | cut -d\" -f4)
      [ -n "$pw_pgpass" ] && [ "$pw_pgpass" = "$pw_dbeaver" ] &&
      grep -q "\"database\": \"db_'"$R1"'\"" "$f" &&
      grep -q "\"user\": \"'"$R1"'\"" "$f" &&
      grep -q "\"save-password\": true" "$f"
    '

  # --- Weryfikacja połączenia end-to-end sterownikiem pgJDBC (#271) -----------------------
  # Program pomocniczy WlbJdbcPing (tests/lib/WlbJdbcPing.java) zrzucany do katalogu tymczasowego.
  # Uruchamiany pod JRE zbundlowanym z DBeaver CE z użyciem oficjalnego pgJDBC jar.
  W72_TMP=$(mktemp -d)
  # shellcheck disable=SC2064
  trap "rm -rf '$W72_TMP'" EXIT
  base64 -d <<'EOF' >"$W72_TMP/WlbJdbcPing.class"
yv66vgAAADQAZgoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClWCQAIAAkHAAoMAAsADAEAEGphdmEvbGFuZy9TeXN0ZW0BAANlcnIBABVMamF2YS9pby9QcmludFN0cmVhbTsIAA4BACpVc2FnZTogV2xiSmRiY1BpbmcgPHVybD4gPHVzZXI+IFtwYXNzd29yZF0KABAAEQcAEgwAEwAUAQATamF2YS9pby9QcmludFN0cmVhbQEAB3ByaW50bG4BABUoTGphdmEvbGFuZy9TdHJpbmc7KVYKAAgAFgwAFwAYAQAEZXhpdAEABChJKVYKABoAGwcAHAwAHQAeAQAQamF2YS9sYW5nL1N0cmluZwEAB2lzRW1wdHkBAAMoKVoIACABABVvcmcucG9zdGdyZXNxbC5Ecml2ZXIKACIAIwcAJAwAJQAmAQAPamF2YS9sYW5nL0NsYXNzAQAHZm9yTmFtZQEAJShMamF2YS9sYW5nL1N0cmluZzspTGphdmEvbGFuZy9DbGFzczsKACgAKQcAKgwAKwAsAQAWamF2YS9zcWwvRHJpdmVyTWFuYWdlcgEADWdldENvbm5lY3Rpb24BAE0oTGphdmEvbGFuZy9TdHJpbmc7TGphdmEvbGFuZy9TdHJpbmc7TGphdmEvbGFuZy9TdHJpbmc7KUxqYXZhL3NxbC9Db25uZWN0aW9uOwsALgAvBwAwDAAxADIBABNqYXZhL3NxbC9Db25uZWN0aW9uAQAPY3JlYXRlU3RhdGVtZW50AQAWKClMamF2YS9zcWwvU3RhdGVtZW50OwgANAEACFNFTEVDVCAxCwA2ADcHADgMADkAOgEAEmphdmEvc3FsL1N0YXRlbWVudAEADGV4ZWN1dGVRdWVyeQEAKChMamF2YS9sYW5nL1N0cmluZzspTGphdmEvbGFuZy9TdHJpbmc7KUxqYXZhL3NxbC9SZXN1bHRTZXQ7CwA8AD0HADwMAP8AHgEAEmphdmEvc3FsL1Jlc3VsdFNldAEABG5leHQACAA8QQEAEmphdmEvc3FsL1Jlc3VsdFNldAQABmdldEludAEABChJKUkJAAgARQwARgAMAEAA291dAgASAEAC1dMQl9KREJDX09LCABKAQAXVW5leHBlY3RlZCBxdWVyeSByZXN1bHQLADwATAwATQAGAQAFY2xvc2UHAE8BABNqYXZhL2xhbmcvVGhyb3dhYmxlCgBOAFEMAFIAUwEADWFkZFN1cHByZXNzZWQBABgoTGphdmEvbGFuZy9UaHJvd2FibGU7KVYLADYATAsALgBMBwBXAQATamF2YS9sYW5nL0V4Y2VwdGlvbgoAVgBZDABaAAYBAA9wcmludFN0YWNrVHJhY2UHAFwBAAtXbGJKZGJjUGluZwEABENvZGUBAA9MaW5lTnVtYmVyVGFibGUBAARtYWluAQAWKFtMamF2YS9sYW5nL1N0cmluZzspVgEADVN0YWNrTWFwVGFibGUHAGMBABNbTGphdmEvbGFuZy9TdHJpbmc7AQAKU291cmNlRmlsZQEAEFdsYkpkYmNQaW5nLmphdmEAIQBbAAIAAAAAAAIAAQAFAAYAAQBdAAAAHQABAAEAAAAFKrcAAbEAAAABAF4AAAAGAAEAAAAGAAkAXwBgAAEAXQAAAocAAwAJAAABJCq+BaIAD7IABxINtgAPBbgAFSoDMkwqBDJNKr4GoQASKgUytgAZmgAJKgUypwAEAU4SH7gAIVctxgAMKywtuAAnpwAJKywBuAAnOgQZBLkALQEAOgUZBRIzuQA1AgA6BhkGuQA7AQCZAB4ZBgS5AEACAASgABKyAEQSR7YADwO4ABWnAA+yAAcSSbYADwS4ABUZBsYAKhkGuQBLAQCnACA6BxkGxgAWGQa5AEsBAKcADDoIGQcZCLYAUBkHvxkFxgAqGQW5AFQBAKcAIDoGGQXGABYZBbkAVAEApwAMOgcZBhkHtgBQGQa/GQTGACoZBLkAVQEApwAgOgUZBMYAFhkEuQBVAQCnAAw6BhkFGQa2AFAZBb+nAA46BBkEtgBYBLgAFbEABwBgAJEAoABOAKcArgCxAE4AVQC9AMwATgDTANoA3QBOAEwA6QD4AE4A/wEGAQkATgAxARUBGABWAAIAXgAAAHIAHAAAAAgABgAJAA4ACgASAAwAFgANABoADgAxABAANwARADsAEgBEABMATAAUAFUAFQBgABYAdgAXAH4AGACFABoAjQAbAJEAHQCgABEAvQAdAMwAEQDpAB0A+AARARUAIQEYAB4BGgAfAR8AIAEjACIAYQAAAKEAFRL9ABwHABoHABpABwAa/AATBwAaRQcALv4AOgcALgcANgcAPAtOBwBO/wAQAAgHAGIHABoHABoHABoHAC4HADYHADwHAE4AAQcATgj5AAJOBwBO/wAQAAcHAGIHABoHABoHABoHAC4HADYHAE4AAQcATgj5AAJOBwBO/wAQAAYHAGIHABoHABoHABoHAC4HAE4AAQcATgj5AAJCBwBWCgABAGQAAAACAGU=
EOF
  chmod 755 "$W72_TMP"
  chmod 644 "$W72_TMP/WlbJdbcPing.class"

  # Test 1: Połączenie TCP z jawnym hasłem z profilu DBeaver
  # shellcheck disable=SC2016
  expect_ok "Sterownik pgJDBC łączy się do db_$R1 przez TCP/SCRAM z hasłem z profilu DBeaver" \
    bash -c '
      f="/workspace/jupyter-'"$R1"'/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
      pw=$(grep -oE "\"userPassword\": \"[^\"]+\"" "$f" | cut -d\" -f4)
      [ -n "$pw" ] &&
      as "'"$R1"'" /usr/share/dbeaver-ce/jre/bin/java \
        -cp "'"$W72_TMP"':/opt/wlb/drivers/postgres/postgresql-42.7.14.jar" \
        WlbJdbcPing "jdbc:postgresql://127.0.0.1:5432/db_'"$R1"'" "'"$R1"'" "$pw" | grep -q "WLB_JDBC_OK"
    '

  # Test 2: Połączenie TCP z automatycznym odczytem ~/.pgpass przez pgJDBC (bez podawania hasła)
  # shellcheck disable=SC2016
  expect_ok "Sterownik pgJDBC łączy się do db_$R1 natywnie z użyciem pliku ~/.pgpass" \
    bash -c '
      as "'"$R1"'" /usr/share/dbeaver-ce/jre/bin/java \
        -cp "'"$W72_TMP"':/opt/wlb/drivers/postgres/postgresql-42.7.14.jar" \
        WlbJdbcPing "jdbc:postgresql://127.0.0.1:5432/db_'"$R1"'" "'"$R1"'" | grep -q "WLB_JDBC_OK"
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
