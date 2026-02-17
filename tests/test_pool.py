import random
import unittest

from app.pool import Provider, mesh_cycle, validate_provider, validate_public_key


class TestPoolSecurityAndMesh(unittest.TestCase):
    def test_validate_public_key_accepts_wireguard_length(self):
        self.assertTrue(validate_public_key("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="))

    def test_validate_public_key_rejects_invalid(self):
        self.assertFalse(validate_public_key("not-a-valid-key"))

    def test_validate_provider_checks_endpoint_and_cidrs(self):
        provider = Provider(
            id="node-a",
            endpoint="8.8.8.8:51820",
            public_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            allowed_ips="0.0.0.0/0,::/0",
        )
        validate_provider(provider)

    def test_validate_provider_rejects_private_endpoint(self):
        provider = Provider(
            id="node-a",
            endpoint="10.0.0.1:51820",
            public_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            allowed_ips="0.0.0.0/0,::/0",
        )
        with self.assertRaises(ValueError):
            validate_provider(provider)

    def test_mesh_cycle_deprioritizes_previous_provider(self):
        providers = [
            Provider("a", "8.8.8.8:51820", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "0.0.0.0/0"),
            Provider("b", "1.1.1.1:51820", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "0.0.0.0/0"),
            Provider("c", "9.9.9.9:51820", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=", "0.0.0.0/0"),
        ]
        ordered = mesh_cycle(providers, previous_provider_id="b", rng=random.Random(0))
        self.assertEqual({p.id for p in ordered}, {"a", "b", "c"})
        self.assertNotEqual(ordered[0].id, "b")


if __name__ == "__main__":
    unittest.main()
