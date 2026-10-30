#!/usr/bin/env bats
# Bramka tozsamosci SBOM (#129, recenzja #179): sbom.sh musi PADAC, nie ostrzegac,
# gdy brakuje dpkg-status albo para tozsamosci jest niezgodna. Atrapa osv-scannera
# tylko tworzy plik wyjscia — testujemy kompozycje, nie parser (to robi pytest).

load helpers

setup() {
  setup_sandbox
  ART="$BATS_TEST_TMPDIR/art"
  OUT="$BATS_TEST_TMPDIR/out/sbom.spdx.json"
  export HOST_OSR=/etc/os-release
  mkdir -p "$ART"
  printf '{"rev":1}\n' >"$ART/renv.lock"
  cat >"$STUBS/osv-scanner" <<'STUB'
#!/bin/sh
while [ "$#" -gt 0 ]; do
  [ "$1" = --output-file ] && printf '{"SPDXVersion":"2.3"}\n' >"$2"
  shift
done
exit 0
STUB
  chmod +x "$STUBS/osv-scanner"
}

write_art() { # dpkg-status + (os, wydanie)
  printf 'Package: acl\nVersion: 2.3.1\n\n' >"$ART/dpkg-status"
  printf 'ID=%s\nVERSION_ID=%s\n' "$1" "$2" >"$ART/os-release"
}

@test "SBOM bez dpkg-status pada, nie ostrzega (#129)" {
  printf 'ID=ubuntu\nVERSION_ID=24.04\n' >"$ART/os-release"
  run bash ci/sbom.sh "$ART" "$OUT"
  [ "$status" -ne 0 ]
  grep -q "niekompletny (#129)" <<<"$output"
}

@test "nieznane wydanie obrazu blokuje SBOM niezaleznie od hosta (#129)" {
  write_art ubuntu 26.04
  run bash ci/sbom.sh "$ART" "$OUT"
  [ "$status" -ne 0 ]
  grep -q "poza wspieranym" <<<"$output"
  [ ! -e "$OUT" ] # zablokowany SBOM nie powstaje
}

@test "obca dystrybucja z tym samym VERSION_ID odrzucona (#129)" {
  write_art debian 24.04
  run bash ci/sbom.sh "$ART" "$OUT"
  [ "$status" -ne 0 ]
  grep -q "poza wspieranym" <<<"$output"
}

@test "pelna zgodna para tozsamosci przechodzi do skanu (#129)" {
  host=$(awk -F= '/^VERSION_ID=/{gsub(/"/,"",$2); print $2}' "$HOST_OSR")
  [ "$host" = "24.04" ] || skip "sciezka szczesliwa wymaga hosta 24.04 (jest: $host)"
  write_art ubuntu 24.04
  run bash ci/sbom.sh "$ART" "$OUT"
  [ "$status" -eq 0 ]
  [ -s "$OUT" ]
}
