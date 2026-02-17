import json
import ssl
import urllib.request

REQUIRED_BTC_WALLET = "1MUss4jmaRJ2sMtS9gyZqeRw8WrhWTsrxn"
REQUIRED_MONTHLY_PRICE_USD = 9.99
REQUIRED_PLAN_INTERVAL = "monthly"


class PaymentVerifier:
    def __init__(self, verify_url: str, token: str, timeout: int = 5) -> None:
        self.verify_url = verify_url
        self.token = token
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    def _request(self, url: str, payload: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "DVPN/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
            return json.loads(response.read().decode("utf-8"))

    def _checkout_url(self, suffix: str) -> str:
        base = self.verify_url.rstrip("/")
        return f"{base}/{suffix}"

    def begin_checkout(self, user_id: str) -> dict:
        return self._request(
            self._checkout_url("checkout/start"),
            {
                "user_id": user_id,
                "required_wallet": REQUIRED_BTC_WALLET,
                "required_price_usd": REQUIRED_MONTHLY_PRICE_USD,
                "required_interval": REQUIRED_PLAN_INTERVAL,
            },
        )

    def poll_checkout(self, session_id: str) -> dict:
        return self._request(
            self._checkout_url("checkout/status"),
            {
                "session_id": session_id,
                "required_wallet": REQUIRED_BTC_WALLET,
                "required_price_usd": REQUIRED_MONTHLY_PRICE_USD,
                "required_interval": REQUIRED_PLAN_INTERVAL,
            },
        )

    def _fetch_payment_status(self, provider_id: str) -> dict:
        return self._request(
            self.verify_url,
            {
                "token": self.token,
                "provider_id": provider_id,
                "required_wallet": REQUIRED_BTC_WALLET,
                "required_price_usd": REQUIRED_MONTHLY_PRICE_USD,
                "required_interval": REQUIRED_PLAN_INTERVAL,
            },
        )

    def is_active(self, provider_id: str) -> bool:
        body = self._fetch_payment_status(provider_id)

        active = bool(body.get("active", False))
        wallet = body.get("wallet")
        interval = body.get("interval")

        try:
            amount_usd = float(body.get("amount_usd", 0))
        except (TypeError, ValueError):
            amount_usd = 0.0

        return (
            active
            and wallet == REQUIRED_BTC_WALLET
            and interval == REQUIRED_PLAN_INTERVAL
            and amount_usd >= REQUIRED_MONTHLY_PRICE_USD
        )
