#!/usr/bin/env bash
# Stage 3.5: kontrakty obrazu zgodne z kodem — obserwowalność (observability/contract.yml)
# i zmienne wdrożeniowe (/etc/wlb/lab.env). Obraz buduje się raz i stawia wiele razy, więc
# parametr per Laboratorium musi istnieć jednocześnie w kodzie firstboot, we wzorze lab.env
# i w działającym przykładzie cloud-init — inaczej rozjazd jest niewidoczny do pierwszego wdrożenia.
# Część dynamiczna (czy zdarzenia docierają do SIEM) działa w stage 5 — ci/integration.sh.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require python3

run_check "Kontrakt obserwowalności: zdarzenia, pola, klucze audytu, prefiksy zapory, SIEM" \
  python3 ci/observability_contract.py static
run_check "Kontrakt zmiennych wdrożeniowych: lab.env ↔ wlb-firstboot ↔ przykłady cloud-init" \
  python3 ci/deployment_vars.py
finish
