#!/usr/bin/env bash
set -euo pipefail
IFACE="${1:-wg0}"
echo "[watch] iface=${IFACE}"
while true; do
  ts="$(date -Is)"
  echo "--- ${ts}"
  wg show "${IFACE}" 2>/dev/null || { echo "wg show failed"; sleep 1; continue; }
  echo
  wg show "${IFACE}" transfer 2>/dev/null || true
  echo
  sleep 1
done
