#!/usr/bin/env bats
# wlb-export.bats — testy jednostkowe operatorskiego CLI wlb-export (#20, interim).
#
# Testuje REALNY skrypt ansible/roles/storage/files/wlb-export na prawdziwej kolejce zbudowanej
# przez wlb-export-snapshot (E1). Pilnuje: inwariant read-only (list/show/verify nie dotykają
# kolejki), bezpieczeństwo (tylko request_id, nieznany -> błąd), stage kopiuje zweryfikowany
# payload, staged-clear sprząta, retencja ręczna (stage nie nadpisuje istniejącego staged).

load helpers.bash

CLI="$REPO_ROOT/ansible/roles/storage/files/wlb-export"
SNAP="$REPO_ROOT/ansible/roles/storage/files/wlb-export-snapshot"

setup() {
  setup_sandbox
  command -v python3 >/dev/null 2>&1 || skip "brak python3"
  QUEUE="$SANDBOX/queue"
  STAGING="$SANDBOX/staging"
  mkdir -p "$QUEUE"
  export WLB_EXPORT_QUEUE="$QUEUE" WLB_EXPORT_STAGING="$STAGING"
  export WLB_EXPORT_SNAPSHOT="$SNAP" WLB_EXPORT_ADMIN=root
  UUID=$(python3 -c 'import uuid; print(uuid.uuid4())')
  printf 'wynik-demo-123\n' >"$SANDBOX/wynik.csv"
  python3 "$SNAP" create "$SANDBOX/wynik.csv" "$QUEUE/20260101T000000Z_jupyter-u01_wynik.csv" wynik.csv "$UUID" >/dev/null
}

# suma drzewa kolejki — do inwariantu read-only
_queue_hash() {
  find "$QUEUE" -type f -exec sha256sum {} + 2>/dev/null | sort | sha256sum | cut -d' ' -f1
}

@test "wlb-export list: pokazuje wniosek z metadanymi (#20)" {
  run python3 "$CLI" list
  [ "$status" -eq 0 ]
  [[ "$output" == *"$UUID"* ]]
  [[ "$output" == *"pending_review"* ]]
}

@test "wlb-export list: wpis legacy (bez manifestu v1) oznaczony, nie ukryty (#20)" {
  mkdir -p "$QUEUE/20250101T000000Z_legacy"
  printf 'nie-manifest\n' >"$QUEUE/20250101T000000Z_legacy/manifest.json"
  run python3 "$CLI" list
  [ "$status" -eq 0 ]
  [[ "$output" == *"LEGACY"* ]]
}

@test "wlb-export show: zweryfikowany deskryptor po request_id, bez treści/nazw plików (#20)" {
  run python3 "$CLI" show "$UUID"
  [ "$status" -eq 0 ]
  [[ "$output" == *"manifest_sha256"* ]]
  [[ "$output" == *"$UUID"* ]]
  # resolve nie ujawnia TREŚCI payloadu ani listy wpisów (entries); ścieżka bundle zawiera nazwę
  # katalogu wniosku (nazewnictwo movera <ts>_<owner>_<nazwa>) — to widzi i tak operator (root).
  [[ "$output" != *"wynik-demo-123"* ]]
  [[ "$output" != *"entries"* ]]
}

@test "wlb-export verify: poprawny pakiet -> exit 0 (#20)" {
  run python3 "$CLI" verify "$UUID"
  [ "$status" -eq 0 ]
}

@test "wlb-export: nieznany request_id -> błąd niezerowy (fail-closed, #20)" {
  bad=$(python3 -c 'import uuid; print(uuid.uuid4())')
  run python3 "$CLI" show "$bad"
  [ "$status" -ne 0 ]
  run python3 "$CLI" stage "$bad"
  [ "$status" -ne 0 ]
}

@test "wlb-export: list/show/verify NIE modyfikują kolejki (inwariant read-only, #20)" {
  before=$(_queue_hash)
  python3 "$CLI" list >/dev/null
  python3 "$CLI" show "$UUID" >/dev/null
  python3 "$CLI" verify "$UUID" >/dev/null
  [ "$(_queue_hash)" = "$before" ]
}

@test "wlb-export stage: kopiuje zweryfikowany payload do staged, kolejka nietknięta (#20)" {
  before=$(_queue_hash)
  run python3 "$CLI" stage "$UUID"
  [ "$status" -eq 0 ]
  [ -e "$STAGING/$UUID/payload" ]
  # staged payload = oryginalna zawartość
  run cat "$STAGING/$UUID/payload"
  [[ "$output" == *"wynik-demo-123"* ]]
  # stage nie dotyka kolejki
  [ "$(_queue_hash)" = "$before" ]
}

@test "wlb-export stage: nie nadpisuje istniejącego staged (retencja ręczna, #20)" {
  python3 "$CLI" stage "$UUID" >/dev/null
  run python3 "$CLI" stage "$UUID"
  [ "$status" -ne 0 ]
  [[ "$output" == *"staged-clear"* ]]
}

@test "wlb-export staged-clear: usuwa staged pliki (#20)" {
  python3 "$CLI" stage "$UUID" >/dev/null
  [ -e "$STAGING/$UUID" ]
  run python3 "$CLI" staged-clear "$UUID"
  [ "$status" -eq 0 ]
  [ ! -e "$STAGING/$UUID" ]
}
