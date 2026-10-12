#!/usr/bin/env bash
# Decyduje, które kosztowne etapy (5–6) uruchomić; wypisuje linie klucz=wartość dla $GITHUB_OUTPUT.
#   EVENT    pull_request | push | workflow_dispatch | schedule
#   BASE     SHA gałęzi docelowej PR
#   LABELS   JSON z etykietami PR, np. ["perf","deploy-test"]
#   IN_PERF, IN_EPHEMERAL   wejścia workflow_dispatch (true/false)
#   SCHEDULE wyrażenie cron, które wyzwoliło przebieg (github.event.schedule)
set -euo pipefail
EVENT=${EVENT:-push}
LABELS=${LABELS:-[]}
SCHEDULE=${SCHEDULE:-}
# Nocny pełny build jest chwilowo WYŁĄCZONY (zakomentowany w on.schedule w ci.yml). Przy włączaniu
# ustaw tutaj dokładnie ten sam cron, który odkomentujesz w ci.yml (github.event.schedule zwraca napis crona).
NIGHTLY_CRON="0 3 * * 2,5" # dopóki w ci.yml nie ma tego crona, ta gałąź nigdy się nie wyzwala

has_label() { python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.loads(sys.argv[1] or "[]") else 1)' "$LABELS" "$1"; }

# Stage 5: każda zmiana poza dokumentacją (README, przewodnik) może zmienić obraz
image=true
case $EVENT in
  pull_request)
    if ! git diff --name-only "$BASE" HEAD | grep -qvE '^(README\.md|przewodnik-vm\.sh|docs/|\.github/dependabot\.yml$)'; then
      image=false
    fi
    ;;
  schedule)
    if [[ $SCHEDULE == "$NIGHTLY_CRON" ]]; then
      image=true # nocny pełny build: etapy 1–6 niezależnie od zakresu zmian (regresje spoza repo)
    else
      image=false # cotygodniowo (pon.): tylko etapy 1–4 (nowe CVE w lockach, zmiany licencji)
    fi
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
