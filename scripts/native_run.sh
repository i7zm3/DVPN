#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ ! -d .venv ]]; then
  echo "Missing .venv; run ./scripts/native_setup_linux.sh first" >&2
  exit 1
fi

. .venv/bin/activate

set -a
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi
set +a

# Prepare runtime paths used by WireGuard/token store so first run is clean.
WG_CONFIG_PATH="${WG_CONFIG_PATH:-/tmp/dvpn/wg0.conf}"
TOKEN_STORE_PATH="${TOKEN_STORE_PATH:-/tmp/dvpn/token.store}"
mkdir -p "$(dirname "${WG_CONFIG_PATH}")" "$(dirname "${TOKEN_STORE_PATH}")"
chmod 700 "$(dirname "${WG_CONFIG_PATH}")" "$(dirname "${TOKEN_STORE_PATH}")" 2>/dev/null || true

# On disconnect/stop, restore host forwarding rules changed by provider setup.
export PROVIDER_FORWARD_DISABLE_CMD="${PROVIDER_FORWARD_DISABLE_CMD:-${ROOT}/scripts/provider_disable_forwarding.sh}"
export PROVIDER_FORWARD_ENABLE_CMD="${PROVIDER_FORWARD_ENABLE_CMD:-${ROOT}/scripts/provider_enable_forwarding.sh}"
export STRICT_FIREWALL="${STRICT_FIREWALL:-true}"
export STRICT_FIREWALL_ENABLE_CMD="${STRICT_FIREWALL_ENABLE_CMD:-${ROOT}/scripts/strict_firewall_enable.sh}"
export STRICT_FIREWALL_DISABLE_CMD="${STRICT_FIREWALL_DISABLE_CMD:-${ROOT}/scripts/strict_firewall_disable.sh}"

cleanup_network() {
  if [[ "${STRICT_FIREWALL,,}" == "true" && -n "${STRICT_FIREWALL_DISABLE_CMD:-}" ]]; then
    bash -lc "${STRICT_FIREWALL_DISABLE_CMD}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${PROVIDER_FORWARD_DISABLE_CMD:-}" ]]; then
    bash -lc "${PROVIDER_FORWARD_DISABLE_CMD}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_network EXIT INT TERM

if [[ "${STRICT_FIREWALL,,}" == "true" && -n "${STRICT_FIREWALL_ENABLE_CMD:-}" ]]; then
  if [[ "${EUID}" -eq 0 ]]; then
    bash -lc "${STRICT_FIREWALL_ENABLE_CMD}" || true
  else
    echo "Strict firewall requested but not root; run with sudo to enforce strict firewall." >&2
  fi
fi

export ENABLE_TRAY="${ENABLE_TRAY:-true}"
python -m app.main
