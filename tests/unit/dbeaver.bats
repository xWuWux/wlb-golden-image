#!/usr/bin/env bats
# shellcheck disable=SC2030,SC2031
# dbeaver.bats — testy jednostkowe wrappera DBeaver i szablonu data-sources.template.json (#271).
# Sprawdza:
# 1. Podstawienie roli badacza i nazwy bazy (jupyter-u01 -> u01, db_u01).
# 2. Format i brak zapisanego hasła w wygenerowanym profilu JSON (kontrakt .pgpass).
# 3. Uprawnienia pliku (0600).
# 4. Idempotencję (istniejący plik nie jest nadpisywany).
# 5. Podstawienie dla kont bez prefiksu jupyter- (u02 -> u02, db_u02).
# 6. Poprawność składniową szablonu JSON.
# 7. Zachowanie w przypadku braku szablonu (skip).

load helpers.bash

setup() {
  setup_sandbox
  export HOME="$SANDBOX/home"
  mkdir -p "$HOME"
  TEMPLATE="$REPO_ROOT/ansible/roles/dbeaver/files/data-sources.template.json"
  WRAPPER="$REPO_ROOT/ansible/roles/dbeaver/files/dbeaver-wrapper"
  export WLB_DBEAVER_TEMPLATE="$TEMPLATE"
  export WLB_DBEAVER_SKIP_EXEC=1
}

@test "wrapper: generuje data-sources.json dla jupyter-u01 z rolą u01 i bazą db_u01 (#271)" {
  export WLB_TEST_USER="jupyter-u01"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [ -f "$target" ]
  grep -q '"database": "db_u01"' "$target"
  grep -q '"user": "u01"' "$target"
  grep -q '"url": "jdbc:postgresql://127.0.0.1:5432/db_u01"' "$target"
  grep -q '"host": "127.0.0.1"' "$target"
  grep -q '"port": "5432"' "$target"
}

@test "wrapper: wygenerowany profil ma uprawnienia 0600 (#271)" {
  export WLB_TEST_USER="jupyter-u01"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [[ $(stat -c %a "$target") == 600 ]]
}

@test "wrapper: wygenerowany profil NIE zawiera jawnego hasła (#271)" {
  export WLB_TEST_USER="jupyter-u01"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  grep -q '"save-password": false' "$target"
  # Brak atrybutów haseł w wygenerowanym JSON
  refute grep -iE '("userPassword"|"password"[[:space:]]*:)' "$target"
}

@test "wrapper: idempotencja — istniejący plik nie jest nadpisywany (#271)" {
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  mkdir -p "$(dirname "$target")"
  echo '{"existing": true}' >"$target"
  export WLB_TEST_USER="jupyter-u01"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  run cat "$target"
  [ "$output" = '{"existing": true}' ]
}

@test "wrapper: konto bez prefiksu jupyter- (np. u02) podstawia się poprawnie (#271)" {
  export WLB_TEST_USER="u02"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  grep -q '"database": "db_u02"' "$target"
  grep -q '"user": "u02"' "$target"
}

@test "szablon: poprawny format JSON (#271)" {
  python3 -m json.tool "$TEMPLATE" >/dev/null
}

@test "wrapper: pomija tworzenie gdy brak szablonu (#271)" {
  export WLB_DBEAVER_TEMPLATE="$SANDBOX/nonexistent.json"
  export WLB_TEST_USER="jupyter-u01"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [ ! -f "$target" ]
}
