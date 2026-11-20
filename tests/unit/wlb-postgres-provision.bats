#!/usr/bin/env bats
# wlb-postgres-provision.bats — testy jednostkowe provisioningu PostgreSQL per konto badacza (#271).
# Stubuje psql (nagrywa SQL), chown, logger. Weryfikuje kontrakt .pgpass, idempotencję i izolację.

load helpers.bash

SCRIPT="$REPO_ROOT/ansible/roles/postgres/files/wlb-postgres-provision"

setup() {
  setup_sandbox
  command -v awk >/dev/null 2>&1 || skip "brak awk"
  SECRET="$SANDBOX/secret"
  HOMEBASE="$SANDBOX/workspace"
  mkdir -p "$SECRET" "$HOMEBASE/jupyter-u01" "$HOMEBASE/jupyter-u02"
  PSQL_LOG="$SANDBOX/psql.log"
  : >"$PSQL_LOG"
  # psql stub: nagrywa argumenty i stdin do PSQL_LOG
  cat >"$STUBS/psql" <<EOF
#!/usr/bin/env bash
echo "ARGS: \$*" >>"$PSQL_LOG"
cat >>"$PSQL_LOG"
echo "===" >>"$PSQL_LOG"
EOF
  chmod +x "$STUBS/psql"
  stub chown
  stub logger
  # Fałszywy getent: u01/u02 (badacze) + a01 (admin, NIE powinien dostać roli) + nobody
  printf 'root:x:0:0::/root:/bin/bash\njupyter-u01:x:10001:10001::/workspace/jupyter-u01:/bin/bash\njupyter-u02:x:10002:10002::/workspace/jupyter-u02:/bin/bash\njupyter-a01:x:10000:10000::/workspace/jupyter-a01:/bin/bash\nnobody:x:65534:65534::/nonexistent:/usr/sbin/nologin\n' >"$SANDBOX/passwd"
  export WLB_PG_PSQL="$STUBS/psql"
  export WLB_PG_SECRET_DIR="$SECRET"
  export WLB_PG_HOME_BASE="$HOMEBASE"
  export WLB_PG_GETENT="cat $SANDBOX/passwd"
}

@test "provision: tworzy rolę uNN i bazę db_uNN OWNER uNN w SQL (#271)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q 'CREATE ROLE "u01" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE' "$PSQL_LOG"
  grep -q 'CREATE DATABASE "db_u01" OWNER "u01"' "$PSQL_LOG"
  grep -q 'REVOKE CONNECT ON DATABASE "db_u01" FROM PUBLIC' "$PSQL_LOG"
  grep -q 'REVOKE ALL ON SCHEMA public FROM PUBLIC' "$PSQL_LOG"
}

@test "provision: .pgpass pod jupyter-uNN z poprawnym formatem i 0600 (#271)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  pgpass="$HOMEBASE/jupyter-u01/.pgpass"
  [ -f "$pgpass" ]
  [[ $(stat -c %a "$pgpass") == 600 ]]
  # format: 127.0.0.1:5432:db_u01:u01:<32 znaki hasła>
  run cat "$pgpass"
  [[ "$output" =~ ^127\.0\.0\.1:5432:db_u01:u01:[A-Za-z0-9]{32}$ ]]
  # właściciel ustawiany przez chown (stub) na jupyter-u01:jupyter-u01
  calls | grep -q "chown jupyter-u01:jupyter-u01 $pgpass"
}

@test "provision: hasło idempotentne — istniejący pwfile reużyty, .pgpass spójny (#271)" {
  printf 'STALEHASLO000000000000000000ABCD' >"$SECRET/wlb-pg-u01-initial-password" # 32 znaki
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q "127.0.0.1:5432:db_u01:u01:STALEHASLO000000000000000000ABCD" "$HOMEBASE/jupyter-u01/.pgpass"
  # hasło w SQL ALTER ROLE też to stałe (nie przegenerowane)
  grep -q "PASSWORD 'STALEHASLO000000000000000000ABCD'" "$PSQL_LOG"
}

@test "provision: konto admina a01 NIE dostaje roli (tylko uNN) (#271)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  ! grep -q '"a01"' "$PSQL_LOG"
  [ ! -e "$HOMEBASE/jupyter-a01/.pgpass" ]
}

@test "provision: konto bez katalogu domowego — rola tworzona, .pgpass pominięty (#271)" {
  rm -rf "$HOMEBASE/jupyter-u02"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q 'CREATE ROLE "u02"' "$PSQL_LOG"
  [ ! -e "$HOMEBASE/jupyter-u02/.pgpass" ]
}

@test "provision: brak kont uNN -> exit 0 bez wywołań psql (#271)" {
  printf 'root:x:0:0::/root:/bin/bash\nnobody:x:65534:65534::/nonexistent:/usr/sbin/nologin\n' >"$SANDBOX/passwd"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"nic do zrobienia"* ]]
  [ ! -s "$PSQL_LOG" ]
}
