#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${FALLBACK_ORCHESTRATOR_URL:-}" ]]; then
  echo "FALLBACK_ORCHESTRATOR_URL is required" >&2
  exit 1
fi

if [[ "${FALLBACK_ORCHESTRATOR_URL}" != https://* ]]; then
  echo "FALLBACK_ORCHESTRATOR_URL must use https://" >&2
  exit 1
fi

if [[ -z "${PAYMENT_TOKEN:-}" ]]; then
  echo "PAYMENT_TOKEN is required" >&2
  exit 1
fi

if [[ -n "${WG_PRIVATE_KEY:-}" ]] && client_public_key="$(printf '%s' "${WG_PRIVATE_KEY}" | wg pubkey 2>/dev/null)"; then
  :
else
  temp_private_key="$(wg genkey)"
  client_public_key="$(printf '%s' "${temp_private_key}" | wg pubkey)"
fi

read -r -d '' payload <<EOF || true
{
  "user_id": "${USER_ID:-local-user}",
  "payment_token": "${PAYMENT_TOKEN}",
  "client_public_key": "${client_public_key}",
  "require_mesh": true,
  "rotate_endpoints": true,
  "anonymity_mode": "high",
  "security_profile": "strict"
}
EOF

curl_args=(
  --silent
  --show-error
  --fail
  --tlsv1.2
  --proto '=https'
  -H 'Content-Type: application/json'
  -X POST
  -d "${payload}"
  "${FALLBACK_ORCHESTRATOR_URL%/}/provision"
)

if [[ -n "${FALLBACK_CA_CERT:-}" ]]; then
  curl_args+=(--cacert "${FALLBACK_CA_CERT}")
fi

curl "${curl_args[@]}"
