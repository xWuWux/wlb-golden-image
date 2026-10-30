#!/usr/bin/env bash
# Dekodery i reguły Wazuh (observability/siem/wazuh/) na prawdziwym menedżerze Wazuh (#17).
#   ci/wazuh-logtest.sh LOG [--require-all] [--expect-untrusted ZDARZENIE]...
# Uruchamia przypięty obraz menedżera w kontenerze, ładuje nasze pliki, przepuszcza LOG przez
# wazuh-logtest i sprawdza wynik względem kontraktu (ci/wazuh_check.py): każde zdarzenie
# z kontraktu trafia w swoją regułę z nazwanymi polami, a wpis podrobiony — w regułę podszycia.
#   etap 3.5: próbka tests/fixtures/siem-sample.log (wszystkie zdarzenia, --require-all)
#   etap 5:   build/ci-logs/siem.log z testowego odbiornika SIEM (to, co naprawdę wysyła VM)
# Wynik surowy: build/wazuh/<nazwa logu>.jsonl. Wymaga dockera.
# shellcheck source=ci/common.sh
. "$(dirname "$0")/common.sh"
require docker python3

# Wersja zgodna z produkcyjnym Wazuh GUMed — zmiana wersji to zmiana tej linii w osobnym PR.
WAZUH_IMAGE=${WAZUH_IMAGE:-wazuh/wazuh-manager:4.14.9@sha256:dbb337727a6b6b17e24b1ccfe4c6e95fd983286ba0ccbf29d568144aa9527c6b}
WAZUH_DIR=observability/siem/wazuh
READY_TIMEOUT=${WAZUH_READY_TIMEOUT:-240}

[[ $# -ge 1 && -f $1 ]] || die "użycie: $0 LOG [--require-all] [--expect-untrusted ZDARZENIE]..."
LOG=$1
shift
OUT=build/wazuh
mkdir -p "$OUT"
RESULT=$OUT/$(basename "$LOG" .log).jsonl
NAME=wlb-wazuh-logtest-$$
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

ossec() { docker exec "$NAME" "$@"; }

wait_ready() { # analysisd uruchomiony i gniazdo logtest gotowe
  local waited status
  for ((waited = 0; waited < READY_TIMEOUT; waited += 3)); do
    # bez potoku do grep -q: przy pipefail SIGPIPE wazuh-control dawałby fałszywą porażkę
    status=$(ossec /var/ossec/bin/wazuh-control status 2>/dev/null || true)
    if [[ $status == *"wazuh-analysisd is running"* ]] && ossec test -S /var/ossec/queue/sockets/logtest; then
      return 0
    fi
    sleep 3
  done
  docker logs --tail 30 "$NAME" 2>&1 | grep -vi 'indexer\|publisher\|retryer' >&2 || true
  die "menedżer Wazuh nie wystartował w ${READY_TIMEOUT} s"
}

step "Menedżer Wazuh ($WAZUH_IMAGE)"
docker run -d --name "$NAME" "$WAZUH_IMAGE" >/dev/null
wait_ready
endstep

step "Ładowanie dekoderów i reguł WLB"
docker cp "$WAZUH_DIR/wlb_decoders.xml" "$NAME:/var/ossec/etc/decoders/wlb_decoders.xml"
docker cp "$WAZUH_DIR/wlb_rules.xml" "$NAME:/var/ossec/etc/rules/wlb_rules.xml"
docker cp ci/wazuh_logtest_client.py "$NAME:/tmp/wazuh_logtest_client.py"
ossec chown wazuh:wazuh /var/ossec/etc/decoders/wlb_decoders.xml /var/ossec/etc/rules/wlb_rules.xml
# analysisd z błędnym plikiem nie startuje — test konfiguracji daje czytelny komunikat zamiast timeoutu
ossec /var/ossec/bin/wazuh-analysisd -t 2>&1 | tail -20
ossec /var/ossec/bin/wazuh-analysisd -t >/dev/null 2>&1 || die "Wazuh odrzucił dekodery lub reguły WLB (wazuh-analysisd -t)"
ossec /var/ossec/bin/wazuh-control restart >/dev/null
wait_ready
endstep

step "wazuh-logtest: $LOG"
docker exec -i "$NAME" /var/ossec/framework/python/bin/python3 -I /tmp/wazuh_logtest_client.py <"$LOG" >"$RESULT"
endstep

python3 ci/wazuh_check.py "$RESULT" "$@"
