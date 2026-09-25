#!/usr/bin/env bash
# Decyduje, które kosztowne etapy (5–6) uruchomić; wypisuje linie klucz=wartość dla $GITHUB_OUTPUT.
#   EVENT    pull_request | push | workflow_dispatch | schedule
#   BASE     SHA gałęzi docelowej PR
#   LABELS   JSON z etykietami PR, np. ["perf","deploy-test"]
#   IN_PERF, IN_EPHEMERAL   wejścia workflow_dispatch (true/false)
set -euo pipefail
EVENT=${EVENT:-push}
LABELS=${LABELS:-[]}

has_label() { python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.loads(sys.argv[1] or "[]") else 1)' "$LABELS" "$1"; }

# Stage 5: każda zmiana poza dokumentacją (README, przewodnik) może zmienić obraz
image=true
case $EVENT in
  pull_request)
    if ! git diff --name-only "$BASE" HEAD | grep -qvE '^(README\.md|przewodnik-vm\.sh|docs/|\.github/dependabot\.yml$)'; then
      image=false
    fi
    ;;
  schedule) image=false ;; # cotygodniowo tylko etapy 1–4 (nowe CVE w lockach, zmiany licencji)
esac

perf=false
{ has_label perf || [[ ${IN_PERF:-false} == true ]]; } && perf=true
ephemeral=false
{ has_label deploy-test || [[ ${IN_EPHEMERAL:-false} == true ]]; } && ephemeral=true
# etap 6 potrzebuje obrazu z etapu 5
[[ $image == true ]] || perf=false ephemeral=false

echo "image=$image"
echo "perf=$perf"
echo "ephemeral=$ephemeral"
