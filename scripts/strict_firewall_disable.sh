#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

STATE_FILE="${DVPN_STRICT_FW_STATE_FILE:-/tmp/dvpn-strict-firewall.state}"

for chain in INPUT OUTPUT FORWARD; do
  iptables -D "${chain}" -j "DVPN_STRICT_${chain}" 2>/dev/null || true
done

for chain in DVPN_STRICT_INPUT DVPN_STRICT_OUTPUT DVPN_STRICT_FORWARD; do
  iptables -F "${chain}" 2>/dev/null || true
  iptables -X "${chain}" 2>/dev/null || true
done

rm -f "${STATE_FILE}" 2>/dev/null || true
echo "Strict firewall disabled and chains removed."
