#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

IMAGE="${DVPN_IMAGE:-dvpn-dvpn:latest}"
NET="${DVPN_TEST_NET:-dvpn_local_test}"
POOL="dvpn-pool"
A="dvpn-wg-a"
B="dvpn-wg-b"

cleanup() {
  docker rm -f "${POOL}" "${A}" "${B}" >/dev/null 2>&1 || true
  docker network rm "${NET}" >/dev/null 2>&1 || true
  rm -f /tmp/dvpn_local_pool.py
}
trap cleanup EXIT
cleanup

cat > /tmp/dvpn_local_pool.py <<'PY'
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

A_PUB = "x5j0ufRvsSbX0iq85YfG6GakDkVjIfEzthpQTyMVbUw="
B_PUB = "Uw+WPiE05CPiIPEcF36t6B2ryeFyQaQ/Yim4I+raiT0="
PROVIDERS = [
    {"id": "node-wga", "endpoint": "dvpn-wg-a:51820", "public_key": A_PUB, "allowed_ips": "0.0.0.0/0", "health": "ok"},
    {"id": "node-wgb", "endpoint": "dvpn-wg-b:51821", "public_key": B_PUB, "allowed_ips": "0.0.0.0/0", "health": "ok"},
]

class H(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def _read(self):
        n = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(n).decode()) if n else {}
    def do_GET(self):
        if self.path == "/providers": return self._send(200, PROVIDERS)
        if self.path == "/health": return self._send(200, {"ok": True})
        self._send(404, {"ok": False})
    def do_POST(self):
        if self.path in {"/providers/approve", "/providers/register"}:
            return self._send(200, {"ok": True})
        if self.path == "/verify":
            body = self._read()
            return self._send(200, {"active": bool(body.get("token")), "wallet": "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn", "interval": "monthly", "amount_usd": 9.99})
        if self.path.startswith("/verify/checkout"):
            return self._send(200, {"active": True, "session_id": "sess-local", "checkout_url": "http://dvpn-pool:18080/"})
        self._send(404, {"ok": False})
    def log_message(self, *_):
        return

ThreadingHTTPServer(("0.0.0.0", 18080), H).serve_forever()
PY

docker build -t "${IMAGE}" . >/dev/null

docker network create "${NET}" >/dev/null

docker run -d --name "${POOL}" --network "${NET}" -v /tmp/dvpn_local_pool.py:/pool.py:ro python:3.12-slim python /pool.py >/dev/null

docker run -d --name "${A}" --network "${NET}" --privileged --device /dev/net/tun:/dev/net/tun \
  --env-file .env \
  -e POOL_URL=http://dvpn-pool:18080/providers \
  -e PAYMENT_API_URL=http://dvpn-pool:18080/verify \
  -e PAYMENT_PORTAL_URL=http://dvpn-pool:18080/portal \
  -e FALLBACK_ENABLED=false \
  -e ALLOW_PRIVATE_ENDPOINTS=true \
  -e NODE_REGISTER_ENABLED=false \
  -e AUTO_NETWORK_CONFIG=false \
  -e UPNP_ENABLED=false \
  -e WG_DNS= \
  -e WG_PRIVATE_KEY='MKgYNI9HIVUfTIlxlrZf8lTz/hlIgsDYZi8VKh5HtVk=' \
  -e WG_ADDRESS='10.66.0.2/32' \
  -e NODE_ID=node-wga \
  -e NODE_PORT=51820 \
  -e CONTROL_PORT=8765 \
  -e ENABLE_TRAY=false \
  -e TOKEN_STORE_PATH=/tmp/dvpn/token-wga.store \
  "${IMAGE}" >/dev/null

docker run -d --name "${B}" --network "${NET}" --privileged --device /dev/net/tun:/dev/net/tun \
  --env-file .env \
  -e POOL_URL=http://dvpn-pool:18080/providers \
  -e PAYMENT_API_URL=http://dvpn-pool:18080/verify \
  -e PAYMENT_PORTAL_URL=http://dvpn-pool:18080/portal \
  -e FALLBACK_ENABLED=false \
  -e ALLOW_PRIVATE_ENDPOINTS=true \
  -e NODE_REGISTER_ENABLED=false \
  -e AUTO_NETWORK_CONFIG=false \
  -e UPNP_ENABLED=false \
  -e WG_DNS= \
  -e WG_PRIVATE_KEY='cMga274zrhEgoPRpFzQ/NFwOdj7vdzH4282ItLdUhGA=' \
  -e WG_ADDRESS='10.66.0.3/32' \
  -e NODE_ID=node-wgb \
  -e NODE_PORT=51821 \
  -e CONTROL_PORT=8766 \
  -e ENABLE_TRAY=false \
  -e TOKEN_STORE_PATH=/tmp/dvpn/token-wgb.store \
  "${IMAGE}" >/dev/null

sleep 20

A_OUT="$(docker exec "${A}" wg show)"
B_OUT="$(docker exec "${B}" wg show)"

printf '%s\n' "${A_OUT}" | sed -n '1,30p'
printf '%s\n' "${B_OUT}" | sed -n '1,30p'

if printf '%s' "${A_OUT}" | grep -q 'latest handshake' && printf '%s' "${B_OUT}" | grep -q 'latest handshake'; then
  echo "PASS: bidirectional WireGuard handshake detected"
else
  echo "FAIL: handshake not detected on both nodes" >&2
  exit 1
fi
