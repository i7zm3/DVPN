#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

ENV_FILE="${1:-.env.prod}"
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

token="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"
passphrase="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
)"

tmp="$(mktemp)"
awk -F= -v t="$token" -v p="$passphrase" '
BEGIN { seen_t=0; seen_p=0; seen_wg=0 }
{
  if ($1=="PAYMENT_TOKEN") { print "PAYMENT_TOKEN=" t; seen_t=1; next }
  if ($1=="TOKEN_STORE_PASSPHRASE") { print "TOKEN_STORE_PASSPHRASE=" p; seen_p=1; next }
  if ($1=="WG_PRIVATE_KEY") { seen_wg=1; print; next }
  print
}
END {
  if (!seen_t) print "PAYMENT_TOKEN=" t
  if (!seen_p) print "TOKEN_STORE_PASSPHRASE=" p
}
' "${ENV_FILE}" > "${tmp}"

if command -v wg >/dev/null 2>&1; then
  wg_key="$(wg genkey)"
  awk -F= -v wgk="$wg_key" '
  BEGIN { seen=0 }
  {
    if ($1=="WG_PRIVATE_KEY") { print "WG_PRIVATE_KEY=" wgk; seen=1; next }
    print
  }
  END { if (!seen) print "WG_PRIVATE_KEY=" wgk }
  ' "${tmp}" > "${tmp}.wg"
  mv "${tmp}.wg" "${tmp}"
fi

mv "${tmp}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}" || true
echo "Rotated secrets in ${ENV_FILE}"
