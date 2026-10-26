#!/usr/bin/env bats
# Bramkowanie kosztownych etapów 5–6 (ci/changes.sh). Kluczowa zasada #86:
# etap 5 NIE uruchamia się domyślnie na PR; bramka jest po merge do main, na etykietę, nocą lub lokalnie.

load helpers

CHANGES="$REPO_ROOT/ci/changes.sh"

# has_line WZORZEC — czy wyjście skryptu zawiera dokładnie taką linię klucz=wartość
has_line() { echo "$output" | grep -qx "$1"; }

# repo_with_base PLIK... — tworzy repo git z bazowym commitem i zmianą podanych plików w HEAD;
# ustawia $BASE na SHA bazy i przechodzi do repo (dla ścieżki push/doc_only).
repo_with_base() {
  local r="$BATS_TEST_TMPDIR/repo"
  rm -rf "$r"
  mkdir -p "$r"
  cd "$r" || return 1
  git init -q
  git config user.email t@example.com
  git config user.name tester
  mkdir -p docs
  echo base >README.md
  echo base >docs/x.md
  git add -A
  git commit -qm base
  BASE=$(git rev-parse HEAD)
  for f in "$@"; do mkdir -p "$(dirname "$f")"; echo zmiana >>"$f"; done
  git add -A
  git commit -qm head
  export BASE
}

# --- PR: domyślnie BEZ etapu 5 (największa oszczędność minut) ---

@test "PR bez etykiet: etap 5/6 pominięty (#86)" {
  repo_with_base docs/x.md
  run env EVENT=pull_request LABELS='[]' bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=false"
  has_line "perf=false"
  has_line "ephemeral=false"
}

@test "PR ze zmianą kodu obrazu, ale bez etykiety: nadal bez etapu 5 (#86)" {
  repo_with_base envs/r/renv.lock
  run env EVENT=pull_request LABELS='["dokumentacja"]' bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=false"
}

@test "PR z etykietą run-integration: etap 5 na żądanie (#86)" {
  run env EVENT=pull_request LABELS='["run-integration"]' BASE= bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=true"
}

@test "PR z etykietą perf: etap 5 + 6a (etap 6 potrzebuje obrazu)" {
  run env EVENT=pull_request LABELS='["perf"]' BASE= bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=true"
  has_line "perf=true"
}

@test "PR z etykietą deploy-test: etap 5 + 6b" {
  run env EVENT=pull_request LABELS='["deploy-test"]' BASE= bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=true"
  has_line "ephemeral=true"
}

# --- push do main: bramka po-merge ---

@test "push ze zmianą kodu: etap 5 jako bramka po-merge" {
  repo_with_base ansible/roles/tljh/files/wlb-hub-user
  run env EVENT=push bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=true"
}

@test "push tylko z dokumentacją: etap 5 pominięty" {
  repo_with_base README.md docs/x.md
  run env EVENT=push bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=false"
}

@test "push z pustą/zerową bazą: buduj dla bezpieczeństwa" {
  repo_with_base README.md
  run env EVENT=push BASE=0000000000000000000000000000000000000000 bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=true"
}

# --- schedule / workflow_dispatch ---

@test "schedule nocny (NIGHTLY_CRON): pełny build 1–6" {
  run env EVENT=schedule SCHEDULE="0 3 * * 2,5" bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=true"
  has_line "perf=true"
}

@test "schedule tygodniowy (inny cron): tylko etapy 1–4" {
  run env EVENT=schedule SCHEDULE="0 5 * * 1" bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=false"
}

@test "workflow_dispatch: ręczny pełny build; IN_PERF wyzwala 6a" {
  run env EVENT=workflow_dispatch IN_PERF=true bash "$CHANGES"
  [ "$status" -eq 0 ]
  has_line "image=true"
  has_line "perf=true"
}

@test "śluza: PR i merge_group wymagają integracji bez etykiety (#149)" {
  for file in ansible/roles/storage/templates/60-resources.conf.j2 ansible/group_vars/all.yml \
    tests/sluza_resources.py tests/acceptance.sh ci/changes.sh; do
    repo_with_base "$file"
    for event in pull_request merge_group; do
      run env EVENT="$event" LABELS='[]' bash "$CHANGES"
      [ "$status" -eq 0 ]
      has_line "image=true"
    done
  done
}
