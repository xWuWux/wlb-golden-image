#!/usr/bin/env bash
# Decyduje, które kosztowne etapy (5–6) uruchomić; wypisuje linie klucz=wartość dla $GITHUB_OUTPUT.
#   EVENT    pull_request | push | workflow_dispatch | schedule
#   BASE     baza do porównania zmian: PR → base.sha gałęzi docelowej; push → event.before (poprzedni main)
#   LABELS   JSON z etykietami PR, np. ["perf","deploy-test","run-integration"]
#   IN_PERF, IN_EPHEMERAL   wejścia workflow_dispatch (true/false)
#   SCHEDULE wyrażenie cron, które wyzwoliło przebieg (github.event.schedule)
#
# Oszczędność minut CI (#86): ETAP 5 (budowa obrazu na KVM, ~22 min) NIE uruchamia się domyślnie na
# każdym PR — to była największa pozycja kosztu. Ciężką weryfikację robimy rzadziej lub lokalnie:
#   - na żądanie na PR: etykieta "run-integration" (albo "perf"/"deploy-test" — etap 6 potrzebuje obrazu),
#   - jako BRAMKA PO MERGE: push do main buduje obraz, chyba że scalono wyłącznie dokumentację,
#   - w nocnym pełnym buildzie (gdy włączony) oraz ręcznie (workflow_dispatch),
#   - lokalnie zawsze: `make ci` / ci/integration.sh (bez minut GitHuba).
# Jakość przed wejściem na main zachowana: bramka przesunięta z „każdy PR" na „po scaleniu do main".
set -euo pipefail
EVENT=${EVENT:-push}
LABELS=${LABELS:-[]}
SCHEDULE=${SCHEDULE:-}
BASE=${BASE:-}
# Nocny pełny build jest chwilowo WYŁĄCZONY (zakomentowany w on.schedule w ci.yml). Przy włączaniu
# ustaw tutaj dokładnie ten sam cron, który odkomentujesz w ci.yml (github.event.schedule zwraca napis crona).
NIGHTLY_CRON="0 3 * * 2,5"          # dopóki w ci.yml nie ma tego crona, ta gałąź nigdy się nie wyzwala
INTEGRATION_LABEL="run-integration" # etykieta PR wymuszająca etap 5 na żądanie

has_label() { python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.loads(sys.argv[1] or "[]") else 1)' "$LABELS" "$1"; }

# Prawda, gdy WSZYSTKIE pliki zmienione względem $1 to dokumentacja (brak wpływu na obraz).
# Pusta/zerowa baza (np. pierwszy push gałęzi) → nie filtrujemy, budujemy dla bezpieczeństwa.
doc_only() {
  local base=$1
  [[ -z $base || $base == 0000000000000000000000000000000000000000 ]] && return 1
  ! git diff --name-only "$base" HEAD | grep -qvE '^(README\.md|przewodnik-vm\.sh|docs/|\.github/dependabot\.yml$)'
}

# Etap 5: domyślnie NIE (oszczędność minut). Wyjątki wg zdarzenia poniżej.
image=false
case $EVENT in
  pull_request)
    # Tylko na żądanie: etykieta integracji lub etykiety etapu 6 (perf/deploy-test potrzebują obrazu).
    if has_label "$INTEGRATION_LABEL" || has_label perf || has_label deploy-test; then
      image=true
    fi
    ;;
  push)
    # Bramka po-merge na main: pełna integracja, chyba że scalono wyłącznie dokumentację.
    doc_only "$BASE" || image=true
    ;;
  schedule)
    # nocny pełny build: etapy 1–6 niezależnie od zakresu zmian (regresje spoza repo).
    # cotygodniowo (pon.): tylko etapy 1–4 (nowe CVE w lockach, zmiany licencji) → image=false.
    [[ $SCHEDULE == "$NIGHTLY_CRON" ]] && image=true
    ;;
  workflow_dispatch)
    image=true # ręczny pełny build (świadome uruchomienie)
    ;;
esac

perf=false
{ has_label perf || [[ ${IN_PERF:-false} == true ]]; } && perf=true
# nocny build obejmuje też benchmarki wydajności (wczesne wykrycie regresji wydajności)
[[ $EVENT == schedule && $SCHEDULE == "$NIGHTLY_CRON" ]] && perf=true
ephemeral=false
{ has_label deploy-test || [[ ${IN_EPHEMERAL:-false} == true ]]; } && ephemeral=true
# etap 6 potrzebuje obrazu z etapu 5
[[ $image == true ]] || perf=false ephemeral=false

echo "image=$image"
echo "perf=$perf"
echo "ephemeral=$ephemeral"
