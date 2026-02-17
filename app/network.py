import json
import shutil
import socket
import ssl
import subprocess
import urllib.request
from dataclasses import dataclass


@dataclass
class NetworkInfo:
    local_ip: str | None
    public_ip: str | None
    upnp_mapped: bool


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
    urls = [
        "https://api.ipify.org?format=json",
        "https://ifconfig.co/json",
    ]
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
                payload = json.loads(response.read().decode("utf-8"))
            ip = payload.get("ip")
            if isinstance(ip, str) and ip:
                return ip
        except Exception:
            continue
    return None


def map_upnp(port: int, protocol: str = "UDP") -> bool:
    if port < 1 or port > 65535:
        return False
    upnpc = shutil.which("upnpc")
    if not upnpc:
        return False
    try:
        subprocess.run(
            [upnpc, "-e", "DVPN", "-a", "127.0.0.1", str(port), str(port), protocol.upper()],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
        return True
    except Exception:
        return False


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
    upnp_mapped = map_upnp(upnp_port) if enable_upnp else False
    return NetworkInfo(local_ip=local_ip, public_ip=public_ip, upnp_mapped=upnp_mapped)
