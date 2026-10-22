# shellcheck shell=bash
# Fragment akceptacji sklejany na hoście przez tests/acceptance.sh (po acceptance-remote.sh).
# Funkcje (expect_ok/expect_fail) i zmienne (R1, PW, QUEUE) pochodzą z prefiksu — nie definiuj ich tu.
echo "== Jedno jądro w obrazie (#9) =="
expect_ok "Dokładnie jedno /boot/vmlinuz-*" test "$(find /boot -maxdepth 1 -name 'vmlinuz-*' | wc -l)" -eq 1
expect_ok "Jeden katalog modułów w /lib/modules" test "$(find /lib/modules -mindepth 1 -maxdepth 1 -type d | wc -l)" -eq 1
expect_ok "Katalog modułów = uruchomione jądro" test -d "/lib/modules/$(uname -r)"
