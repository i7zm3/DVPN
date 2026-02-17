#!/usr/bin/env python3
import base64
import os
import platform
import secrets
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def render_env(values: dict[str, str], original_order: list[str]) -> str:
    seen = set()
    lines: list[str] = []
    for key in original_order:
        if key in values:
            lines.append(f"{key}={values[key]}")
            seen.add(key)
    for key in sorted(values):
        if key not in seen:
            lines.append(f"{key}={values[key]}")
    return "\n".join(lines) + "\n"


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def wireguard_private_key_placeholder() -> str:
    # This is not a cryptographically correct WireGuard key. The runtime script
    # replaces placeholder/private-key failures with `wg genkey` when available.
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def main() -> None:
    if not ENV_EXAMPLE.exists():
        raise SystemExit("Missing .env.example")

    base = parse_env(ENV_EXAMPLE)
    current = parse_env(ENV_FILE)

    merged = {**base, **current}
    defaults = {
        "USER_ID": f"user-{uuid.uuid4().hex[:12]}",
        "PAYMENT_TOKEN": random_token(24),
        "TOKEN_STORE_PASSPHRASE": random_token(24),
        "WG_PRIVATE_KEY": wireguard_private_key_placeholder(),
        "AUTO_NETWORK_CONFIG": "true",
        "UPNP_ENABLED": "true",
        "NODE_REGISTER_ENABLED": "true",
        "NODE_ID": f"node-{uuid.uuid4().hex[:12]}",
        "NODE_PORT": "51820",
        "ENABLE_TRAY": "false",
        "ENDPOINT_ROTATE_SECONDS": "240",
        "ENDPOINT_ROTATE_JITTER_SECONDS": "45",
        "LOG_STDOUT": "false",
        "AUDIT_ENABLED": "false",
    }

    placeholder_values = {"", "replace-me", "change-me"}
    for key, val in defaults.items():
        if merged.get(key, "") in placeholder_values:
            merged[key] = val

    if platform.system().lower() == "windows":
        merged["ENABLE_TRAY"] = "true"

    if not merged.get("FALLBACK_CA_CERT"):
        merged["FALLBACK_CA_CERT"] = "/app/certs/dev-ca.crt"
    if not merged.get("SSL_CERT_FILE"):
        merged["SSL_CERT_FILE"] = "/app/certs/dev-ca.crt"

    order = [line.split("=", 1)[0] for line in ENV_EXAMPLE.read_text().splitlines() if "=" in line]
    ENV_FILE.write_text(render_env(merged, order))
    print(f"Prepared {ENV_FILE}")


if __name__ == "__main__":
    main()
