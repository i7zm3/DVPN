import json
import os
import random
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REQUIRED_WALLET = "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn"
REQUIRED_INTERVAL = "monthly"
REQUIRED_AMOUNT = 9.99
PUBLIC_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
ENDPOINTS = [
    "198.51.100.10:51820",
    "198.51.100.11:51820",
    "198.51.100.12:51820",
]
REGISTERED_NODES: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size) if size else b"{}"
        return json.loads(body.decode("utf-8"))

    def _send(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/portal":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Mock Payment Portal</h1></body></html>")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/verify":
            body = self._read_json()
            self._send(
                200,
                {
                    "active": bool(body.get("token")),
                    "wallet": REQUIRED_WALLET,
                    "interval": REQUIRED_INTERVAL,
                    "amount_usd": REQUIRED_AMOUNT,
                },
            )
            return
        if self.path == "/verify/checkout/start":
            body = self._read_json()
            self._send(
                200,
                {
                    "session_id": f"sess-{random.randint(1000, 9999)}",
                    "user_id": body.get("user_id", "local-user"),
                    "checkout_url": "https://mock-orchestrator:9443/portal",
                },
            )
            return
        if self.path == "/verify/checkout/status":
            self._send(200, {"active": True, "wallet": REQUIRED_WALLET, "interval": REQUIRED_INTERVAL, "amount_usd": REQUIRED_AMOUNT})
            return
        if self.path == "/provision":
            body = self._read_json()
            if not body.get("payment_token"):
                self._send(403, {"error": "payment_token required"})
                return
            endpoint = random.choice(ENDPOINTS)
            suffix = endpoint.split(":")[0].split(".")[-1]
            self._send(
                200,
                {
                    "id": f"fallback-{suffix}",
                    "endpoint": endpoint,
                    "public_key": PUBLIC_KEY,
                    "allowed_ips": "0.0.0.0/0,::/0",
                },
            )
            return
        if self.path == "/register":
            body = self._read_json()
            node_id = body.get("id")
            endpoint = body.get("endpoint")
            public_key = body.get("public_key")
            if not node_id or not endpoint or not public_key:
                self._send(400, {"error": "id, endpoint, public_key are required"})
                return
            REGISTERED_NODES[str(node_id)] = body
            self._send(200, {"ok": True, "node_id": node_id, "registered": len(REGISTERED_NODES)})
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[mock-orchestrator] {fmt % args}", flush=True)


def main() -> None:
    host = os.getenv("MOCK_HOST", "0.0.0.0")
    port = int(os.getenv("MOCK_PORT", "9443"))
    cert = os.getenv("MOCK_TLS_CERT", "/certs/dev-server.crt")
    key = os.getenv("MOCK_TLS_KEY", "/certs/dev-server.key")
    tls_enabled = os.getenv("MOCK_TLS_ENABLED", "true").lower() == "true"

    server = ThreadingHTTPServer((host, port), Handler)
    if tls_enabled:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certfile=cert, keyfile=key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
