#!/usr/bin/env bats
# Testy jednostkowe kopii bazy huba sprzed migracji schematu (#13, RB-05) w piaskownicy.

load helpers

setup() {
  setup_sandbox
  command -v sqlite3 >/dev/null || skip "sqlite3 niedostępne"
  SCRIPT="$REPO_ROOT/ansible/roles/tljh/files/wlb-hub-db-preupgrade"
  export WLB_HUB_DB="$SANDBOX/workspace/.wlb-hub/jupyterhub.sqlite"
  export WLB_HUB_BACKUP_DIR="$SANDBOX/workspace/.wlb-hub/backup"
  export WLB_IMAGE_RELEASE="$SANDBOX/image-release"
  mkdir -p "$(dirname "$WLB_HUB_DB")"
  printf 'WLB_IMAGE_VERSION=0.1.0\n' >"$WLB_IMAGE_RELEASE"
}

mkdb() { sqlite3 "$WLB_HUB_DB" "create table t(x); insert into t values(1);"; }

@test "świeży dysk bez bazy -> brak kopii (#13)" {
  run "$SCRIPT"
  [ "$status" -eq 0 ]
  run bash -c "ls '$WLB_HUB_BACKUP_DIR' 2>/dev/null"
  [ -z "$output" ]
}

@test "kopia pre-<wersja> powstaje, gdy baza istnieje (#13)" {
  mkdb
  run "$SCRIPT"
  [ "$status" -eq 0 ]
  [ -f "$WLB_HUB_BACKUP_DIR/jupyterhub.sqlite.pre-0.1.0" ]
  run sqlite3 "$WLB_HUB_BACKUP_DIR/jupyterhub.sqlite.pre-0.1.0" "select x from t;"
  [ "$output" = "1" ]
}

@test "druga próba tej samej wersji nie nadpisuje starej kopii (#13)" {
  mkdb
  "$SCRIPT"
  sqlite3 "$WLB_HUB_DB" "insert into t values(2);"
  "$SCRIPT"
  run sqlite3 "$WLB_HUB_BACKUP_DIR/jupyterhub.sqlite.pre-0.1.0" "select count(*) from t;"
  [ "$output" = "1" ]
}

@test "brak image-release -> pre-unknown (#13)" {
  rm -f "$WLB_IMAGE_RELEASE"
  mkdb
  run "$SCRIPT"
  [ "$status" -eq 0 ]
  [ -f "$WLB_HUB_BACKUP_DIR/jupyterhub.sqlite.pre-unknown" ]
}
