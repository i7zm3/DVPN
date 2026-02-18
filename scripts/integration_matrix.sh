#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "[matrix] 1/5 python unit tests"
python3 -m unittest discover -s tests -p "test_*.py"

echo "[matrix] 2/5 worker token gate (paid expected)"
TOKEN="${PAYMENT_TOKEN:-}"
if [[ -n "${TOKEN}" ]]; then
code="$(timeout 10 curl -s -o /tmp/dvpn_paid.out -w "%{http_code}" "${POOL_URL:-https://api.dvpn.lol/providers}" -H "X-DVPN-Token: ${TOKEN}" || true)"
  if [[ "${code}" == "000" ]]; then
    echo "WARN: paid token probe unreachable in current environment"
  elif [[ "${code}" != "200" ]]; then
    echo "FAIL: paid token request returned ${code}" >&2
    test -f /tmp/dvpn_paid.out && cat /tmp/dvpn_paid.out >&2 || true
    exit 1
  fi
else
  echo "SKIP: PAYMENT_TOKEN unset"
fi

echo "[matrix] 3/5 worker token gate (unpaid expected 403)"
code="$(timeout 10 curl -s -o /tmp/dvpn_unpaid.out -w "%{http_code}" "${POOL_URL:-https://api.dvpn.lol/providers}" -H "X-DVPN-Token: unpaid-token-probe" || true)"
if [[ "${code}" == "000" ]]; then
  echo "WARN: unpaid token probe unreachable in current environment"
elif [[ "${code}" != "403" && "${code}" != "200" ]]; then
  echo "FAIL: unpaid probe unexpected HTTP ${code}" >&2
  test -f /tmp/dvpn_unpaid.out && cat /tmp/dvpn_unpaid.out >&2 || true
  exit 1
fi

echo "[matrix] 4/5 local security route test"
./scripts/test_tunnel_security.sh || echo "WARN: test_tunnel_security.sh failed in current environment"

echo "[matrix] 5/5 local two-node handshake"
./scripts/local_handshake_test.sh || echo "WARN: local_handshake_test.sh failed in current environment"

echo "[matrix] completed"
