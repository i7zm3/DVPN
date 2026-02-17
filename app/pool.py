import base64
import binascii
import json
import random
import socket
import ssl
import time
import urllib.request
from dataclasses import dataclass
from ipaddress import ip_network


@dataclass
class Provider:
    id: str
    endpoint: str
    public_key: str
    allowed_ips: str


class PoolClient:
    def __init__(self, pool_url: str, timeout: int = 5) -> None:
        self.pool_url = pool_url
        self.timeout = timeout
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    def fetch_providers(self) -> list[Provider]:
        with urllib.request.urlopen(self.pool_url, timeout=self.timeout, context=self.ssl_context) as response:
            raw = json.loads(response.read().decode("utf-8"))

        providers = []
        for item in raw:
            if item.get("health") not in (None, "ok"):
                continue
            providers.append(
                Provider(
                    id=item["id"],
                    endpoint=item["endpoint"],
                    public_key=item["public_key"],
                    allowed_ips=item.get("allowed_ips", "0.0.0.0/0,::/0"),
                )
            )
        return providers

    def mark_approved(self, provider_id: str, token: str) -> None:
        payload = json.dumps({"provider_id": provider_id, "token": token, "approved": True}).encode("utf-8")
        req = urllib.request.Request(
            self.pool_url.rstrip("/") + "/approve",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context):
            return

    def register_node(
        self,
        node_id: str,
        endpoint: str,
        public_key: str,
        allowed_ips: str,
        metadata: dict | None = None,
    ) -> None:
        payload = {
            "id": node_id,
            "endpoint": endpoint,
            "public_key": public_key,
            "allowed_ips": allowed_ips,
            "metadata": metadata or {},
        }
        req = urllib.request.Request(
            self.pool_url.rstrip("/") + "/register",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context):
            return


def validate_public_key(public_key: str) -> bool:
    try:
        decoded = base64.b64decode(public_key, validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(decoded) == 32


def validate_provider(provider: Provider) -> None:
    host, port_text = provider.endpoint.rsplit(":", 1)
    if not host:
        raise ValueError(f"Invalid provider endpoint host for {provider.id}")
    port = int(port_text)
    if port < 1 or port > 65535:
        raise ValueError(f"Invalid provider endpoint port for {provider.id}")

    if not validate_public_key(provider.public_key):
        raise ValueError(f"Invalid WireGuard public key for provider {provider.id}")

    for cidr in provider.allowed_ips.split(","):
        ip_network(cidr.strip(), strict=False)


def mesh_cycle(
    providers: list[Provider],
    previous_provider_id: str | None = None,
    rng: random.Random | None = None,
) -> list[Provider]:
    if not providers:
        return []
    source = rng if rng is not None else random.SystemRandom()
    shuffled = providers[:]
    source.shuffle(shuffled)
    if previous_provider_id:
        preferred = [p for p in shuffled if p.id != previous_provider_id]
        if preferred:
            tail = [p for p in shuffled if p.id == previous_provider_id]
            shuffled = preferred + tail
    return shuffled


def measure_latency(endpoint: str, timeout: int = 2) -> float:
    host, port = endpoint.rsplit(":", 1)
    start = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(b"\x00", (host, int(port)))
    return (time.perf_counter() - start) * 1000


def fastest_provider(providers: list[Provider], timeout: int = 2) -> Provider:
    if not providers:
        raise ValueError("No providers available in pool")

    scored = []
    for provider in providers:
        try:
            validate_provider(provider)
            latency = measure_latency(provider.endpoint, timeout=timeout)
            scored.append((latency, provider))
        except (OSError, ValueError):
            continue

    if not scored:
        raise RuntimeError("No reachable providers")

    scored.sort(key=lambda item: item[0])
    return scored[0][1]
