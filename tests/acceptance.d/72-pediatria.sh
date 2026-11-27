# shellcheck shell=bash
# Adaptacyjna: tylko na flavorze wlb-pediatria sprawdza stos danych (PostgreSQL 16 + DBeaver, #271);
# na innych flavorach pomija.
if grep -qx "WLB_IMAGE_NAME=wlb-pediatria" /etc/wlb/image-release 2>/dev/null; then
  echo "== Stos bazy danych i DBeaver (PostgreSQL 16 + DBeaver CE, #271) =="

  # KLUCZOWE (#369): część testów poniżej uruchamia polecenia badacza przez `as` wewnątrz `bash -c '...'`
  # (expect_ok tego wymaga, bo łączy kilka kroków). `as` to FUNKCJA powłoki z remote-common.sh, a świeży
  # `bash -c` jej NIE dziedziczy → „as: command not found" → wrapper/JDBC nigdy nie startował i 4 testy
  # DBeaver/pgJDBC padały (a negatywny przechodził z błędnego powodu). Eksport funkcji udostępnia ją
  # podpowłokom `bash -c`. (Diagnostyka #369 potwierdziła: provisioning, .pgpass i TCP/SCRAM działają —
  # to był wyłącznie problem widoczności `as` w podpowłoce, nie produktu.)
  export -f as

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

  # --- Provisioning kont badaczy: event-driven po pierwszym spawnie (#271/#369 wariant B) -------
  # Konto SYSTEMOWE jupyter-uNN i jego stan PostgreSQL (rola, baza, .pgpass) NIE istnieją od boota —
  # powstają po PIERWSZYM spawnie serwera badacza: TLJH tworzy /workspace/jupyter-uNN, a path-unit
  # wlb-postgres-provision.path wyzwala wtedy (idempotentny) wlb-postgres-provision. Rdzeń akceptacji
  # (acceptance-remote.sh) już spawnuje u01 i u02, więc tu tylko CZEKAMY, aż zdarzeniowy (asynchroniczny)
  # provisioning utworzy .pgpass obu kont — bez tego poniższe asercje bazy łapałyby wyścig.
  provisioned=0
  for _ in $(seq 1 30); do
    if [[ -f /workspace/jupyter-$R1/.pgpass && -f /workspace/jupyter-$R2/.pgpass ]]; then
      provisioned=1
      break
    fi
    sleep 2
  done
  expect_ok "Provisioning PostgreSQL wyzwolony zdarzeniowo po spawnie kont u01/u02 (path-unit, #369 B)" \
    test "$provisioned" -eq 1

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
  # Jeśli w środowisku obecny jest kompilator javac (np. pełny JDK), klasa jest kompilowana ze źródła.
  # W minimalnym środowisku JRE (zbundlowanym z DBeaverem) odtwarzany jest zaaudytowany bytecode
  # weryfikowany kontraktem tests/unit/test_jdbc_ping_contract.py.
  W72_TMP=$(mktemp -d)
  # shellcheck disable=SC2064
  trap "rm -rf '$W72_TMP'" EXIT

  cat <<'EOF' >"$W72_TMP/WlbJdbcPing.java"
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

public class WlbJdbcPing {
    public static void main(String[] args) {
        if (args.length < 2) {
            System.err.println("Usage: WlbJdbcPing <url> <user> [password]");
            System.exit(2);
        }
        String url = args[0];
        String user = args[1];
        String password = (args.length >= 3 && !args[2].isEmpty()) ? args[2] : null;
        try {
            Class.forName("org.postgresql.Driver");
            try (Connection conn = (password != null)
                    ? DriverManager.getConnection(url, user, password)
                    : DriverManager.getConnection(url, user, null);
                 Statement stmt = conn.createStatement();
                 ResultSet rs = stmt.executeQuery("SELECT 1")) {
                if (rs.next() && rs.getInt(1) == 1) {
                    System.out.println("WLB_JDBC_OK");
                    System.exit(0);
                } else {
                    System.err.println("Unexpected query result");
                    System.exit(1);
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }
    }
}
EOF

  if command -v javac >/dev/null 2>&1; then
    javac -source 8 -target 8 "$W72_TMP/WlbJdbcPing.java"
  else
    base64 -d <<'EOF' >"$W72_TMP/WlbJdbcPing.class"
yv66vgAAADQAZgoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClW
CQAIAAkHAAoMAAsADAEAEGphdmEvbGFuZy9TeXN0ZW0BAANlcnIBABVMamF2YS9pby9QcmludFN0
cmVhbTsIAA4BACpVc2FnZTogV2xiSmRiY1BpbmcgPHVybD4gPHVzZXI+IFtwYXNzd29yZF0KABAA
EQcAEgwAEwAUAQATamF2YS9pby9QcmludFN0cmVhbQEAB3ByaW50bG4BABUoTGphdmEvbGFuZy9T
dHJpbmc7KVYKAAgAFgwAFwAYAQAEZXhpdAEABChJKVYKABoAGwcAHAwAHQAeAQAQamF2YS9sYW5n
L1N0cmluZwEAB2lzRW1wdHkBAAMoKVoIACABABVvcmcucG9zdGdyZXNxbC5Ecml2ZXIKACIAIwcA
JAwAJQAmAQAPamF2YS9sYW5nL0NsYXNzAQAHZm9yTmFtZQEAJShMamF2YS9sYW5nL1N0cmluZzsp
TGphdmEvbGFuZy9DbGFzczsKACgAKQcAKgwAKwAsAQAWamF2YS9zcWwvRHJpdmVyTWFuYWdlcgEA
DWdldENvbm5lY3Rpb24BAE0oTGphdmEvbGFuZy9TdHJpbmc7TGphdmEvbGFuZy9TdHJpbmc7TGph
dmEvbGFuZy9TdHJpbmc7KUxqYXZhL3NxbC9Db25uZWN0aW9uOwsALgAvBwAwDAAxADIBABNqYXZh
L3NxbC9Db25uZWN0aW9uAQAPY3JlYXRlU3RhdGVtZW50AQAWKClMamF2YS9zcWwvU3RhdGVtZW50
OwgANAEACFNFTEVDVCAxCwA2ADcHADgMADkAOgEAEmphdmEvc3FsL1N0YXRlbWVudAEADGV4ZWN1
dGVRdWVyeQEAKChMamF2YS9sYW5nL1N0cmluZzspTGphdmEvc3FsL1Jlc3VsdFNldDsLADwAPQcA
PgwAPwAeAQASamF2YS9zcWwvUmVzdWx0U2V0AQAEbmV4dAsAPABBDABCAEMBAAZnZXRJbnQBAAQo
SSlJCQAIAEUMAEYADAEAA291dAgASAEAC1dMQl9KREJDX09LCABKAQAXVW5leHBlY3RlZCBxdWVy
eSByZXN1bHQLADwATAwATQAGAQAFY2xvc2UHAE8BABNqYXZhL2xhbmcvVGhyb3dhYmxlCgBOAFEM
AFIAUwEADWFkZFN1cHByZXNzZWQBABgoTGphdmEvbGFuZy9UaHJvd2FibGU7KVYLADYATAsALgBM
BwBXAQATamF2YS9sYW5nL0V4Y2VwdGlvbgoAVgBZDABaAAYBAA9wcmludFN0YWNrVHJhY2UHAFwB
AAtXbGJKZGJjUGluZwEABENvZGUBAA9MaW5lTnVtYmVyVGFibGUBAARtYWluAQAWKFtMamF2YS9s
YW5nL1N0cmluZzspVgEADVN0YWNrTWFwVGFibGUHAGMBABNbTGphdmEvbGFuZy9TdHJpbmc7AQAK
U291cmNlRmlsZQEAEFdsYkpkYmNQaW5nLmphdmEAIQBbAAIAAAAAAAIAAQAFAAYAAQBdAAAAHQAB
AAEAAAAFKrcAAbEAAAABAF4AAAAGAAEAAAAGAAkAXwBgAAEAXQAAAocAAwAJAAABJCq+BaIAD7IA
BxINtgAPBbgAFSoDMkwqBDJNKr4GoQASKgUytgAZmgAJKgUypwAEAU4SH7gAIVctxgAMKywtuAAn
pwAJKywBuAAnOgQZBLkALQEAOgUZBRIzuQA1AgA6BhkGuQA7AQCZAB4ZBgS5AEACAASgABKyAEQS
R7YADwO4ABWnAA+yAAcSSbYADwS4ABUZBsYAKhkGuQBLAQCnACA6BxkGxgAWGQa5AEsBAKcADDoI
GQcZCLYAUBkHvxkFxgAqGQW5AFQBAKcAIDoGGQXGABYZBbkAVAEApwAMOgcZBhkHtgBQGQa/GQTG
ACoZBLkAVQEApwAgOgUZBMYAFhkEuQBVAQCnAAw6BhkFGQa2AFAZBb+nAA46BBkEtgBYBLgAFbEA
BwBgAJEAoABOAKcArgCxAE4AVQC9AMwATgDTANoA3QBOAEwA6QD4AE4A/wEGAQkATgAxARUBGABW
AAIAXgAAAHIAHAAAAAgABgAJAA4ACgASAAwAFgANABoADgAxABAANwARADsAEgBEABMATAAUAFUA
FQBgABYAdgAXAH4AGACFABoAjQAbAJEAHQCgABEAvQAdAMwAEQDpAB0A+AARARUAIQEYAB4BGgAf
AR8AIAEjACIAYQAAAKEAFRL9ABwHABoHABpABwAa/AATBwAaRQcALv4AOgcALgcANgcAPAtOBwBO
/wAQAAgHAGIHABoHABoHABoHAC4HADYHADwHAE4AAQcATgj5AAJOBwBO/wAQAAcHAGIHABoHABoH
ABoHAC4HADYHAE4AAQcATgj5AAJOBwBO/wAQAAYHAGIHABoHABoHABoHAC4HAE4AAQcATgj5AAJC
BwBWCgABAGQAAAACAGU=
EOF
  fi
  chmod 755 "$W72_TMP"
  [ -f "$W72_TMP/WlbJdbcPing.class" ] && chmod 644 "$W72_TMP/WlbJdbcPing.class"

  # Test 1: Połączenie TCP z jawnym hasłem z profilu DBeaver (wymóg menedżera połączeń GUI)
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

  # Test 3 (negatywny): Próba połączenia TCP bez ~/.pgpass kończy się odmową autoryzacji (wymóg sekretu)
  # shellcheck disable=SC2016
  expect_ok "Próba połączenia TCP bez ~/.pgpass kończy się odmową autoryzacji (wymóg sekretu)" \
    bash -c '
      p="/workspace/jupyter-'"$R1"'/.pgpass"
      trap "mv \"$p.tmp_neg\" \"$p\" 2>/dev/null || true" EXIT
      mv "$p" "$p.tmp_neg"
      if as "'"$R1"'" /usr/share/dbeaver-ce/jre/bin/java \
        -cp "'"$W72_TMP"':/opt/wlb/drivers/postgres/postgresql-42.7.14.jar" \
        WlbJdbcPing "jdbc:postgresql://127.0.0.1:5432/db_'"$R1"'" "'"$R1"'" >/dev/null 2>&1; then
        exit 1
      fi
      exit 0
    '

  # --- DIAGNOSTYKA #369 (NIE bramkuje): dlaczego wrapper/JDBC pada mimo działającego provisioningu ------
  # CI `expect_ok` nie zrzuca stderr padającego polecenia. Prowizjoning już ZASTAJE konta (peer + .pgpass
  # zielone), więc te 4 FAIL to osobna warstwa (wrapper/auth). Zrzucamy stan do logu etapu 5; każde
  # polecenie zabezpieczone `|| true`, a potoki kończą się na `sed`, żeby set -e/pipefail nie wywrócił suite.
  echo "=== DIAG DBeaver/pgJDBC badacz $R1 (nie bramkuje, #369) ==="
  echo "DIAG id: $(as "$R1" id 2>&1 || true)"
  # shellcheck disable=SC2016  # $HOME ma się rozwinąć w powłoce badacza (sudo -H), nie lokalnie
  echo "DIAG HOME: $(as "$R1" bash -c 'printf %s "$HOME"' 2>&1 || true)"
  echo "DIAG .pgpass (hasło zamaskowane):"
  # shellcheck disable=SC2016  # $HOME rozwijany w powłoce badacza
  as "$R1" bash -c 'ls -ld "$HOME/.pgpass" 2>&1; sed -E "s/:[^:]*$/:<REDACTED>/" "$HOME/.pgpass" 2>&1 || true' 2>&1 | sed 's/^/  /' || true
  echo "DIAG rola/baza w PG (superuser):"
  sudo -u postgres psql -tAc "SELECT 'rola='||rolname FROM pg_roles WHERE rolname='$R1'; SELECT 'baza='||datname FROM pg_database WHERE datname='db_$R1'" 2>&1 | sed 's/^/  /' || true
  echo "DIAG czy hasło z .pgpass autoryzuje rolę przez TCP/SCRAM (wykrywa wyścig ALTER ROLE vs .pgpass):"
  # shellcheck disable=SC2016  # $HOME i awk \$5 rozwijane w powłoce badacza, nie lokalnie
  as "$R1" bash -c '
    pw=$(awk -F: "{print \$5}" "$HOME/.pgpass" 2>/dev/null)
    PGPASSWORD="$pw" psql -h 127.0.0.1 -p 5432 -U "'"$R1"'" -d "db_'"$R1"'" -tAc "SELECT 1" 2>&1 || true
  ' 2>&1 | sed 's/^/  /' || true
  echo "DIAG świeży przebieg wrappera (usuwamy profil, uruchamiamy, zrzucamy rc i stderr):"
  # shellcheck disable=SC2016  # $HOME/$f/$rc rozwijane w powłoce badacza
  as "$R1" bash -c '
    f="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
    rm -f "$f" 2>/dev/null || true
    env WLB_DBEAVER_SKIP_EXEC=1 /usr/local/bin/dbeaver; rc=$?
    echo "wrapper rc=$rc"
    ls -ld "$f" 2>&1 || true
  ' 2>&1 | sed 's/^/  /' || true
  echo "=== koniec DIAG #369 ==="

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
