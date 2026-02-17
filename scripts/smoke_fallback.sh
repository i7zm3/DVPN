#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f certs/dev-ca.crt ]]; then
  echo "Missing certs/dev-ca.crt. Run: ./scripts/gen_dev_certs.sh"
  exit 1
fi

curl --silent --show-error --fail --tlsv1.2 \
  --cacert certs/dev-ca.crt \
  -H 'Content-Type: application/json' \
  -d '{"payment_token":"tok","user_id":"smoke"}' \
  https://localhost:9443/provision | python -m json.tool
