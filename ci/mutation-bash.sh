#!/usr/bin/env bash
# Harness mutacji powłoki dla stage 4b (blokujący).
#
# Każdy wiersz tabeli to jedna celowa, minimalna zmiana w skrypcie obrazu. Odpowiadający test bats
# MUSI ją zabić (test czerwony). Jeśli test przechodzi mimo mutacji → „survived” → błąd CI, bo
# znaczy to, że test nie sprawdza tego, co deklaruje.
#
# Tabela: ci/mutations/bash-mutations.tsv — kolumny rozdzielone TAB:
#   plik <TAB> fragment_przed <TAB> fragment_po <TAB> plik_testu <TAB> filtr_testu <TAB> opis
# Filtr (bats -f) ogranicza przebieg do potrzebnych testów; pusty = cały plik testów.
#
# --check: tylko walidacja tabeli (każdy fragment_przed występuje dokładnie raz, pliki istnieją).
#           Używane przez tests/unit/mutation-bash.bats — nie mutuje niczego.
#
# Zmienne dla testów harnessu: MUTATION_REPO_ROOT (drzewo do skopiowania), MUTATION_TABLE.
set -euo pipefail

SELF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=${MUTATION_REPO_ROOT:-$(cd "$SELF_DIR/.." && pwd)}
TABLE=${MUTATION_TABLE:-$REPO_ROOT/ci/mutations/bash-mutations.tsv}
OUTPUT=""
CHECK_ONLY=0
while (($#)); do
  case $1 in
    --check) CHECK_ONLY=1 ;;
    --output)
      OUTPUT=${2:?--output wymaga ścieżki}
      shift
      ;;
    *)
      echo "BŁĄD: nieznany argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

[[ -r $TABLE ]] || {
  echo "BŁĄD: brak tabeli mutacji $TABLE" >&2
  exit 1
}
mapfile -t ROWS < <(grep -vE '^[[:space:]]*(#|$)' "$TABLE")
((${#ROWS[@]})) || {
  echo "BŁĄD: tabela mutacji jest pusta ($TABLE)" >&2
  exit 1
}

count_occurrences() { # count_occurrences PLIK FRAGMENT — liczba wystąpień fragmentu
  python3 - "$1" "$2" <<'PY'
import sys

text = open(sys.argv[1], encoding="utf-8").read()
print(text.count(sys.argv[2]))
PY
}

apply_mutation() { # apply_mutation PLIK PRZED PO — podmienia dokładnie jedno wystąpienie
  python3 - "$1" "$2" "$3" <<'PY'
import sys

path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path, encoding="utf-8").read()
if text.count(old) != 1:
    raise SystemExit(f"fragment niejednoznaczny w {path} ({text.count(old)} wystąpień)")
open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
PY
}

# Walidacja tabeli: niejednoznaczny fragment albo brak pliku = błąd, bo mutacja przestałaby
# cokolwiek sprawdzać (kod się zmienił, a tabela nie).
errors=0
for row in "${ROWS[@]}"; do
  IFS=$'\t' read -r file old new test filter desc <<<"$row"
  # "-" = cały plik testów (pole nie może być puste: read z IFS=TAB zwija kolejne separatory)
  if [[ $filter == - ]]; then filter=""; fi
  for field in file old new test desc; do
    [[ -n ${!field} ]] || {
      echo "BŁĄD: pusty wymagany element wiersza ($field): $row" >&2
      errors=1
    }
  done
  [[ -f $REPO_ROOT/$file ]] || {
    echo "BŁĄD: brak pliku $file ($desc)" >&2
    errors=1
    continue
  }
  [[ -f $REPO_ROOT/$test ]] || {
    echo "BŁĄD: brak testu $test ($desc)" >&2
    errors=1
    continue
  }
  n=$(count_occurrences "$REPO_ROOT/$file" "$old")
  [[ $n == 1 ]] || {
    echo "BŁĄD: fragment do mutacji występuje $n razy w $file (oczekiwano 1): $desc" >&2
    errors=1
  }
done
((errors == 0)) || exit 1

if ((CHECK_ONLY)); then
  echo "OK: ${#ROWS[@]} mutacji, każdy fragment występuje dokładnie raz"
  exit 0
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
# Kopia drzewa bez artefaktów: testy bats liczą REPO_ROOT z położenia pliku testu, więc mutacja
# musi leżeć w kopii razem z testami, a nie w drzewie roboczym.
tar -cf - -C "$REPO_ROOT" \
  --exclude=.git --exclude=.tools --exclude=build --exclude=output \
  --exclude=mutants --exclude=.mutmut-cache --exclude=packer_cache \
  . | tar -xf - -C "$WORK"

killed=0
survived=0
report=$(
  echo "### Mutacje powłoki (harness tabelaryczny)"
  echo
  echo "| Mutacja | Plik | Test | Wynik |"
  echo "|---|---|---|---|"
)
for row in "${ROWS[@]}"; do
  IFS=$'\t' read -r file old new test filter desc <<<"$row"
  if [[ $filter == - ]]; then filter=""; fi
  apply_mutation "$WORK/$file" "$old" "$new"
  bats_args=("$WORK/$test")
  [[ -z $filter ]] || bats_args=(-f "$filter" "$WORK/$test")
  if bats "${bats_args[@]}" >"$WORK/bats.log" 2>&1; then
    result="**survived**"
    survived=$((survived + 1))
    echo "PRZEŻYŁ: $desc (mutacja: $old → $new)" >&2
    tail -n 5 "$WORK/bats.log" >&2
  else
    result="killed"
    killed=$((killed + 1))
  fi
  # Filtr, który nie wybrał żadnego testu, dawałby fałszywe „killed” — sprawdzamy liczbę testów.
  ran=$(sed -n 's/^1\.\.\([0-9]*\).*/\1/p' "$WORK/bats.log" | head -1)
  if [[ -z $ran || $ran == 0 ]]; then
    echo "BŁĄD: filtr '$filter' nie wybrał żadnego testu ($desc)" >&2
    errors=1
  fi
  report+=$'\n'"| $desc | \`$file\` | \`$test\`${filter:+ (-f \`$filter\`)} | $result |"
  cp "$REPO_ROOT/$file" "$WORK/$file" # przywrócenie przed kolejną mutacją
done
report+=$'\n\n'"Zabite: **$killed**, przeżyły: **$survived**."$'\n'
if [[ -n $OUTPUT ]]; then
  printf '%s\n' "$report" >"$OUTPUT"
else
  printf '%s\n' "$report"
fi
((survived == 0 && errors == 0)) || exit 1
echo "OK: wszystkie $killed mutacji zabite"
