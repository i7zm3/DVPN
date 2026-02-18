#!/usr/bin/env bash
set -euo pipefail

CONTROL_URL="${CONTROL_URL:-http://127.0.0.1:8765}"
WG_CONFIG="${WG_CONFIG_PATH:-/tmp/dvpn/wg0.conf}"

echo "[check] control: ${CONTROL_URL}"
echo "[check] stopping service for baseline route"
curl -fsS -X POST "${CONTROL_URL}/stop" >/dev/null || true
sleep 2

PLAIN_ROUTE="$(ip -4 route get 1.1.1.1 2>/dev/null || true)"
echo "[check] baseline route: ${PLAIN_ROUTE}"

echo "[check] starting service"
curl -fsS -X POST "${CONTROL_URL}/start" >/dev/null

STATUS=""
for _ in $(seq 1 20); do
  STATUS="$(curl -fsS "${CONTROL_URL}/status" || true)"
  if echo "${STATUS}" | rg -q '"connection": "connected to '; then
    break
  fi
  sleep 2
done

echo "[check] status: ${STATUS}"
if ! echo "${STATUS}" | rg -q '"connection": "connected to '; then
  echo "[fail] service did not reach connected state"
  exit 1
fi

TUN_ROUTE="$(ip -4 route get 1.1.1.1 2>/dev/null || true)"
echo "[check] tunnel route: ${TUN_ROUTE}"
if ! echo "${TUN_ROUTE}" | rg -q 'dev wg0|table 51820'; then
  echo "[fail] default test route is not forced via wg0 policy table"
  exit 1
fi

if [[ ! -f "${WG_CONFIG}" ]]; then
  echo "[fail] WG config missing: ${WG_CONFIG}"
  exit 1
fi

ENDPOINT="$(rg '^Endpoint\\s*=\\s*' "${WG_CONFIG}" -N | head -n1 | awk -F'=' '{print $2}' | xargs || true)"
if [[ -z "${ENDPOINT}" ]]; then
  echo "[fail] endpoint not found in ${WG_CONFIG}"
  exit 1
fi
HOST="${ENDPOINT%:*}"
HOST="${HOST#[}"
HOST="${HOST%]}"
echo "[check] endpoint host: ${HOST}"

python3 - <<PY
import ipaddress
host = "${HOST}"
try:
    ip = ipaddress.ip_address(host)
except ValueError:
    raise SystemExit(0)
if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
    raise SystemExit(1)
PY
if [[ $? -ne 0 ]]; then
  echo "[fail] endpoint host is non-public (LAN/loopback/link-local)"
  exit 1
fi

echo "[pass] tunnel policy route + endpoint safety checks passed"
