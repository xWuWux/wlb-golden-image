# shellcheck shell=bash
# Wspólna asercja negatywna targetu E2E pulpitu (#277).
#
# Kontrakt ścieżek jest w ci/e2e-fixture-paths.txt — tym samym pliku, który czyta
# bramka wydania (ci/e2e_release_gate.py). tests/acceptance.sh wstrzykuje go do
# skryptu VM jako WLB_E2E_FIXTURE_PATHS. Funkcja jest testowana bezpośrednio
# (tests/unit/test_e2e_negative_acceptance.py), więc testy nie kopiują logiki asercji.

# assert_no_e2e_fixture [ROOT] — sprawdza, że żadna ścieżka kontraktu nie istnieje
# pod ROOT (domyślnie /). Zwraca 1, gdy expect_ok zgłosił FAIL; w akceptacji i tak
# decyduje końcowe summary, ale test jednostkowy potrzebuje jednoznacznego kodu.
assert_no_e2e_fixture() {
  local root=${1:-/}
  local before=${FAIL:-0}
  local path
  local -a paths=("${WLB_E2E_FIXTURE_PATHS[@]:-}")
  # ${arr[@]:-} zwraca jeden pusty element dla pustej tablicy — odfiltruj go jawnie,
  # żeby pusty kontrakt był błędem, a nie asercją „/ nie istnieje”.
  if ((${#paths[@]} == 1)) && [[ -z ${paths[0]} ]]; then
    paths=()
  fi
  if ((${#paths[@]} == 0)); then
    echo "BŁĄD: pusty kontrakt ścieżek E2E (#277)" >&2
    return 1
  fi
  for path in "${paths[@]}"; do
    expect_ok "Brak targetu E2E: ${path} nie istnieje w obrazie nie-E2E (#277)" \
      test ! -e "${root%/}${path}"
  done
  ((FAIL == before))
}
