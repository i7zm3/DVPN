import json
import shutil
import socket
import ssl
import subprocess
import urllib.request
from dataclasses import dataclass
from ipaddress import ip_address, ip_network


@dataclass
class NetworkInfo:
    local_ip: str | None
    public_ip: str | None
    upnp_mapped: bool
    cgnat_suspected: bool


def detect_local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def detect_public_ip(timeout: int = 5) -> str | None:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Prefer Cloudflare trace on our control-plane domain so strict firewall allowlists
    # still permit public IP detection during startup.
    urls = [
        "https://api.dvpn.lol/cdn-cgi/trace",
        "https://api.ipify.org?format=json",
        "https://ifconfig.co/json",
    ]
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
                body = response.read().decode("utf-8", errors="replace")
            if "cdn-cgi/trace" in url:
                for line in body.splitlines():
                    if line.startswith("ip="):
                        ip = line.split("=", 1)[1].strip()
                        if ip:
                            return ip
                continue
            payload = json.loads(body)
            ip = payload.get("ip")
            if isinstance(ip, str) and ip:
                return ip
        except Exception:
            continue
    return None


def map_upnp(port: int, protocol: str = "UDP", local_ip: str | None = None) -> bool:
    if port < 1 or port > 65535:
        return False
    upnpc = shutil.which("upnpc")
    if not upnpc:
        return False
    if not local_ip:
        local_ip = detect_local_ip()
    if not local_ip:
        return False
    try:
        subprocess.run(
            [upnpc, "-e", "DVPN", "-a", local_ip, str(port), str(port), protocol.upper()],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
        return True
    except Exception:
        return False


def map_upnp_retry(port: int, protocol: str = "UDP", attempts: int = 3, local_ip: str | None = None) -> bool:
    attempts = max(1, attempts)
    for _ in range(attempts):
        if map_upnp(port, protocol, local_ip=local_ip):
            return True
    return False


def is_cgnat_suspected(public_ip: str | None) -> bool:
    if not public_ip:
        return True
    try:
        ip = ip_address(public_ip)
    except ValueError:
        return True
    cgnat = ip_network("100.64.0.0/10")
    return ip in cgnat or ip.is_private


def derive_wg_public_key(private_key: str) -> str | None:
    try:
        proc = subprocess.run(
            ["wg", "pubkey"],
            input=private_key,
            text=True,
            capture_output=True,
            check=True,
            timeout=3,
        )
        key = proc.stdout.strip()
        return key if key else None
    except Exception:
        return None


def auto_network_config(enable_upnp: bool, upnp_port: int) -> NetworkInfo:
    local_ip = detect_local_ip()
    public_ip = detect_public_ip()
    upnp_mapped = map_upnp_retry(upnp_port, local_ip=local_ip) if enable_upnp else False
    return NetworkInfo(
        local_ip=local_ip,
        public_ip=public_ip,
        upnp_mapped=upnp_mapped,
        cgnat_suspected=is_cgnat_suspected(public_ip),
    )
