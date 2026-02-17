import tempfile
import textwrap
import unittest
from pathlib import Path

from app.fallback import FallbackProvisioner


class TestFallbackProvisioner(unittest.TestCase):
    def test_provision_parses_provider_from_script_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fallback.sh"
            script.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s' '{"id":"fallback-1","endpoint":"8.8.8.8:51820","public_key":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=","allowed_ips":"0.0.0.0/0,::/0"}'
                    """
                )
            )
            script.chmod(0o755)
            provisioner = FallbackProvisioner(
                enabled=True,
                script_path=script,
                orchestrator_url="https://orchestrator.example.com",
                timeout=2,
            )
            provider = provisioner.provision(payment_token="tok", user_id="user-1")

        self.assertEqual(provider.id, "fallback-1")
        self.assertEqual(provider.endpoint, "8.8.8.8:51820")

    def test_requires_https_orchestrator(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fallback.sh"
            script.write_text("#!/usr/bin/env bash\necho '{}'\n")
            script.chmod(0o755)
            provisioner = FallbackProvisioner(
                enabled=True,
                script_path=script,
                orchestrator_url="http://orchestrator.local",
                timeout=2,
            )
            with self.assertRaises(RuntimeError):
                provisioner.provision(payment_token="tok", user_id="user-1")


if __name__ == "__main__":
    unittest.main()
