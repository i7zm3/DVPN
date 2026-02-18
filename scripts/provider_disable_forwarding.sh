#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

STATE_FILE="${DVPN_FORWARD_STATE_FILE:-/tmp/dvpn-provider-forwarding.state}"
if [[ ! -f "${STATE_FILE}" ]]; then
  echo "No forwarding state file found (${STATE_FILE}); nothing to restore."
  exit 0
fi

# shellcheck disable=SC1090
source "${STATE_FILE}"

WAN_IFACE="${WAN_IFACE:-}"
BACKEND="${BACKEND:-iptables}"
NODE_PORT="${NODE_PORT:-51820}"
PREV_IP_FORWARD="${PREV_IP_FORWARD:-0}"
INPUT_ADDED="${INPUT_ADDED:-0}"
NAT_ADDED="${NAT_ADDED:-0}"
FWD_OUT_ADDED="${FWD_OUT_ADDED:-0}"
FWD_IN_ADDED="${FWD_IN_ADDED:-0}"
UPNP_ADDED="${UPNP_ADDED:-0}"
UPNP_PROTOCOL="${UPNP_PROTOCOL:-UDP}"

if [[ -n "${WAN_IFACE}" ]]; then
  if [[ "${BACKEND}" == "nft" ]]; then
    if [[ "${INPUT_ADDED}" == "1" || "${NAT_ADDED}" == "1" || "${FWD_OUT_ADDED}" == "1" || "${FWD_IN_ADDED}" == "1" ]]; then
      nft delete table ip dvpn 2>/dev/null || true
    fi
  else
    if [[ "${INPUT_ADDED}" == "1" ]]; then
      iptables -D INPUT -i "${WAN_IFACE}" -p udp --dport "${NODE_PORT}" -j ACCEPT 2>/dev/null || true
    fi
    if [[ "${NAT_ADDED}" == "1" ]]; then
      iptables -t nat -D POSTROUTING -o "${WAN_IFACE}" -j MASQUERADE 2>/dev/null || true
    fi
    if [[ "${FWD_OUT_ADDED}" == "1" ]]; then
      iptables -D FORWARD -i wg0 -o "${WAN_IFACE}" -j ACCEPT 2>/dev/null || true
    fi
    if [[ "${FWD_IN_ADDED}" == "1" ]]; then
      iptables -D FORWARD -i "${WAN_IFACE}" -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || true
    fi
  fi
fi

if [[ "${UPNP_ADDED}" == "1" ]] && command -v upnpc >/dev/null 2>&1; then
  upnpc -d "${NODE_PORT}" "${UPNP_PROTOCOL^^}" >/dev/null 2>&1 || true
fi

sysctl -w net.ipv4.ip_forward="${PREV_IP_FORWARD}" >/dev/null || true
rm -f "${STATE_FILE}"

echo "Forwarding/NAT restored to previous state."
