#!/usr/bin/env bash
# Testowe PKI dla akceptacji: jedna CA podpisuje certyfikaty serwerów SIEM i huba.
#   - SIEM (tests/syslog_sink.py --tls-*): CN=siem.test.local (SIEM_TLS_NAME w user-data.yaml).
#   - Hub (TLS huba, #18): SAN localhost + 127.0.0.1, by curl w VM weryfikował HTTPS po nazwie
#     i CA, bez -k (HUB=https://localhost w remote-common.sh).
# Generowane przy teście, nigdy nie trafia do repozytorium; ważne 30 dni, odnawiane < 2 dni.
#   tests/lib/test-pki.sh KATALOG
#     -> KATALOG/siem-ca.pem (= CA), siem.pem, siem.key, hub.pem, hub.key
set -euo pipefail
dir=$1
siem_name=siem.test.local
mkdir -p "$dir"
if [[ -f $dir/siem.pem && -f $dir/hub.pem ]] &&
  openssl x509 -checkend 172800 -noout -in "$dir/siem.pem" >/dev/null &&
  openssl x509 -checkend 172800 -noout -in "$dir/hub.pem" >/dev/null; then
  exit 0
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 30 -subj "/CN=WLB test CA" \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -keyout "$tmp/ca.key" -out "$tmp/ca.pem" 2>/dev/null

# cert_for NAZWA_PLIKU SAN — wystawia certyfikat serwera podpisany przez CA, z podanym subjectAltName.
cert_for() {
  local base=$1 san=$2
  openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -subj "/CN=${base}" \
    -keyout "$tmp/$base.key" -out "$tmp/$base.csr" 2>/dev/null
  printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n' "$san" >"$tmp/$base.ext"
  openssl x509 -req -in "$tmp/$base.csr" -CA "$tmp/ca.pem" -CAkey "$tmp/ca.key" -CAcreateserial -days 30 \
    -extfile "$tmp/$base.ext" -out "$tmp/$base.pem" 2>/dev/null
}

cert_for siem "DNS:${siem_name}"
cert_for hub "DNS:localhost,IP:127.0.0.1"

install -m 0644 "$tmp/ca.pem" "$dir/siem-ca.pem"
install -m 0644 "$tmp/siem.pem" "$dir/siem.pem"
install -m 0600 "$tmp/siem.key" "$dir/siem.key"
install -m 0644 "$tmp/hub.pem" "$dir/hub.pem"
install -m 0600 "$tmp/hub.key" "$dir/hub.key"
echo "Testowe PKI: $dir (SIEM ${siem_name}, hub localhost/127.0.0.1, wspólna CA)"
