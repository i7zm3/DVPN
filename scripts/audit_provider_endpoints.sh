#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python3 - <<'PY'
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path


def fetch_live_providers(pool_url: str, token: str):
    if not pool_url:
        return None, "POOL_URL missing"
    try:
        cmd = ["curl", "-fsS", "--max-time", "10", pool_url]
        if token:
            cmd.extend(["-H", f"X-DVPN-Token: {token}"])
        env = dict(os.environ)
        env.pop("CURL_CA_BUNDLE", None)
        env.pop("SSL_CERT_FILE", None)
        env.pop("REQUESTS_CA_BUNDLE", None)
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=12, env=env)
        if cp.returncode != 0:
            err = (cp.stderr or cp.stdout or "curl failed").strip()
            return None, err
        body = cp.stdout
        providers = json.loads(body)
        if not isinstance(providers, list):
            return None, f"pool response is not a list ({type(providers).__name__})"
        return providers, None
    except Exception as exc:
        return None, str(exc)


def fetch_wrangler_providers():
    wrangler = Path("wrangler.toml")
    if not wrangler.exists():
        return None, "wrangler.toml not found"
    text = wrangler.read_text(encoding="utf-8")
    m = re.search(r'PROVIDERS_JSON\s*=\s*"""(.*?)"""', text, re.S)
    if not m:
        return None, "PROVIDERS_JSON missing in wrangler.toml"
    try:
        providers = json.loads(m.group(1))
    except Exception as exc:
        return None, f"invalid PROVIDERS_JSON: {exc}"
    if not isinstance(providers, list):
        return None, "wrangler PROVIDERS_JSON is not a list"
    return providers, None


def endpoint_parts(endpoint: str):
    if not endpoint or ":" not in endpoint:
        return None, None
    host, port_text = endpoint.rsplit(":", 1)
    try:
        return host, int(port_text)
    except Exception:
        return host, None


def udp_probe(host: str, port: int):
    # Unprivileged UDP probe. rc=0 is best signal, rc!=0 is likely closed/unreachable/filtered.
    cp = subprocess.run(
        ["nc", "-zvu", "-w", "3", host, str(port)],
        capture_output=True,
        text=True,
        timeout=6,
    )
    msg = (cp.stdout + cp.stderr).strip().replace("\n", " | ")
    return cp.returncode, msg


def dns_lookup(host: str, port: int):
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_UDP)
    return sorted({i[4][0] for i in infos})


pool_url = os.getenv("POOL_URL", "").strip()
token = os.getenv("PAYMENT_TOKEN", "").strip()

providers, live_err = fetch_live_providers(pool_url, token)
source = "pool"
if providers is None:
    providers, wrangler_err = fetch_wrangler_providers()
    source = "wrangler"
    if providers is None:
        print("ERROR: unable to load providers")
        print(f"  pool: {live_err}")
        print(f"  wrangler: {wrangler_err}")
        sys.exit(1)
    print(f"WARN: live pool fetch failed: {live_err}")
    print("INFO: falling back to wrangler.toml provider list")

print(f"Provider source: {source}")
print(f"Provider count: {len(providers)}")

bad = 0
for item in providers:
    pid = str(item.get("id", "unknown"))
    endpoint = str(item.get("endpoint", ""))
    host, port = endpoint_parts(endpoint)
    print()
    print(f"[{pid}] endpoint={endpoint}")
    if not host or not port:
        print("  status: FAIL invalid endpoint format")
        bad += 1
        continue
    try:
        addrs = dns_lookup(host, port)
        print(f"  dns: {', '.join(addrs)}")
    except Exception as exc:
        print(f"  dns: FAIL {exc}")
        bad += 1
        continue
    try:
        rc, msg = udp_probe(host, port)
        print(f"  udp_probe_rc: {rc}")
        if msg:
            print(f"  udp_probe_msg: {msg}")
        if rc != 0:
            print("  status: FAIL udp probe did not confirm listener")
            bad += 1
        else:
            print("  status: PASS udp probe accepted")
    except Exception as exc:
        print(f"  status: FAIL udp probe error: {exc}")
        bad += 1

print()
if bad:
    print(f"SUMMARY: {bad} endpoint(s) failing checks")
    sys.exit(2)
print("SUMMARY: all endpoints passed")
PY
