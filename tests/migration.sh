#!/usr/bin/env bash
# Test migracji: nowa VM (nowa wersja obrazu albo odtworzenie po awarii) na istniejącym
# dysku roboczym. Dysk systemowy jest jednorazowy — konta w hubie, UID badaczy
# i ich pliki muszą przetrwać wymianę.
#
#   tests/migration.sh OBRAZ_ŹRÓDŁOWY [OBRAZ_DOCELOWY]   # domyślnie ten sam obraz
set -euo pipefail
# shellcheck source=tests/lib/local-common.sh
. "$(dirname "$0")/lib/local-common.sh"

ROLLBACK=0
positional=()
for a in "$@"; do
  case $a in
    --rollback) ROLLBACK=1 ;;
    *) positional+=("$a") ;;
  esac
done
FROM=${positional[0]:?podaj obraz źródłowy (.qcow2)}
TO=${positional[1]:-$FROM}

echo "== Migracja: $(basename "$FROM") -> $(basename "$TO") =="
"$ROOT/tests/stop-local.sh" >/dev/null
KEEP_WORKSPACE=0 "$ROOT/tests/run-local.sh" "$FROM" >/dev/null

echo "-- VM źródłowa: konto badacza i dane w katalogu domowym"
read -r uid password admin_password < <(remote_run "$ROOT/tests/migration-remote.sh" prepare)
[[ -n ${admin_password:-} ]] || {
  echo "Przygotowanie VM źródłowej nie powiodło się"
  exit 1
}
echo "   jupyter-migrant UID=$uid"

echo "-- Wymiana dysku systemowego (dysk roboczy zostaje)"
KEEP_WORKSPACE=1 "$ROOT/tests/stop-local.sh" >/dev/null
KEEP_WORKSPACE=1 "$ROOT/tests/run-local.sh" "$TO" >/dev/null

echo "-- VM docelowa"
status=0
remote_run "$ROOT/tests/migration-remote.sh" verify "$uid" "$password" "$admin_password" || status=$?

# Wycofanie (RB-05, DoD #106/#62): przywróć bazę sprzed migracji i wróć na stary obraz.
# Pełny test schematu wymaga FROM i TO o różnych wersjach JupyterHub; przy tym samym obrazie
# sprawdza samą mechanikę przywrócenia i startu starego obrazu na dysku roboczym.
if [[ $ROLLBACK == 1 ]]; then
  echo "-- Wycofanie: przywrócenie bazy sprzed migracji (pre-<wersja>)"
  remote_run "$ROOT/tests/migration-remote.sh" rollback-prepare || status=$?
  echo "-- Powrót na stary obraz (dysk roboczy zostaje)"
  KEEP_WORKSPACE=1 "$ROOT/tests/stop-local.sh" >/dev/null
  KEEP_WORKSPACE=1 "$ROOT/tests/run-local.sh" "$FROM" >/dev/null
  echo "-- VM po wycofaniu"
  remote_run "$ROOT/tests/migration-remote.sh" verify "$uid" "$password" "$admin_password" || status=$?
fi

"$ROOT/tests/stop-local.sh" >/dev/null
exit $status
