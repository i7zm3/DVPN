#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER="dvpn-node"

docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true

if [[ "$(uname -s)" == "Linux" ]]; then
  if [[ "${EUID}" -eq 0 ]]; then
    "${ROOT}/strict_firewall_disable.sh" || true
    "${ROOT}/provider_disable_forwarding.sh" || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n "${ROOT}/strict_firewall_disable.sh" || \
      echo "Strict firewall rollback needs sudo. Run: sudo ${ROOT}/strict_firewall_disable.sh"
    sudo -n "${ROOT}/provider_disable_forwarding.sh" || \
      echo "Forwarding rollback needs sudo. Run: sudo ${ROOT}/provider_disable_forwarding.sh"
  fi
fi

echo "Portable DVPN stopped. Forwarding rollback attempted."
