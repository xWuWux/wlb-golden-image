# Fixture kontraktu SARIF (#257): syntetyczny sekret-canary dla reguł p/secrets semgrepa.
# Wartość nie jest prawdziwym kluczem (alfabet poza base32 AWS, więc gitleaks jej nie zgłasza).
# Wyłączony z głównych skanów etapu 3 (--exclude/--skip-path w ci/security.sh).
aws_access_key_id = "AKIAWLB257CANARY0000"
