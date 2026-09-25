#!/usr/bin/env bats
# Strażnik zasobów ci/guard.sh: klasyfikacja wyniku, tryb opcjonalny, dziennik guard.jsonl.

load helpers

GUARD="$REPO_ROOT/ci/guard.sh"

setup() {
  export GUARD_LOG_DIR="$BATS_TEST_TMPDIR/logs" GUARD_NO_CGROUP=1
  unset GITHUB_ACTIONS
}

last() { tail -1 "$GUARD_LOG_DIR/guard.jsonl"; }

@test "sukces: kod 0 i wpis OK" {
  run "$GUARD" --name prosty -- true
  [ "$status" -eq 0 ]
  last | grep -q '"name": "prosty", "status": "OK", "exit_code": 0'
}

@test "błąd polecenia: kod przekazany dalej, wpis FAIL, wskazówka z runbooka" {
  run "$GUARD" --name test-a -- bash -c 'exit 3'
  [ "$status" -eq 3 ]
  last | grep -q '"status": "FAIL", "exit_code": 3'
  [[ $output == *"[FAIL: test-a] Kod wyjścia 3"*"docs/ci-runbook.md#test"* ]]
}

@test "przekroczony czas: TIMEOUT (kod 124)" {
  run "$GUARD" --name wolny --timeout 1s -- sleep 5
  [ "$status" -eq 124 ]
  last | grep -q '"status": "TIMEOUT"'
  [[ $output == *"[TIMEOUT: wolny] Przekroczony limit czasu 1s"* ]]
}

@test "opcjonalny krok: błąd raportowany, ale nie przerywa" {
  run "$GUARD" --name raport --optional --timeout 1s -- sleep 5
  [ "$status" -eq 0 ]
  last | grep -q '"status": "TIMEOUT".*"optional": true'
}

@test "SIGKILL bez cgroup to FAIL, nie OOM" {
  run "$GUARD" --name zabity -- bash -c 'kill -9 $$'
  [ "$status" -eq 137 ]
  last | grep -q '"status": "FAIL", "exit_code": 137'
}

@test "adnotacje GitHub w CI" {
  GITHUB_ACTIONS=true run "$GUARD" --name ci-krok -- false
  [[ $output == *"::error title=FAIL: ci-krok::Kod wyjścia 1"* ]]
  GITHUB_ACTIONS=true run "$GUARD" --name ci-opc --optional -- false
  [[ $output == *"::warning title=FAIL: ci-opc::"* ]]
}

@test "limit pamięci bez systemd: ostrzeżenie i tylko limit czasu" {
  GUARD_NO_CGROUP=0 PATH="$BATS_TEST_TMPDIR/nosystemd:$PATH" run bash -c "
    mkdir -p '$BATS_TEST_TMPDIR/nosystemd'
    printf '#!/bin/sh\nexit 1\n' > '$BATS_TEST_TMPDIR/nosystemd/systemd-run'
    printf '#!/bin/sh\nexit 1\n' > '$BATS_TEST_TMPDIR/nosystemd/sudo'
    chmod +x '$BATS_TEST_TMPDIR/nosystemd/'*
    '$GUARD' --name bez-cgroup --memory 1G -- true"
  [ "$status" -eq 0 ]
  [[ $output == *"bez limitu pamięci"* ]]
}

@test "błędne wywołanie" {
  run "$GUARD" -- true
  [ "$status" -eq 2 ]
  run "$GUARD" --name x --nieznana -- true
  [ "$status" -eq 2 ]
}

@test "--memory auto: pamięć maszyny minus 1 GB" {
  run "$GUARD" --name auto --memory auto -- true
  [ "$status" -eq 0 ]
  expected=$(($(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 - 1024))M
  last | grep -q "\"memory\": \"$expected\""
}
