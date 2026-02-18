import base64
import binascii
import json
import os
import random
import socket
import ssl
import time
import urllib.request
from dataclasses import dataclass
from ipaddress import ip_address, ip_network


@dataclass
class Provider:
    id: str
    endpoint: str
    public_key: str
    allowed_ips: str
    client_ip: str | None = None
    lease_nonce: str | None = None
    lease_exp: int | None = None
    lease_sig: str | None = None


class PoolClient:
    def __init__(self, pool_url: str, timeout: int = 5, pool_token: str = "") -> None:
        self.pool_url = pool_url
        self.timeout = timeout
        self.pool_token = pool_token
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    def set_token(self, token: str) -> None:
        self.pool_token = token

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"User-Agent": "DVPN/1.0"}
        if self.pool_token:
            headers["X-DVPN-Token"] = self.pool_token
        if extra:
            headers.update(extra)
        return headers

    def fetch_providers(self) -> list[Provider]:
        req = urllib.request.Request(self.pool_url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
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
                    client_ip=item.get("client_ip"),
                    lease_nonce=item.get("lease_nonce"),
                    lease_exp=item.get("lease_exp"),
                    lease_sig=item.get("lease_sig"),
                )
            )
        return providers

    def mark_approved(self, provider: Provider, token: str) -> None:
        payload = json.dumps(
            {
                "provider_id": provider.id,
                "token": token,
                "approved": True,
                "client_ip": provider.client_ip,
                "lease_nonce": provider.lease_nonce,
                "lease_exp": provider.lease_exp,
                "lease_sig": provider.lease_sig,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.pool_url.rstrip("/") + "/approve",
            data=payload,
            headers=self._headers({"Content-Type": "application/json"}),
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
            headers=self._headers({"Content-Type": "application/json"}),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context):
            return

    def prune_dead_endpoints(self) -> dict:
        req = urllib.request.Request(
            self.pool_url.rstrip("/") + "/prune",
            data=b"{}",
            headers=self._headers({"Content-Type": "application/json"}),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch_next_claim(self, provider_id: str) -> dict | None:
        payload = json.dumps({"provider_id": provider_id}).encode("utf-8")
        req = urllib.request.Request(
            self.pool_url.rstrip("/") + "/claim/next",
            data=payload,
            headers=self._headers({"Content-Type": "application/json"}),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("ok"):
            return None
        claim = body.get("claim")
        return claim if isinstance(claim, dict) else None


def _allow_private_endpoints() -> bool:
    return os.getenv("ALLOW_PRIVATE_ENDPOINTS", "false").lower() == "true"


def _split_endpoint(endpoint: str) -> tuple[str, int]:
    if endpoint.startswith("["):
        host, remainder = endpoint.split("]", 1)
        host = host[1:]
        if not remainder.startswith(":"):
            raise ValueError("Invalid endpoint format")
        port_text = remainder[1:]
    else:
        host, port_text = endpoint.rsplit(":", 1)

    if not host:
        raise ValueError("Invalid endpoint host")
    port = int(port_text)
    if port < 1 or port > 65535:
        raise ValueError("Invalid endpoint port")
    return host, port


def _is_disallowed_host(host: str) -> bool:
    lowered = host.lower()
    if lowered in {"localhost", "ip6-localhost"} or lowered.endswith(".local"):
        return True

    try:
        ip = ip_address(host)
    except ValueError:
        return False

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_key(public_key: str) -> bool:
    try:
        decoded = base64.b64decode(public_key, validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(decoded) == 32


def validate_provider(provider: Provider) -> None:
    try:
        host, _ = _split_endpoint(provider.endpoint)
    except ValueError as err:
        raise ValueError(f"Invalid provider endpoint for {provider.id}: {err}") from err

    if not _allow_private_endpoints() and _is_disallowed_host(host):
        raise ValueError(f"Provider endpoint must be public-routable for {provider.id}")

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
    host, port = _split_endpoint(endpoint)
    start = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(b"\x00", (host, port))
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
