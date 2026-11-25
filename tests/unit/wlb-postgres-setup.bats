#!/usr/bin/env bats
# wlb-postgres-setup.bats — testy jednostkowe tworzenia klastra PG (#271).
# Krytyczne: wymiana dysku systemowego NIE może wywołać initdb na istniejących danych.
# Stubuje pg_createcluster, install, chown, logger; asercje na CALLS.

load helpers.bash

SCRIPT="$REPO_ROOT/ansible/roles/postgres/files/wlb-postgres-setup"

setup() {
  setup_sandbox
  PGDATA="$SANDBOX/workspace/pgdata"
  STAGE="$SANDBOX/stage"
  CONFDIR="$SANDBOX/confdir"
  mkdir -p "$SANDBOX/workspace" "$STAGE" "$CONFDIR"
  printf 'conf\n' >"$STAGE/50-wlb.conf"
  printf 'hba\n' >"$STAGE/pg_hba.conf"
  printf 'ident\n' >"$STAGE/pg_ident.conf"
  stub pg_createcluster
  stub install
  stub chown
  stub logger
  export WLB_PG_DATA_DIR="$PGDATA" WLB_PG_STAGE_DIR="$STAGE" WLB_PG_CONF_DIR="$CONFDIR"
}

@test "setup: brak klastra -> pg_createcluster z --datadir na /workspace (#271)" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  calls | grep -qE "pg_createcluster 16 main --datadir=$PGDATA"
}

@test "setup: istniejący klaster (wymiana dysku) NIE wywołuje pg_createcluster (#271)" {
  mkdir -p "$PGDATA"
  printf '16\n' >"$PGDATA/PG_VERSION"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  refute called 'pg_createcluster'                  # dane istnieją + CONFDIR obecny -> bez initdb/adopcji
  [[ "$output" == *"konfiguracja WLB nałożona"* ]]
}

@test "setup: istniejący klaster — nakłada konfigurację gdy CONFDIR istnieje (#271)" {
  mkdir -p "$PGDATA"
  printf '16\n' >"$PGDATA/PG_VERSION"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  # install wywołany na plikach konfiguracji WLB (conf.d / pg_hba / pg_ident)
  calls | grep -q "install.*50-wlb.conf"
  calls | grep -q "install.*pg_hba.conf"
}

@test "setup: istniejący klaster bez CONFDIR (świeży dysk) rejestruje datadir i nakłada konfigurację (#369 P1)" {
  # Dane są (PG_VERSION), ale katalog konfiguracji zniknął po wymianie dysku systemowego. Wcześniej
  # skrypt kończył się „sukcesem" bez konfiguracji WLB. Teraz adoptuje datadir (bez initdb) i konfiguruje.
  rm -rf "$CONFDIR"
  mkdir -p "$PGDATA"
  printf '16\n' >"$PGDATA/PG_VERSION"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  calls | grep -qE "pg_createcluster 16 main --datadir=$PGDATA" # adopcja istniejącego datadir (NIE initdb)
  calls | grep -q "install.*50-wlb.conf"                        # konfiguracja WLB nałożona, nie cichy sukces
}

@test "setup: katalog roboczy niezamontowany -> die, bez pg_createcluster (#271)" {
  export WLB_PG_DATA_DIR="$SANDBOX/niezamontowany/pgdata" # rodzic nie istnieje
  run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nie jest zamontowany"* ]]
  refute called 'pg_createcluster'
}
