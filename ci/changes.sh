#!/usr/bin/env bash
# Decyduje, które kosztowne etapy (5–6) uruchomić; wypisuje linie klucz=wartość dla $GITHUB_OUTPUT.
#   EVENT    pull_request | merge_group | push | workflow_dispatch | schedule
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
# Zmiany sieci/utwardzenia i ich harnessu wymagają etapu 5 PRZED merge (#63, #16).
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

# network_change BASE: kod 0 oznacza wymaganą integrację. Brak bazy/błąd git
# wymusza walidację; nie pozwalamy uzyskać zielonej bramki przez błąd klasyfikacji.
network_change() {
  local changed
  [[ -n $1 ]] || return 0
  changed=$(git diff --name-only "$1" HEAD) || return 0
  grep -qE '^(ansible/roles/(base|lab_config|tljh)/|cloud-init/|tests/(acceptance|cloud-init/|lib/|proxy_sink\.py)|ci/(changes|integration|ready)\.sh$|\.github/workflows/ci\.yml$)' <<<"$changed"
}

# #149: limity śluzy i ich testy wymagają rzeczywistego jądra przed merge.
storage_change() {
  local changed
  [[ -n $BASE ]] || return 0
  changed=$(git diff --name-only "$BASE" HEAD) || return 0
  grep -qE '^(ansible/roles/storage/|ansible/group_vars/all\.yml$|tests/(sluza_resources\.py|acceptance\.sh|acceptance\.d/80-sluza)|ci/changes\.sh$)' <<<"$changed"
}

# #135: zmiana flavora wlb-radiologia (neuro_apps/desktop, radiologia.yml/packer, testy flavora)
# wymaga przebudowy i testu flavora na realnym jądrze — bug instalatora FSL łapie tylko build.
radiologia_change() {
  local changed
  [[ -n $1 ]] || return 0
  changed=$(git diff --name-only "$1" HEAD) || return 0
  grep -qE '^(ansible/roles/(neuro_apps|desktop)/|ansible/radiologia\.yml$|packer/wlb-radiologia\.pkr\.hcl$|tests/acceptance\.d/(40-pulpit|70-radiologia)\.sh$)' <<<"$changed"
}

# Etap 5: domyślnie NIE (oszczędność minut). Wyjątki wg zdarzenia poniżej.
image=false
case $EVENT in
  pull_request | merge_group)
    # Sieć/utwardzenie (#63/#16) oraz limity śluzy (#149) zawsze; pozostałe zmiany na etykietę (#86).
    if network_change "$BASE" || storage_change || has_label "$INTEGRATION_LABEL" || has_label perf || has_label deploy-test; then
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

# Radiologia (flavor neuro): opt-in etykietą build-radiologia albo zmiana plików flavora na PR; nocny
# build też go obejmuje. Buduje się na obrazie bazowym, więc wymusza image=true (etap 5 zbuduje bazę). #135
radiologia=false
case $EVENT in
  pull_request | merge_group)
    { has_label build-radiologia || radiologia_change "$BASE"; } && radiologia=true
    ;;
  schedule)
    [[ $SCHEDULE == "$NIGHTLY_CRON" ]] && radiologia=true
    ;;
esac
[[ $radiologia == true ]] && image=true

perf=false
{ has_label perf || [[ ${IN_PERF:-false} == true ]]; } && perf=true
# nocny build obejmuje też benchmarki wydajności (wczesne wykrycie regresji wydajności)
[[ $EVENT == schedule && $SCHEDULE == "$NIGHTLY_CRON" ]] && perf=true
ephemeral=false
{ has_label deploy-test || [[ ${IN_EPHEMERAL:-false} == true ]]; } && ephemeral=true
# etap 6 potrzebuje obrazu z etapu 5
[[ $image == true ]] || perf=false ephemeral=false

echo "image=$image"
echo "radiologia=$radiologia"
echo "perf=$perf"
echo "ephemeral=$ephemeral"
