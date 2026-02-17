import json
import time
import unittest
import urllib.request

from app.control import ControlServer


class TestControlServer(unittest.TestCase):
    def test_health_and_metrics_endpoints(self):
        server = ControlServer(
            "127.0.0.1",
            18765,
            actions={"ping": lambda: {"ok": True}},
            metrics_fn=lambda: "dvpn_test_metric 1\n",
            status_fn=lambda: {"ok": True, "killswitch_enabled": False, "start_on_boot": False},
        )
        server.start()
        try:
            time.sleep(0.05)
            with urllib.request.urlopen("http://127.0.0.1:18765/health", timeout=2) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(body["ok"])
            with urllib.request.urlopen("http://127.0.0.1:18765/metrics", timeout=2) as resp:
                text = resp.read().decode("utf-8")
                self.assertIn("dvpn_test_metric 1", text)
            with urllib.request.urlopen("http://127.0.0.1:18765/status", timeout=2) as resp:
                status = json.loads(resp.read().decode("utf-8"))
                self.assertIn("killswitch_enabled", status)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
