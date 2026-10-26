#!/usr/bin/env bats
# Testy jednostkowe śluzy wyjściowej (tryb --once) w piaskownicy.

load helpers

setup() {
  setup_sandbox
  export WLB_SLUZA_OUT="$SANDBOX/sluza-out" WLB_EXPORT_QUEUE="$SANDBOX/queue"
  export WLB_IMAGE_CONF="$SANDBOX/etc/wlb/image.conf" # nie istnieje -> wartości z env
  mkdir -p "$WLB_SLUZA_OUT"
  stub logger
  stub chown
  stub fuser 1 # domyślnie: plik nie jest otwarty
  ME=$(id -un)
}

@test "plik trafia do kolejki i znika ze śluzy" {
  echo "wynik" >"$WLB_SLUZA_OUT/wynik.csv"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ ! -e "$WLB_SLUZA_OUT/wynik.csv" ]
  queued=$(ls "$WLB_EXPORT_QUEUE")
  [[ $queued =~ ^[0-9]{8}T[0-9]{6}Z_${ME}_wynik\.csv$ ]]
  [ "$(stat -c %a "$WLB_EXPORT_QUEUE/$queued/payload")" = 600 ]
  [ "$(stat -c %a "$WLB_EXPORT_QUEUE")" = 700 ]
}

@test "przeniesienie jest logowane z badaczem i sumą SHA-256" {
  echo "wynik" >"$WLB_SLUZA_OUT/wynik.csv"
  sha=$(sha256sum "$WLB_SLUZA_OUT/wynik.csv" | cut -d' ' -f1)
  "$MOVER" --once
  calls | grep -q "logger -t wlb-sluza-out -p authpriv.notice -- export_request user=$ME uid=$(id -u) entry=wynik.csv sha256=$sha queued_as="
  [ -f "$WLB_EXPORT_QUEUE/$(ls "$WLB_EXPORT_QUEUE")/manifest.json" ]
}

@test "plik otwarty do zapisu czeka na zamknięcie" {
  echo "w trakcie" >"$WLB_SLUZA_OUT/duzy.csv"
  stub fuser 0
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -e "$WLB_SLUZA_OUT/duzy.csv" ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
}

@test "pliki tymczasowe/ukryte są pomijane do zmiany nazwy (#33)" {
  echo x >"$WLB_SLUZA_OUT/.ukryty"
  echo x >"$WLB_SLUZA_OUT/wynik.tmp"
  echo x >"$WLB_SLUZA_OUT/wynik.part"
  echo x >"$WLB_SLUZA_OUT/wynik~"
  "$MOVER" --once
  # zostają w śluzie, nie trafiają do kolejki
  [ -e "$WLB_SLUZA_OUT/.ukryty" ]
  [ -e "$WLB_SLUZA_OUT/wynik.tmp" ]
  [ -e "$WLB_SLUZA_OUT/wynik.part" ]
  [ -e "$WLB_SLUZA_OUT/wynik~" ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
  refute called "export_request"
}

@test "plik tymczasowy po zmianie nazwy na docelową trafia do kolejki (#33)" {
  echo "dane" >"$WLB_SLUZA_OUT/.wynik.csv.ABC123" # zapis atomowy: najpierw nazwa tymczasowa
  "$MOVER" --once
  [ -e "$WLB_SLUZA_OUT/.wynik.csv.ABC123" ] # pominięty, czeka
  mv "$WLB_SLUZA_OUT/.wynik.csv.ABC123" "$WLB_SLUZA_OUT/wynik.csv" # zmiana nazwy na docelową
  "$MOVER" --once
  [ ! -e "$WLB_SLUZA_OUT/wynik.csv" ] # teraz wyeksportowany
  compgen -G "$WLB_EXPORT_QUEUE/*_wynik.csv" >/dev/null
}

@test "dowiązanie symboliczne jest odrzucane i usuwane" {
  echo tajne >"$BATS_TEST_TMPDIR/cel"
  ln -s "$BATS_TEST_TMPDIR/cel" "$WLB_SLUZA_OUT/link"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ ! -L "$WLB_SLUZA_OUT/link" ]
  [ -e "$BATS_TEST_TMPDIR/cel" ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
  calls | grep -q "rejected user=$ME entry=link reason=unsupported_type"
}

@test "świeży katalog czeka, aż przestanie się zmieniać" {
  mkdir "$WLB_SLUZA_OUT/wyniki"
  echo a >"$WLB_SLUZA_OUT/wyniki/a.csv"
  "$MOVER" --once
  [ -d "$WLB_SLUZA_OUT/wyniki" ]
}

@test "ustabilizowany katalog trafia do kolejki z sumą zawartości" {
  mkdir "$WLB_SLUZA_OUT/wyniki"
  echo a >"$WLB_SLUZA_OUT/wyniki/a.csv"
  echo b >"$WLB_SLUZA_OUT/wyniki/b.csv"
  touch -d '10 minutes ago' "$WLB_SLUZA_OUT/wyniki" "$WLB_SLUZA_OUT/wyniki/"*
  "$MOVER" --once
  [ ! -e "$WLB_SLUZA_OUT/wyniki" ]
  queued=$(ls "$WLB_EXPORT_QUEUE")
  [ -f "$WLB_EXPORT_QUEUE/$queued/payload/a.csv" ]
  calls | grep -Eq "entry=wyniki sha256=[0-9a-f]{64} "
}

@test "pusta śluza — nic się nie dzieje" {
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
  [ ! -s "$CALLS" ]
}

@test "ścieżki z image.conf mają pierwszeństwo przed domyślnymi" {
  mkdir -p "$SANDBOX/inna-sluza"
  printf 'WLB_SLUZA_OUT=%s\nWLB_EXPORT_QUEUE=%s\n' "$SANDBOX/inna-sluza" "$SANDBOX/inna-kolejka" >"$WLB_IMAGE_CONF"
  unset WLB_SLUZA_OUT WLB_EXPORT_QUEUE
  echo x >"$SANDBOX/inna-sluza/plik"
  "$MOVER" --once
  [ -n "$(ls "$SANDBOX/inna-kolejka")" ]
}

# --- #29: podmiana wpisu między sprawdzeniem a przeniesieniem (TOCTOU) --------------------

# swap_on_fuser CEL — atrapa fuser, która (jak badacz w pętli) podmienia sprawdzany plik
# na dowiązanie do CELU dokładnie między sprawdzeniem typu a przeniesieniem
swap_on_fuser() {
  cat >"$STUBS/fuser" <<EOF
#!/usr/bin/env bash
echo "fuser \$*" >>"\$CALLS"
f=\${!#}
rm -f -- "\$f" && ln -s "$1" "\$f"
exit 1
EOF
  chmod +x "$STUBS/fuser"
}

@test "#29: plik podmieniony na dowiązanie po sprawdzeniu — cel nietknięty, kolejka pusta" {
  unstub_chown
  echo tajne >"$BATS_TEST_TMPDIR/cel"
  chmod 644 "$BATS_TEST_TMPDIR/cel"
  echo wynik >"$WLB_SLUZA_OUT/wynik.csv"
  swap_on_fuser "$BATS_TEST_TMPDIR/cel"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ "$(stat -c %a "$BATS_TEST_TMPDIR/cel")" = 644 ]
  [ "$(cat "$BATS_TEST_TMPDIR/cel")" = tajne ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
  [ ! -e "$WLB_SLUZA_OUT/wynik.csv" ] && [ ! -L "$WLB_SLUZA_OUT/wynik.csv" ]
  calls | grep -q "snapshot_failed .*reason=snapshot_error"
  compgen -G "$WLB_EXPORT_QUEUE/.incoming.*/source" >/dev/null
  refute called "export_request"
}

@test "#20: niedozwolony element zatrzymuje cały katalog w kwarantannie" {
  mkdir -p "$WLB_SLUZA_OUT/wyniki/pod"
  echo a >"$WLB_SLUZA_OUT/wyniki/a.csv"
  ln -s /etc/passwd "$WLB_SLUZA_OUT/wyniki/pod/link"
  WLB_DIR_SETTLE_SECONDS=0 run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
  compgen -G "$WLB_EXPORT_QUEUE/.incoming.*/source/a.csv" >/dev/null
  calls | grep -q "snapshot_failed .*reason=snapshot_error"
  refute called "export_request"
}

@test "#29: plik z drugim dowiązaniem twardym jest odrzucany, oryginał badacza zostaje" {
  echo wynik >"$BATS_TEST_TMPDIR/oryginal"
  ln "$BATS_TEST_TMPDIR/oryginal" "$WLB_SLUZA_OUT/wynik.csv"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
  [ "$(cat "$BATS_TEST_TMPDIR/oryginal")" = wynik ]
  calls | grep -q "snapshot_failed .*reason=snapshot_error"
}

@test "#29: wpis usunięty przez badacza w trakcie przeglądu nie zatrzymuje usługi" {
  echo wynik >"$WLB_SLUZA_OUT/wynik.csv"
  cat >"$STUBS/fuser" <<'EOF'
#!/usr/bin/env bash
rm -f -- "${!#}"
exit 1
EOF
  chmod +x "$STUBS/fuser"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -z "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name .mover.lock)" ]
  refute called "export_request"
}

@test "#29: dwa wpisy o tej samej nazwie w tej samej sekundzie nie nadpisują się" {
  stub date 0 20260928T120000Z
  echo pierwszy >"$WLB_SLUZA_OUT/wynik.csv"
  "$MOVER" --once
  echo drugi >"$WLB_SLUZA_OUT/wynik.csv"
  "$MOVER" --once
  [ "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 -maxdepth 1 ! -name '.*' | wc -l)" -eq 2 ]
  [ "$(cat "$WLB_EXPORT_QUEUE"/*/payload | sort | tr '\n' ' ')" = "drugi pierwszy " ]
}

@test "#20: suma katalogu odtwarzalna przez weryfikator po przeniesieniu pakietu" {
  mkdir -p "$WLB_SLUZA_OUT/wyniki/pod"
  echo a >"$WLB_SLUZA_OUT/wyniki/a.csv"
  echo b >"$WLB_SLUZA_OUT/wyniki/pod/b.csv"
  WLB_DIR_SETTLE_SECONDS=0 "$MOVER" --once
  queued=$WLB_EXPORT_QUEUE/$(ls "$WLB_EXPORT_QUEUE")
  mv "$queued" "$BATS_TEST_TMPDIR/relocated"
  expected=$("${MOVER%/*}/wlb-export-snapshot" verify "$BATS_TEST_TMPDIR/relocated")
  calls | grep -q "entry=wyniki sha256=$expected "
}
