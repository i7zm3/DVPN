#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

docker compose down || true

if [[ "$(uname -s)" == "Linux" ]]; then
  if [[ "${EUID}" -eq 0 ]]; then
    ./scripts/strict_firewall_disable.sh || true
    ./scripts/provider_disable_forwarding.sh || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n ./scripts/strict_firewall_disable.sh || \
      echo "Strict firewall rollback needs sudo. Run: sudo ./scripts/strict_firewall_disable.sh"
    sudo -n ./scripts/provider_disable_forwarding.sh || \
      echo "Forwarding rollback needs sudo. Run: sudo ./scripts/provider_disable_forwarding.sh"
  fi
fi

echo "DVPN stopped. Forwarding rollback attempted."
