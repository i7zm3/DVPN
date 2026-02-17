import json
import os
import subprocess
from pathlib import Path

from app.pool import Provider, validate_provider


class FallbackProvisioner:
    def __init__(
        self,
        enabled: bool,
        script_path: Path,
        orchestrator_url: str,
        timeout: int = 30,
    ) -> None:
        self.enabled = enabled
        self.script_path = script_path
        self.orchestrator_url = orchestrator_url
        self.timeout = timeout

    def provision(self, payment_token: str, user_id: str) -> Provider:
        if not self.enabled:
            raise RuntimeError("Fallback provisioning disabled")
        if not self.orchestrator_url.startswith("https://"):
            allowed_local_http = self.orchestrator_url.startswith("http://127.0.0.1") or self.orchestrator_url.startswith("http://localhost")
            if not allowed_local_http:
                raise RuntimeError("Fallback orchestrator URL must use https://")
        if not self.script_path.exists():
            raise RuntimeError(f"Fallback script missing: {self.script_path}")

        env = os.environ.copy()
        env["PAYMENT_TOKEN"] = payment_token
        env["USER_ID"] = user_id
        env["FALLBACK_ORCHESTRATOR_URL"] = self.orchestrator_url

        result = subprocess.run(
            [str(self.script_path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=self.timeout,
            env=env,
        )
        payload = json.loads(result.stdout)
        provider = Provider(
            id=payload["id"],
            endpoint=payload["endpoint"],
            public_key=payload["public_key"],
            allowed_ips=payload.get("allowed_ips", "0.0.0.0/0,::/0"),
        )
        validate_provider(provider)
        return provider
