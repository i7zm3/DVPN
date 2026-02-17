import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


class ControlServer:
    def __init__(
        self,
        host: str,
        port: int,
        actions: dict[str, Callable[[], dict]],
        metrics_fn: Callable[[], str] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.actions = actions
        self.metrics_fn = metrics_fn
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        actions = self.actions
        metrics_fn = self.metrics_fn

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.strip("/") == "health":
                    payload = json.dumps({"ok": True}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if self.path.strip("/") == "metrics" and metrics_fn is not None:
                    payload = metrics_fn().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                action = self.path.strip("/")
                if action not in actions:
                    self.send_response(404)
                    self.end_headers()
                    return
                try:
                    body = actions[action]()
                    payload = json.dumps(body).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as err:
                    payload = json.dumps({"ok": False, "error": str(err)}).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

            def log_message(self, format, *args):
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
