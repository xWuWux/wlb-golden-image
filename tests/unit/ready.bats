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
  printf '{"lint":{"result":"%s","outputs":{"image":"false"}},"build-check":{"result":"success"},"security":{"result":"success"},"observability":{"result":"success"},"unit":{"result":"success"},"mutation":{"result":"%s"},"integration":{"result":"%s"},"perf":{"result":"skipped"},"ephemeral":{"result":"skipped"}}' \
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
