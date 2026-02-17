import tempfile
import unittest
from pathlib import Path

from app.security import SecureTokenStore


class TestSecureTokenStore(unittest.TestCase):
    def test_round_trip_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token.store"
            store = SecureTokenStore(path, "passphrase")
            store.save_token("token-123")

            loaded = store.load_token()
            self.assertEqual(loaded, "token-123")


if __name__ == "__main__":
    unittest.main()
