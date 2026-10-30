#!/usr/bin/env bash
# Stage 3.5: kontrakty obrazu zgodne z kodem — obserwowalność (observability/contract.yml),
# dekodery i reguły Wazuh (observability/siem/wazuh/) i zmienne wdrożeniowe (/etc/wlb/lab.env). Obraz buduje się raz i stawia wiele razy, więc
# parametr per Laboratorium musi istnieć jednocześnie w kodzie firstboot, we wzorze lab.env
# i w działającym przykładzie cloud-init — inaczej rozjazd jest niewidoczny do pierwszego wdrożenia.
# Część dynamiczna (czy zdarzenia docierają do SIEM) działa w stage 5 — ci/integration.sh.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require python3

run_check "Kontrakt obserwowalności: zdarzenia, pola, klucze audytu, prefiksy zapory, SIEM" \
  python3 ci/observability_contract.py static
run_check "Kontrakt metryk WLB (#22)" python3 ci/metrics_check.py --static
run_check "Kontrakt zmiennych wdrożeniowych: lab.env ↔ wlb-firstboot ↔ przykłady cloud-init" \
  python3 ci/deployment_vars.py

# Dekodery i reguły Wazuh na prawdziwym menedżerze (#17), na próbce z każdym zdarzeniem kontraktu.
# W CI docker jest zawsze; lokalnie bez dockera krok jest pomijany z ostrzeżeniem (jak kcov w unit.sh).
wazuh_sample() {
  if ! command -v docker >/dev/null; then
    [[ -z ${CI:-} ]] || return 1
    echo "docker niedostępny — pomijam test Wazuh (lokalnie: zainstaluj docker albo polegaj na CI)"
    return 0
  fi
  ci/wazuh-logtest.sh tests/fixtures/siem-sample.log --require-all \
    --expect-untrusted sluza_out.export_request --expect-untrusted hub.login --expect-untrusted shell.command
}
run_check "Wazuh: dekodery i reguły na próbce strumienia (#17)" wazuh_sample

# Wersja Ubuntu i wrapper zgodne z obrazem. Test startuje prywatny VNC w kontenerze,
# nigdy na żywej VM ani w istniejącej sesji badacza.
desktop_smoke() {
  if ! command -v docker >/dev/null; then
    [[ -z ${CI:-} ]] || return 1
    echo "docker niedostępny — pomijam lokalny test TigerVNC"
    return 0
  fi
  ci/desktop-vnc-smoke.sh
}
run_check "TigerVNC: konfiguracja Ubuntu i polityka schowka (#106)" desktop_smoke
finish
