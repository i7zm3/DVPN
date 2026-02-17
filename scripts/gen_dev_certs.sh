#!/usr/bin/env bash
set -euo pipefail

CERT_DIR="${1:-certs}"
mkdir -p "${CERT_DIR}"

cat > "${CERT_DIR}/dev-openssl.cnf" <<'EOF'
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
C = US
ST = Dev
L = Dev
O = DVPN Dev
OU = Dev
CN = mock-orchestrator

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = mock-orchestrator
DNS.2 = localhost
IP.1 = 127.0.0.1
EOF

openssl genrsa -out "${CERT_DIR}/dev-ca.key" 2048
openssl req -x509 -new -nodes -key "${CERT_DIR}/dev-ca.key" -sha256 -days 3650 \
  -out "${CERT_DIR}/dev-ca.crt" -subj "/CN=DVPN Dev CA"

openssl genrsa -out "${CERT_DIR}/dev-server.key" 2048
openssl req -new -key "${CERT_DIR}/dev-server.key" -out "${CERT_DIR}/dev-server.csr" \
  -config "${CERT_DIR}/dev-openssl.cnf"
openssl x509 -req -in "${CERT_DIR}/dev-server.csr" -CA "${CERT_DIR}/dev-ca.crt" \
  -CAkey "${CERT_DIR}/dev-ca.key" -CAcreateserial -out "${CERT_DIR}/dev-server.crt" \
  -days 825 -sha256 -extensions v3_req -extfile "${CERT_DIR}/dev-openssl.cnf"

rm -f "${CERT_DIR}/dev-server.csr" "${CERT_DIR}/dev-openssl.cnf" "${CERT_DIR}/dev-ca.srl"
echo "Generated TLS certs in ${CERT_DIR}"
