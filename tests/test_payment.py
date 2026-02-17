import io
import json
import unittest
from unittest.mock import patch

from app.payment import PaymentVerifier


class FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._bytes = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._bytes.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestPaymentVerifier(unittest.TestCase):
    def test_active_payment_with_expected_wallet_and_monthly_price_passes(self):
        verifier = PaymentVerifier("https://payments.local/verify", "tok", timeout=1)

        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse(
                {
                    "active": True,
                    "wallet": "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn",
                    "interval": "monthly",
                    "amount_usd": 9.99,
                }
            ),
        ):
            self.assertTrue(verifier.is_active("provider-a"))

    def test_wrong_wallet_fails_even_if_active(self):
        verifier = PaymentVerifier("https://payments.local/verify", "tok", timeout=1)

        with patch(
            "urllib.request.urlopen",
            return_value=FakeHTTPResponse(
                {
                    "active": True,
                    "wallet": "bc1wrongwallet",
                    "interval": "monthly",
                    "amount_usd": 9.99,
                }
            ),
        ):
            self.assertFalse(verifier.is_active("provider-a"))


if __name__ == "__main__":
    unittest.main()
