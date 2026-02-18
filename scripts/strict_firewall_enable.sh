#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)." >&2
  exit 1
fi

WAN_IFACE="${1:-}"
WG_IFACE="${WG_IFACE:-wg0}"
WG_PORT="${NODE_PORT:-51820}"
WG_FWMARK="${WG_FWMARK:-}"
STATE_FILE="${DVPN_STRICT_FW_STATE_FILE:-/tmp/dvpn-strict-firewall.state}"
ALLOW_CONTROL_PLANE="${STRICT_FW_ALLOW_CONTROL_PLANE:-true}"

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

if [[ -z "${WG_FWMARK}" ]] && command -v wg >/dev/null 2>&1; then
  WG_FWMARK="$(wg show "${WG_IFACE}" fwmark 2>/dev/null || true)"
fi
if [[ -z "${WG_FWMARK}" || "${WG_FWMARK}" == "off" ]]; then
  WG_FWMARK="${WG_PORT}"
fi

parse_host() {
  local url="${1:-}"
  url="${url#*://}"
  url="${url%%/*}"
  url="${url%%:*}"
  printf '%s' "${url}"
}

CONTROL_HOSTS=()
for u in "${POOL_URL:-}" "${PAYMENT_API_URL:-}" "${PAYMENT_PORTAL_URL:-}" "${FALLBACK_ORCHESTRATOR_URL:-}"; do
  h="$(parse_host "${u}")"
  [[ -z "${h}" ]] && continue
  CONTROL_HOSTS+=("${h}")
done

if ((${#CONTROL_HOSTS[@]})); then
  # De-dup
  mapfile -t CONTROL_HOSTS < <(printf '%s\n' "${CONTROL_HOSTS[@]}" | sort -u)
fi

iptables -N DVPN_STRICT_INPUT 2>/dev/null || true
iptables -N DVPN_STRICT_OUTPUT 2>/dev/null || true
iptables -N DVPN_STRICT_FORWARD 2>/dev/null || true

iptables -F DVPN_STRICT_INPUT
iptables -F DVPN_STRICT_OUTPUT
iptables -F DVPN_STRICT_FORWARD

iptables -C INPUT -j DVPN_STRICT_INPUT 2>/dev/null || iptables -I INPUT 1 -j DVPN_STRICT_INPUT
iptables -C OUTPUT -j DVPN_STRICT_OUTPUT 2>/dev/null || iptables -I OUTPUT 1 -j DVPN_STRICT_OUTPUT
iptables -C FORWARD -j DVPN_STRICT_FORWARD 2>/dev/null || iptables -I FORWARD 1 -j DVPN_STRICT_FORWARD

iptables -A DVPN_STRICT_INPUT -i lo -j ACCEPT
iptables -A DVPN_STRICT_INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -A DVPN_STRICT_INPUT -i "${WG_IFACE}" -j ACCEPT
iptables -A DVPN_STRICT_INPUT -i "${WAN_IFACE}" -p udp --dport "${WG_PORT}" -j ACCEPT
iptables -A DVPN_STRICT_INPUT -j DROP

iptables -A DVPN_STRICT_FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -A DVPN_STRICT_FORWARD -i "${WG_IFACE}" -o "${WAN_IFACE}" -j ACCEPT
iptables -A DVPN_STRICT_FORWARD -j DROP

iptables -A DVPN_STRICT_OUTPUT -o lo -j ACCEPT
iptables -A DVPN_STRICT_OUTPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -A DVPN_STRICT_OUTPUT -o "${WG_IFACE}" -j ACCEPT
iptables -A DVPN_STRICT_OUTPUT -m mark --mark "${WG_FWMARK}" -j ACCEPT

if [[ "${ALLOW_CONTROL_PLANE,,}" == "true" ]]; then
  for host in "${CONTROL_HOSTS[@]}"; do
    while IFS= read -r ip; do
      [[ -z "${ip}" ]] && continue
      iptables -A DVPN_STRICT_OUTPUT -o "${WAN_IFACE}" -p tcp -d "${ip}" --dport 443 -j ACCEPT
    done < <(getent ahostsv4 "${host}" | awk '{print $1}' | sort -u)
  done
fi

iptables -A DVPN_STRICT_OUTPUT -j REJECT

cat > "${STATE_FILE}" <<STATE
WAN_IFACE=${WAN_IFACE}
WG_IFACE=${WG_IFACE}
WG_PORT=${WG_PORT}
WG_FWMARK=${WG_FWMARK}
ALLOW_CONTROL_PLANE=${ALLOW_CONTROL_PLANE}
STATE

echo "Strict firewall enabled: inbound only udp/${WG_PORT} on ${WAN_IFACE}, egress only via ${WG_IFACE} (and WG/control-plane exceptions)."
echo "State saved: ${STATE_FILE}"
