#!/usr/bin/env bats
# Testy końcowej bramki (ci/ready.sh): każdy wymagany etap musi blokować, także 4b (mutacje).
# NEEDS jest JSON-em z GitHub Actions (toJSON(needs)).

load helpers

READY="$REPO_ROOT/ci/ready.sh"

setup() {
  # ready.sh dopisuje podsumowanie do GITHUB_STEP_SUMMARY; w testach nie chcemy zaśmiecać
  # podsumowania joba unit — kierujemy je do pliku tymczasowego.
  export GITHUB_STEP_SUMMARY="$BATS_TEST_TMPDIR/summary.md"
}

needs_json() { # needs_json WYNIK_LINT WYNIK_MUTATION [WYNIK_INTEGRATION]
  printf '{"lint":{"result":"%s","outputs":{"image":"false"}},"build-check":{"result":"success"},"security":{"result":"success"},"security-report":{"result":"success"},"observability":{"result":"success"},"formal-logic":{"result":"success"},"unit":{"result":"success"},"mutation":{"result":"%s"},"integration":{"result":"%s"},"perf":{"result":"skipped"},"ephemeral":{"result":"skipped"}}' \
    "$1" "$2" "${3:-skipped}"
}

@test "ready: wszystkie wymagane zielone (mutation success) -> gotowe" {
  run env NEEDS="$(needs_json success success)" "$READY"
  [ "$status" -eq 0 ]
  [[ $output == *"Gotowe do code review i merge"* ]]
  [[ $output == *"4b. Testy mutacyjne"* ]]
}

@test "ready: mutation failure blokuje merge (4b jest wymagany)" {
  run env NEEDS="$(needs_json success failure)" "$READY"
  [ "$status" -eq 1 ]
  [[ $output == *"4b. Testy mutacyjne"*"blokuje"* ]]
  [[ $output == *"Nie gotowe"* ]]
}

@test "ready: mutation skipped blokuje (wymagany etap nie może być pominięty)" {
  run env NEEDS="$(needs_json success skipped)" "$READY"
  [ "$status" -eq 1 ]
}

@test "ready: integracja pominięta przy image=false nie blokuje" {
  run env NEEDS="$(needs_json success success skipped)" "$READY"
  [ "$status" -eq 0 ]
}

@test "ready: build-base w needs blokuje merge przy awarii gdy image=true (#288)" {
  local json='{"lint":{"result":"success","outputs":{"image":"true"}},"build-check":{"result":"success"},"security":{"result":"success"},"security-report":{"result":"success"},"observability":{"result":"success"},"formal-logic":{"result":"success"},"unit":{"result":"success"},"mutation":{"result":"success"},"build-base":{"result":"failure"},"integration":{"result":"skipped"},"perf":{"result":"skipped"},"ephemeral":{"result":"skipped"}}'
  run env NEEDS="$json" "$READY"
  [ "$status" -eq 1 ]
  [[ $output == *"5a. Budowa bazy"*"blokuje"* ]]
}

@test "ready: build-base w needs zaliczony gdy image=true (#288)" {
  local json='{"lint":{"result":"success","outputs":{"image":"true"}},"build-check":{"result":"success"},"security":{"result":"success"},"security-report":{"result":"success"},"observability":{"result":"success"},"formal-logic":{"result":"success"},"unit":{"result":"success"},"mutation":{"result":"success"},"build-base":{"result":"success"},"integration":{"result":"success"},"perf":{"result":"skipped"},"ephemeral":{"result":"skipped"}}'
  run env NEEDS="$json" "$READY"
  [ "$status" -eq 0 ]
  [[ $output == *"5a. Budowa bazy"* ]]
  [[ $output == *"Gotowe do code review i merge"* ]]
}

setup_card_repo() {
  # Test karty nie może zależeć od historii głównego repo (CI checkout bywa shallow).
  local repo="$BATS_TEST_TMPDIR/card-repo"
  git init -q "$repo"
  git -C "$repo" config user.email test@example.invalid
  git -C "$repo" config user.name test
  printf 'base\n' >"$repo/file.txt"
  git -C "$repo" add file.txt
  git -C "$repo" commit -q -m base
  local base
  base=$(git -C "$repo" rev-parse HEAD)
  printf 'head\n' >"$repo/file.txt"
  git -C "$repo" commit -q -am head
  git -C "$repo" update-ref refs/remotes/origin/main "$base"
  cp -R "$REPO_ROOT/ci" "$repo/ci"
  READY="$repo/ci/ready.sh"
  cd "$repo" || return 1
}

@test "ready: generuje karte inspekcji PR w GITHUB_STEP_SUMMARY" {
  setup_card_repo
  run env GITHUB_BASE_REF=main NEEDS="$(needs_json success success)" "$READY"
  [ "$status" -eq 0 ]
  [ -f "$GITHUB_STEP_SUMMARY" ]
  grep -q "Automatyczna Karta PR" "$GITHUB_STEP_SUMMARY"
}

@test "ready: bez GITHUB_BASE_REF nie generuje karty inspekcji" {
  setup_card_repo
  run env -u GITHUB_BASE_REF NEEDS="$(needs_json success success)" "$READY"
  [ "$status" -eq 0 ]
  if grep -q "Automatyczna Karta PR" "$GITHUB_STEP_SUMMARY"; then
    false
  fi
}

@test "ready: nieistniejacy GITHUB_BASE_REF nie generuje karty inspekcji" {
  setup_card_repo
  run env GITHUB_BASE_REF="no-such-base-376" NEEDS="$(needs_json success success)" "$READY"
  [ "$status" -eq 0 ]
  if grep -q "Automatyczna Karta PR" "$GITHUB_STEP_SUMMARY"; then
    false
  fi
}
