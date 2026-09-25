#!/usr/bin/env bash
# Stage 3.5: kontrakt obserwowalności (observability/contract.yml) zgodny z kodem obrazu.
# Część dynamiczna (czy zdarzenia docierają do SIEM) działa w stage 5 — ci/integration.sh.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require python3

run_check "Kontrakt obserwowalności: zdarzenia, pola, klucze audytu, prefiksy zapory, SIEM" \
  python3 ci/observability_contract.py static
finish
