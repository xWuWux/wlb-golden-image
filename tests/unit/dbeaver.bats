#!/usr/bin/env bats
# shellcheck disable=SC2030,SC2031
# dbeaver.bats — testy jednostkowe wrappera DBeaver i szablonu data-sources.template.json (#271).
# Sprawdza:
# 1. Podstawienie roli badacza i nazwy bazy (jupyter-u01 -> u01, db_u01).
# 2. Wstrzyknięcie hasła z ~/.pgpass do wygenerowanego profilu JSON (save-password: true).
# 3. Uprawnienia pliku (0600).
# 4. Idempotencję (istniejący plik nie jest nadpisywany).
# 5. Podstawienie dla kont bez prefiksu jupyter- (u02 -> u02, db_u02) z hasłem z .pgpass.
# 6. Poprawność składniową szablonu JSON i brak jawnych haseł w szablonie git (@PASSWORD@).
# 7. Zachowanie w przypadku braku szablonu (skip).
# 8. Zachowanie przy braku .pgpass (generuje profil z pustym hasłem bez wywrotki).
# 9. Obsługa haseł ze znakami specjalnymi (&, /, ", \) bez uszkadzania składni JSON.

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
  grep -q '"save-password": true' "$target"
}

@test "wrapper: wstrzykuje hasło z ~/.pgpass do wygenerowanego profilu DBeaver (#271)" {
  export WLB_TEST_USER="jupyter-u01"
  printf '127.0.0.1:5432:db_u01:u01:TajneHasloBadacza12345\n' >"$HOME/.pgpass"
  chmod 600 "$HOME/.pgpass"

  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [ -f "$target" ]
  grep -q '"userPassword": "TajneHasloBadacza12345"' "$target"
  grep -q '"password": "TajneHasloBadacza12345"' "$target"
  grep -q '"save-password": true' "$target"
}

@test "wrapper: wygenerowany profil ma uprawnienia 0600 (#271)" {
  export WLB_TEST_USER="jupyter-u01"
  printf '127.0.0.1:5432:db_u01:u01:Haslo0600\n' >"$HOME/.pgpass"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [[ $(stat -c %a "$target") == 600 ]]
}

@test "wrapper: idempotencja — istniejący plik nie jest nadpisywany (#271)" {
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  mkdir -p "$(dirname "$target")"
  echo '{"existing": true}' >"$target"
  export WLB_TEST_USER="jupyter-u01"
  printf '127.0.0.1:5432:db_u01:u01:NoweHaslo\n' >"$HOME/.pgpass"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  run cat "$target"
  [ "$output" = '{"existing": true}' ]
}

@test "wrapper: konto bez prefiksu jupyter- (np. u02) pobiera hasło dla u02 (#271)" {
  export WLB_TEST_USER="u02"
  printf '127.0.0.1:5432:db_u02:u02:HasloU02Weryfikacja\n' >"$HOME/.pgpass"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  grep -q '"database": "db_u02"' "$target"
  grep -q '"user": "u02"' "$target"
  grep -q '"userPassword": "HasloU02Weryfikacja"' "$target"
}

@test "szablon: poprawny format JSON i brak jawnych haseł w repo (tylko placeholder) (#271)" {
  python3 -m json.tool "$TEMPLATE" >/dev/null
  grep -q '"userPassword": "@PASSWORD@"' "$TEMPLATE"
  grep -q '"password": "@PASSWORD@"' "$TEMPLATE"
}

@test "wrapper: pomija tworzenie gdy brak szablonu (#271)" {
  export WLB_DBEAVER_TEMPLATE="$SANDBOX/nonexistent.json"
  export WLB_TEST_USER="jupyter-u01"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [ ! -f "$target" ]
}

@test "wrapper: brak .pgpass generuje profil z pustym hasłem bez wywrotki (#271)" {
  export WLB_TEST_USER="jupyter-u01"
  rm -f "$HOME/.pgpass"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [ -f "$target" ]
  grep -q '"userPassword": ""' "$target"
}

@test "wrapper: bezpieczna obsługa haseł ze znakami specjalnymi (&, /, \", \\) (#271)" {
  export WLB_TEST_USER="jupyter-u01"
  printf '127.0.0.1:5432:db_u01:u01:Trudne&Haslo/Z\\Znakami"Specjalnymi\n' >"$HOME/.pgpass"
  chmod 600 "$HOME/.pgpass"
  run bash "$WRAPPER"
  [ "$status" -eq 0 ]
  target="$HOME/.local/share/DBeaverData/workspace6/General/.dbeaver/data-sources.json"
  [ -f "$target" ]
  # Sprawdzenie czy plik jest w 100% poprawnym JSON po podstawieniu
  python3 -m json.tool "$target" >/dev/null
  # Weryfikacja dokładnej wartości hasła z deserializacji JSON
  python3 -c '
import json
with open("'"$target"'") as f:
    d = json.load(f)
pw = d["connections"]["wlb-local-postgres"]["configuration"]["auth-properties"]["userPassword"]
assert pw == "Trudne&Haslo/Z\\Znakami\"Specjalnymi", f"Niepoprawne haslo: {pw}"
'
}
