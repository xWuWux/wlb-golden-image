#!/usr/bin/env bats
# Testy harnessu mutacji powłoki (ci/mutation-bash.sh): walidacja tabeli oraz wykrywanie mutacji
# zabitych i przeżytych na syntetycznym fixture. Nie uruchamiają mutacji na prawdziwym repo.

load helpers

HARNESS="$REPO_ROOT/ci/mutation-bash.sh"

setup() {
  setup_sandbox
  FIX="$BATS_TEST_TMPDIR/fixture"
  mkdir -p "$FIX/ansible/roles/x/files" "$FIX/tests/unit" "$FIX/ci/mutations"
  cat >"$FIX/ansible/roles/x/files/skrypt" <<'EOF'
#!/usr/bin/env bash
echo one
echo unused
EOF
  chmod +x "$FIX/ansible/roles/x/files/skrypt"
  # Test sprawdza tylko pierwszy wiersz — mutacja drugiego echo MUSI przeżyć (luka w teście).
  cat >"$FIX/tests/unit/x.bats" <<'EOF'
#!/usr/bin/env bats
@test "skrypt wypisuje one" {
  run bash "$BATS_TEST_DIRNAME/../../ansible/roles/x/files/skrypt"
  [ "${lines[0]}" = one ]
}
EOF
  export MUTATION_REPO_ROOT="$FIX" MUTATION_TABLE="$FIX/ci/mutations/bash-mutations.tsv"
}

@test "harness: --check przyjmuje poprawną tabelę" {
  printf 'ansible/roles/x/files/skrypt\techo unused\techo used\ttests/unit/x.bats\t-\tprzeżyta\n' >"$MUTATION_TABLE"
  run "$HARNESS" --check
  [ "$status" -eq 0 ]
  [[ $output == *"1 mutacji"* ]]
}

@test "harness: --check odrzuca fragment nieobecny w pliku" {
  printf 'ansible/roles/x/files/skrypt\techo nie-ma\techo jest\ttests/unit/x.bats\t-\tzła\n' >"$MUTATION_TABLE"
  run "$HARNESS" --check
  [ "$status" -eq 1 ]
  [[ $output == *"występuje 0 razy"* ]]
}

@test "harness: mutacja przeżyta -> survived i błąd (luka w teście)" {
  printf 'ansible/roles/x/files/skrypt\techo unused\techo used\ttests/unit/x.bats\t-\tprzeżyta\n' >"$MUTATION_TABLE"
  run "$HARNESS"
  [ "$status" -eq 1 ]
  [[ $output == *"survived"* ]]
  [[ $output == *"przeżyły: **1**"* ]]
}

@test "harness: mutacja zabita -> exit 0" {
  printf 'ansible/roles/x/files/skrypt\techo one\techo two\ttests/unit/x.bats\t-\tzabita\n' >"$MUTATION_TABLE"
  run "$HARNESS"
  [ "$status" -eq 0 ]
  [[ $output == *"Zabite: **1**"* ]]
}

@test "harness: filtr bez pasującego testu jest błędem, nie fałszywym killed" {
  printf 'ansible/roles/x/files/skrypt\techo one\techo two\ttests/unit/x.bats\tnieistniejacy\tpusty filtr\n' >"$MUTATION_TABLE"
  run "$HARNESS"
  [ "$status" -eq 1 ]
  [[ $output == *"nie wybrał żadnego testu"* ]]
}

@test "harness: prawdziwa tabela repo przechodzi --check" {
  unset MUTATION_REPO_ROOT MUTATION_TABLE
  run "$HARNESS" --check
  [ "$status" -eq 0 ]
}

@test "harness: pusta tabela to błąd" {
  : >"$MUTATION_TABLE"
  run "$HARNESS" --check
  [ "$status" -eq 1 ]
  [[ $output == *"tabela mutacji jest pusta"* ]]
}

@test "harness: --check odrzuca brak pliku testu" {
  printf 'ansible/roles/x/files/skrypt\techo one\techo two\ttests/unit/nie-ma.bats\t-\tbrak testu\n' >"$MUTATION_TABLE"
  run "$HARNESS" --check
  [ "$status" -eq 1 ]
  [[ $output == *"brak testu"* ]]
}

@test "harness: --check odrzuca fragment występujący więcej niż raz" {
  printf '#!/usr/bin/env bash\necho one\necho one\n' >"$FIX/ansible/roles/x/files/skrypt2"
  printf 'ansible/roles/x/files/skrypt2\techo one\techo two\ttests/unit/x.bats\t-\tniejednoznaczna\n' >"$MUTATION_TABLE"
  run "$HARNESS" --check
  [ "$status" -eq 1 ]
  [[ $output == *"występuje 2 razy"* ]]
}

@test "harness: zepsuty baseline (błąd składni testu) nie udaje zabitej mutacji" {
  printf '#!/usr/bin/env bats\n@test "niedomknięty" {\n' >"$FIX/tests/unit/zepsuty.bats"
  printf 'ansible/roles/x/files/skrypt\techo one\techo two\ttests/unit/zepsuty.bats\t-\tzepsuty baseline\n' >"$MUTATION_TABLE"
  run "$HARNESS"
  [ "$status" -eq 1 ]
  [[ $output == *"baseline czerwony"* ]]
  [[ $output == *"błąd baseline"* ]]
}

@test "harness: --output zapisuje raport do pliku" {
  printf 'ansible/roles/x/files/skrypt\techo one\techo two\ttests/unit/x.bats\t-\tzabita\n' >"$MUTATION_TABLE"
  report="$BATS_TEST_TMPDIR/raport.md"
  run "$HARNESS" --output "$report"
  [ "$status" -eq 0 ]
  [ -s "$report" ]
  grep -q 'Zabite: \*\*1\*\*' "$report"
}

@test "harness: filtr łapiący dwa testy jest błędem (wymagany dokładnie 1)" {
  cat >"$FIX/tests/unit/dwa.bats" <<'BATS'
#!/usr/bin/env bats
@test "pierwszy" {
  run bash "$BATS_TEST_DIRNAME/../../ansible/roles/x/files/skrypt"
  [ "${lines[0]}" = one ]
}

@test "drugi" {
  run bash "$BATS_TEST_DIRNAME/../../ansible/roles/x/files/skrypt"
  [ "${lines[1]}" = unused ]
}
BATS
  printf 'ansible/roles/x/files/skrypt\techo one\techo two\ttests/unit/dwa.bats\t-\tzabita\n' >"$MUTATION_TABLE"
  run "$HARNESS"
  [ "$status" -eq 1 ]
  [[ $output == *"wybrał 2 testów"* ]]
  [[ $output == *"zły filtr"* ]]
}
