# Fixture kontraktu SARIF (#257)

Kontrolowane wejście dla `ci/security.sh` (sprawdzenie „Kontrakt SARIF”): prawdziwe, przypięte wersje
semgrep i checkov skanują ten katalog, a `ci/sarif_report.py prepare` musi dać `findings` z oczekiwanymi
regułami, bez wartości canary w publikowanym SARIF, manifeście i logu. Katalog jest wyłączony z głównych
skanów etapu 3. Nie umieszczaj tu prawdziwych sekretów.
