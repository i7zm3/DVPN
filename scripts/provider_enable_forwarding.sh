#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

WAN_IFACE="${1:-}"
STATE_FILE="${DVPN_FORWARD_STATE_FILE:-/tmp/dvpn-provider-forwarding.state}"
BACKEND="${PROVIDER_FW_BACKEND:-auto}"
SCOPE="${PROVIDER_NETWORK_SCOPE:-host}"
NODE_PORT="${NODE_PORT:-51820}"
UPNP_ENABLE="${PROVIDER_UPNP_ENABLE:-true}"
UPNP_PROTOCOL="${PROVIDER_UPNP_PROTOCOL:-UDP}"
if [[ -z "${WAN_IFACE}" ]]; then
  WAN_IFACE="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
fi
if [[ -z "${WAN_IFACE}" ]]; then
  echo "Unable to auto-detect WAN interface. Usage: $0 <wan_iface>" >&2
  exit 1
fi

if ! ip link show "${WAN_IFACE}" >/dev/null 2>&1; then
  echo "Interface not found: ${WAN_IFACE}" >&2
  exit 1
fi

if [[ "${SCOPE}" == "host" && -f /.dockerenv ]]; then
  echo "Warning: running inside container but PROVIDER_NETWORK_SCOPE=host. Apply this on the host namespace instead." >&2
fi

if [[ "${BACKEND}" == "auto" ]]; then
  if command -v nft >/dev/null 2>&1; then
    BACKEND="nft"
  else
    BACKEND="iptables"
  fi
fi

prev_ipf="$(sysctl -n net.ipv4.ip_forward 2>/dev/null || echo 0)"

nat_added=0
fwd_out_added=0
fwd_in_added=0
input_added=0
upnp_added=0
upnp_local_ip=""

if [[ "${BACKEND}" == "nft" ]]; then
  nft add table ip dvpn 2>/dev/null || true
  nft "add chain ip dvpn input { type filter hook input priority 0; policy accept; }" 2>/dev/null || true
  nft "add chain ip dvpn forward { type filter hook forward priority 0; policy accept; }" 2>/dev/null || true
  nft "add chain ip dvpn postrouting { type nat hook postrouting priority srcnat; policy accept; }" 2>/dev/null || true
  nft add rule ip dvpn input iifname "${WAN_IFACE}" udp dport "${NODE_PORT}" accept 2>/dev/null || true
  nft add rule ip dvpn postrouting oifname "${WAN_IFACE}" masquerade 2>/dev/null || true
  nft add rule ip dvpn forward iifname "wg0" oifname "${WAN_IFACE}" accept 2>/dev/null || true
  nft add rule ip dvpn forward iifname "${WAN_IFACE}" oifname "wg0" ct state related,established accept 2>/dev/null || true
  input_added=1
  nat_added=1
  fwd_out_added=1
  fwd_in_added=1
else
  if ! iptables -C INPUT -i "${WAN_IFACE}" -p udp --dport "${NODE_PORT}" -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 1 -i "${WAN_IFACE}" -p udp --dport "${NODE_PORT}" -j ACCEPT
    input_added=1
  fi
  if ! iptables -t nat -C POSTROUTING -o "${WAN_IFACE}" -j MASQUERADE 2>/dev/null; then
    iptables -t nat -A POSTROUTING -o "${WAN_IFACE}" -j MASQUERADE
    nat_added=1
  fi

  if ! iptables -C FORWARD -i wg0 -o "${WAN_IFACE}" -j ACCEPT 2>/dev/null; then
    iptables -A FORWARD -i wg0 -o "${WAN_IFACE}" -j ACCEPT
    fwd_out_added=1
  fi

  if ! iptables -C FORWARD -i "${WAN_IFACE}" -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
    iptables -A FORWARD -i "${WAN_IFACE}" -o wg0 -m state --state RELATED,ESTABLISHED -j ACCEPT
    fwd_in_added=1
  fi
fi

sysctl -w net.ipv4.ip_forward=1 >/dev/null

if [[ "${UPNP_ENABLE,,}" == "true" ]] && command -v upnpc >/dev/null 2>&1; then
  upnp_local_ip="$(ip -4 -o addr show dev "${WAN_IFACE}" | awk '{print $4}' | head -n1 | cut -d/ -f1)"
  if [[ -n "${upnp_local_ip}" ]]; then
    if upnpc -e "DVPN" -a "${upnp_local_ip}" "${NODE_PORT}" "${NODE_PORT}" "${UPNP_PROTOCOL^^}" >/dev/null 2>&1; then
      upnp_added=1
    fi
  fi
fi

cat > "${STATE_FILE}" <<EOF
WAN_IFACE=${WAN_IFACE}
BACKEND=${BACKEND}
NODE_PORT=${NODE_PORT}
PREV_IP_FORWARD=${prev_ipf}
INPUT_ADDED=${input_added}
NAT_ADDED=${nat_added}
FWD_OUT_ADDED=${fwd_out_added}
FWD_IN_ADDED=${fwd_in_added}
UPNP_ADDED=${upnp_added}
UPNP_PROTOCOL=${UPNP_PROTOCOL^^}
UPNP_LOCAL_IP=${upnp_local_ip}
EOF

echo "Forwarding enabled (${BACKEND}): wg0 <-> ${WAN_IFACE}"
if [[ "${input_added}" == "1" ]]; then
  echo "Firewall opened: ${WAN_IFACE} udp/${NODE_PORT}"
fi
if [[ "${upnp_added}" == "1" ]]; then
  echo "UPnP mapping added: ${NODE_PORT}/${UPNP_PROTOCOL^^} -> ${upnp_local_ip}:${NODE_PORT}"
fi
echo "State saved: ${STATE_FILE}"
