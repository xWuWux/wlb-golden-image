#!/usr/bin/env bash
# Testowe PKI dla odbiornika SIEM (tests/syslog_sink.py --tls-*): CA i certyfikat serwera wystawiony
# na nazwę siem.test.local (SIEM_TLS_NAME w tests/cloud-init/user-data.yaml). Generowane przy teście,
# nigdy nie trafia do repozytorium; ważne 30 dni, odnawiane, gdy zostało mniej niż 2 dni.
#   tests/lib/test-pki.sh KATALOG   -> KATALOG/siem-ca.pem, siem.pem, siem.key
set -euo pipefail
dir=$1
name=siem.test.local
mkdir -p "$dir"
if [[ -f $dir/siem.pem ]] && openssl x509 -checkend 172800 -noout -in "$dir/siem.pem" >/dev/null; then
  exit 0
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 30 -subj "/CN=WLB test SIEM CA" \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -keyout "$tmp/ca.key" -out "$tmp/ca.pem" 2>/dev/null
openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj "/CN=$name" \
  -keyout "$tmp/siem.key" -out "$tmp/siem.csr" 2>/dev/null
printf 'subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n' "$name" >"$tmp/ext"
openssl x509 -req -in "$tmp/siem.csr" -CA "$tmp/ca.pem" -CAkey "$tmp/ca.key" -CAcreateserial -days 30 \
  -extfile "$tmp/ext" -out "$tmp/siem.pem" 2>/dev/null
install -m 0644 "$tmp/ca.pem" "$dir/siem-ca.pem"
install -m 0644 "$tmp/siem.pem" "$dir/siem.pem"
install -m 0600 "$tmp/siem.key" "$dir/siem.key"
echo "Testowe PKI SIEM: $dir (serwer $name)"
