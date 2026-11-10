#!/usr/bin/env bats
# Testy jednostkowe wlb-apparmor-enforce (#65, CIS 1.6.3): sweep complain→enforce w warstwie pulpitu.
# Atrapy aa-status / aa-enforce / apparmor_parser odwzorowują stan z plików profili (jak jądro po
# aa-enforce), więc licznik przed/po jest spójny z tym, co robi skrypt.

load helpers

ENFORCE="$REPO_ROOT/ansible/roles/desktop/files/wlb-apparmor-enforce"

setup() {
  setup_sandbox
  APPARMOR_D="$BATS_TEST_TMPDIR/apparmor.d"
  mkdir -p "$APPARMOR_D"
  export WLB_APPARMOR_D="$APPARMOR_D"

  # aa-status: licznik i JSON wyprowadzane z plików profili (po aa-enforce plik traci flags=(complain)).
  cat >"$STUBS/aa-status" <<EOF
#!/usr/bin/env bash
echo "aa-status \$*" >>"\$CALLS"
case "\$1" in
  --complaining)
    n=0
    for f in "$APPARMOR_D"/*; do
      [[ -f \$f ]] || continue
      grep -q 'flags=(complain' "\$f" && n=\$((n + 1))
    done
    echo "\$n"
    ;;
  --json)
    printf '{"profiles": {'
    first=1
    for f in "$APPARMOR_D"/*; do
      [[ -f \$f ]] || continue
      grep -q 'flags=(complain' "\$f" || continue
      name=\$(grep -oE '^profile [^ ]+' "\$f" | head -1 | cut -d' ' -f2)
      [[ -n \$name ]] || continue
      ((first)) || printf ', '
      printf '"%s": "complain"' "\$name"
      first=0
    done
    printf '}}'
    ;;
esac
EOF
  chmod +x "$STUBS/aa-status"

  # aa-enforce: zdejmuje flags=(complain) z pliku profilu — tak działa prawdziwe aa-enforce.
  cat >"$STUBS/aa-enforce" <<'EOF'
#!/usr/bin/env bash
echo "aa-enforce $*" >>"$CALLS"
sed -i 's/ flags=(complain)//' "$1"
EOF
  chmod +x "$STUBS/aa-enforce"

  # apparmor_parser -N: nazwy profili zdefiniowanych w pliku.
  cat >"$STUBS/apparmor_parser" <<'EOF'
#!/usr/bin/env bash
echo "apparmor_parser $*" >>"$CALLS"
[[ $1 == -N ]] && grep -oE '^profile [^ ]+' "$2" | cut -d' ' -f2
EOF
  chmod +x "$STUBS/apparmor_parser"
}

profile_file() { # profile_file NAZWA [SUFIKS] — plik profilu w complain
  printf 'profile %s flags=(complain) {\n}\n' "$1" >"$APPARMOR_D/$1"
}

@test "brak profili w complain -> WLB_SWITCHED=0, bez aa-enforce" {
  run "$ENFORCE"
  [ "$status" -eq 0 ]
  [[ $output == *"aa-status --complaining=0"* ]]
  [[ $output == *"WLB_SWITCHED=0"* ]]
  refute called aa-enforce
}

@test "dwa profile w complain -> przełączone na enforce, WLB_SWITCHED=1" {
  profile_file test-a
  profile_file test-b
  run "$ENFORCE"
  [ "$status" -eq 0 ]
  [[ $output == *"WLB_SWITCHED=1"* ]]
  [[ $output == *"before=2 after=0"* ]]
  refute grep -q 'flags=(complain' "$APPARMOR_D/test-a"
  refute grep -q 'flags=(complain' "$APPARMOR_D/test-b"
  called aa-enforce
}

@test "drugi przebieg jest idempotentny -> WLB_SWITCHED=0" {
  profile_file test-a
  run "$ENFORCE"
  [ "$status" -eq 0 ]
  [[ $output == *"WLB_SWITCHED=1"* ]]
  run "$ENFORCE"
  [ "$status" -eq 0 ]
  [[ $output == *"WLB_SWITCHED=0"* ]]
}

@test "aa-status --complaining zwraca śmieci -> błąd (nie zgadujemy stanu)" {
  cat >"$STUBS/aa-status" <<'EOF'
#!/usr/bin/env bash
echo "aa-status $*" >>"$CALLS"
echo 'nie-liczba'
EOF
  chmod +x "$STUBS/aa-status"
  run "$ENFORCE"
  [ "$status" -eq 1 ]
  [[ $output == *"nie-liczba"* ]]
}

@test "licznik > 0, ale JSON bez nazw profili -> błąd (fail-secure)" {
  # Plik ma flags=(complain), ale nie definiuje profilu przez `profile NAZWA` — JSON nie zna nazwy.
  printf '/usr/bin/x flags=(complain) {\n}\n' >"$APPARMOR_D/x"
  run "$ENFORCE"
  [ "$status" -eq 1 ]
  [[ $output == *"nie zwróciło nazw"* ]]
}

@test "aa-enforce nie zdejmuje complain -> błąd po liczniku (fail-secure)" {
  profile_file test-a
  cat >"$STUBS/aa-enforce" <<'EOF'
#!/usr/bin/env bash
echo "aa-enforce $*" >>"$CALLS"
EOF
  chmod +x "$STUBS/aa-enforce"
  run "$ENFORCE"
  [ "$status" -eq 1 ]
  [[ $output == *"nadal 1 profili w trybie complain"* ]]
}

@test "profil w complain bez pliku do przełączenia -> błąd po liczniku (fail-secure)" {
  # JSON zgłasza profil (np. ładowany spoza /etc/apparmor.d), ale żaden plik nie pasuje.
  cat >"$STUBS/aa-status" <<'EOF'
#!/usr/bin/env bash
echo "aa-status $*" >>"$CALLS"
case "$1" in
  --complaining) echo 1 ;;
  --json) echo '{"profiles": {"test-a": "complain"}}' ;;
esac
EOF
  chmod +x "$STUBS/aa-status"
  run "$ENFORCE"
  [ "$status" -eq 1 ]
  [[ $output == *"nadal 1 profili w trybie complain"* ]]
  refute called aa-enforce
}
