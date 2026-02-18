#!/usr/bin/env bash
set -euo pipefail

# Sets the Worker secret PAID_TOKENS_JSON using a Cloudflare API token.
#
# Required env:
#   CF_API_TOKEN   Cloudflare API token with Workers Secrets edit permission
#   CF_ACCOUNT_ID  Cloudflare Account ID
# Optional env:
#   CF_WORKER_NAME (default: dvpn-worker)
#
# Usage:
#   CF_API_TOKEN=... CF_ACCOUNT_ID=... ./scripts/cloudflare_set_paid_tokens.sh tok_abc tok_def
#   CF_API_TOKEN=... CF_ACCOUNT_ID=... TOKENS_FILE=tokens.txt ./scripts/cloudflare_set_paid_tokens.sh

WORKER_NAME="${CF_WORKER_NAME:-dvpn-worker}"
ACCOUNT_ID="${CF_ACCOUNT_ID:-}"
API_TOKEN="${CF_API_TOKEN:-}"
TOKENS_FILE="${TOKENS_FILE:-}"

if [[ -z "${ACCOUNT_ID}" ]]; then
  echo "Missing CF_ACCOUNT_ID" >&2
  exit 1
fi
if [[ -z "${API_TOKEN}" ]]; then
  echo "Missing CF_API_TOKEN" >&2
  exit 1
fi

TOKENS=()
if [[ -n "${TOKENS_FILE}" ]]; then
  if [[ ! -f "${TOKENS_FILE}" ]]; then
    echo "TOKENS_FILE not found: ${TOKENS_FILE}" >&2
    exit 1
  fi
  while IFS= read -r line; do
    t="${line%%#*}"
    t="${t//[[:space:]]/}"
    [[ -z "${t}" ]] && continue
    TOKENS+=("${t}")
  done < "${TOKENS_FILE}"
else
  TOKENS=("$@")
fi

if [[ ${#TOKENS[@]} -eq 0 ]]; then
  echo "No tokens provided." >&2
  exit 1
fi

TOKENS_JSON="$(python3 - <<'PY' "${TOKENS[@]}"
import json,sys
print(json.dumps(sys.argv[1:]))
PY
)"

PAYLOAD="$(python3 - <<'PY' "${TOKENS_JSON}"
import json,sys
tokens_json = sys.argv[1]
print(json.dumps({"name":"PAID_TOKENS_JSON","text":tokens_json,"type":"secret_text"}))
PY
)"

# Cloudflare API: bulk update secrets expects an array.
BODY="[${PAYLOAD}]"

resp="$(curl -sS -X PUT \
  "https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/workers/services/${WORKER_NAME}/environments/production/secrets" \
  -H "Authorization: Bearer ${API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data "${BODY}")"

ok="$(python3 - <<'PY' "${resp}"
import json,sys
r=json.loads(sys.argv[1])
print('true' if r.get('success') else 'false')
PY
)"

if [[ "${ok}" != "true" ]]; then
  echo "Cloudflare API returned error:" >&2
  echo "${resp}" >&2
  exit 1
fi

echo "PAID_TOKENS_JSON updated for worker '${WORKER_NAME}'."
