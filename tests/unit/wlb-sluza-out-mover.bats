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
  calls | grep -q "chown -R root:root -- $WLB_EXPORT_QUEUE/"
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
