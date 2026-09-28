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
  [ "$(stat -c %a "$WLB_EXPORT_QUEUE/$queued")" = 600 ]
  [ "$(stat -c %a "$WLB_EXPORT_QUEUE")" = 700 ]
}

@test "przeniesienie jest logowane z badaczem i sumą SHA-256" {
  echo "wynik" >"$WLB_SLUZA_OUT/wynik.csv"
  sha=$(sha256sum "$WLB_SLUZA_OUT/wynik.csv" | cut -d' ' -f1)
  "$MOVER" --once
  calls | grep -q "logger -t wlb-sluza-out -p authpriv.notice -- export_request user=$ME uid=$(id -u) entry=wynik.csv sha256=$sha queued_as="
  calls | grep -q "chown -hR root:root -- $WLB_EXPORT_QUEUE/"
}

@test "plik otwarty do zapisu czeka na zamknięcie" {
  echo "w trakcie" >"$WLB_SLUZA_OUT/duzy.csv"
  stub fuser 0
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -e "$WLB_SLUZA_OUT/duzy.csv" ]
  [ -z "$(ls -A "$WLB_EXPORT_QUEUE")" ]
}

@test "pliki ukryte też są eksportowane" {
  echo x >"$WLB_SLUZA_OUT/.ukryty"
  "$MOVER" --once
  [ ! -e "$WLB_SLUZA_OUT/.ukryty" ]
  compgen -G "$WLB_EXPORT_QUEUE/*_.ukryty" >/dev/null
}

@test "dowiązanie symboliczne jest odrzucane i usuwane" {
  echo tajne >"$BATS_TEST_TMPDIR/cel"
  ln -s "$BATS_TEST_TMPDIR/cel" "$WLB_SLUZA_OUT/link"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ ! -L "$WLB_SLUZA_OUT/link" ]
  [ -e "$BATS_TEST_TMPDIR/cel" ]
  [ -z "$(ls -A "$WLB_EXPORT_QUEUE")" ]
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
  [ -f "$WLB_EXPORT_QUEUE/$queued/a.csv" ]
  calls | grep -Eq "entry=wyniki sha256=[0-9a-f]{64} "
}

@test "pusta śluza — nic się nie dzieje" {
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -z "$(ls -A "$WLB_EXPORT_QUEUE")" ]
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
  [ -z "$(ls -A "$WLB_EXPORT_QUEUE")" ]
  [ ! -e "$WLB_SLUZA_OUT/wynik.csv" ] && [ ! -L "$WLB_SLUZA_OUT/wynik.csv" ]
  calls | grep -q "rejected user=$ME entry=wynik.csv reason=unsupported_type"
  refute called "export_request"
}

@test "#29: dowiązania i pliki specjalne wewnątrz katalogu są usuwane, reszta eksportowana" {
  unstub_chown
  echo tajne >"$BATS_TEST_TMPDIR/cel"
  chmod 644 "$BATS_TEST_TMPDIR/cel"
  mkdir -p "$WLB_SLUZA_OUT/wyniki/pod"
  echo a >"$WLB_SLUZA_OUT/wyniki/a.csv"
  ln -s "$BATS_TEST_TMPDIR/cel" "$WLB_SLUZA_OUT/wyniki/pod/link"
  mkfifo "$WLB_SLUZA_OUT/wyniki/fifo"
  touch -h -d '10 minutes ago' "$WLB_SLUZA_OUT/wyniki" "$WLB_SLUZA_OUT/wyniki/"* "$WLB_SLUZA_OUT/wyniki/pod/"*
  touch -d '10 minutes ago' "$WLB_SLUZA_OUT/wyniki/pod"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  queued=$WLB_EXPORT_QUEUE/$(ls "$WLB_EXPORT_QUEUE")
  [ -f "$queued/a.csv" ]
  [ -z "$(find "$queued" ! -type f ! -type d)" ]
  [ "$(stat -c %a "$BATS_TEST_TMPDIR/cel")" = 644 ]
  calls | grep -q "rejected user=$ME entry=wyniki/pod/link reason=unsupported_type"
  calls | grep -q "rejected user=$ME entry=wyniki/fifo reason=unsupported_type"
  calls | grep -Eq "export_request user=$ME .*entry=wyniki sha256=[0-9a-f]{64} "
}

@test "#29: plik z drugim dowiązaniem twardym jest odrzucany, oryginał badacza zostaje" {
  echo wynik >"$BATS_TEST_TMPDIR/oryginal"
  ln "$BATS_TEST_TMPDIR/oryginal" "$WLB_SLUZA_OUT/wynik.csv"
  run "$MOVER" --once
  [ "$status" -eq 0 ]
  [ -z "$(ls -A "$WLB_EXPORT_QUEUE")" ]
  [ "$(cat "$BATS_TEST_TMPDIR/oryginal")" = wynik ]
  calls | grep -q "rejected user=$ME entry=wynik.csv reason=hardlink"
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
  [ -z "$(ls -A "$WLB_EXPORT_QUEUE")" ]
  refute called "export_request"
}

@test "#29: dwa wpisy o tej samej nazwie w tej samej sekundzie nie nadpisują się" {
  stub date 0 20260928T120000Z
  echo pierwszy >"$WLB_SLUZA_OUT/wynik.csv"
  "$MOVER" --once
  echo drugi >"$WLB_SLUZA_OUT/wynik.csv"
  "$MOVER" --once
  [ "$(find "$WLB_EXPORT_QUEUE" -mindepth 1 | wc -l)" -eq 2 ]
  [ "$(cat "$WLB_EXPORT_QUEUE"/* | sort | tr '\n' ' ')" = "drugi pierwszy " ]
}
