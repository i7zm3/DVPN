#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${ROOT}"
IMAGE="${DVPN_IMAGE:-dvpn-node:portable}"
TAR="${DIST_DIR}/dvpn-node-image.tar.gz"
DATA_DIR="${HOME}/.dvpn-node"
ENV_FILE="${DATA_DIR}/.env"
CONTAINER="dvpn-node"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

install_docker_linux() {
  if have_cmd docker; then return; fi
  if have_cmd curl; then
    curl -fsSL https://get.docker.com | sh
  elif have_cmd wget; then
    wget -qO- https://get.docker.com | sh
  else
    echo "Missing curl/wget for Docker bootstrap." >&2
    exit 1
  fi
}

install_docker_macos() {
  if have_cmd docker; then return; fi
  if have_cmd brew; then
    brew install --cask docker
    open -a Docker || true
  else
    echo "Install Docker Desktop manually, then rerun." >&2
    exit 1
  fi
}

wait_for_docker() {
  for _ in $(seq 1 90); do
    if docker info >/dev/null 2>&1; then
      return
    fi
    sleep 2
  done
  echo "Docker daemon did not become ready." >&2
  exit 1
}

detect_wan_iface() {
  ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}'
}

maybe_enable_provider_forwarding() {
  if [[ "${ENABLE_PROVIDER_FORWARDING:-true}" != "true" ]]; then
    return
  fi
  if [[ "$(uname -s)" != "Linux" ]]; then
    return
  fi
  local iface
  iface="$(detect_wan_iface || true)"
  if [[ -z "${iface}" ]]; then
    echo "Provider forwarding skipped: unable to detect WAN interface."
    return
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    "${DIST_DIR}/provider_enable_forwarding.sh" "${iface}" || true
    return
  fi
  if have_cmd sudo; then
    sudo -n "${DIST_DIR}/provider_enable_forwarding.sh" "${iface}" || \
      echo "Provider forwarding not enabled automatically (sudo prompt required). Run: sudo ${DIST_DIR}/provider_enable_forwarding.sh ${iface}"
  else
    echo "Provider forwarding not enabled automatically (sudo unavailable). Run as root: ${DIST_DIR}/provider_enable_forwarding.sh ${iface}"
  fi
}

maybe_enable_strict_firewall() {
  if [[ "${STRICT_FIREWALL:-true}" != "true" ]]; then
    return
  fi
  if [[ "$(uname -s)" != "Linux" ]]; then
    return
  fi
  local iface
  iface="$(detect_wan_iface || true)"
  if [[ -z "${iface}" ]]; then
    echo "Strict firewall skipped: unable to detect WAN interface."
    return
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    "${DIST_DIR}/strict_firewall_enable.sh" "${iface}" || true
    return
  fi
  if have_cmd sudo; then
    sudo -n "${DIST_DIR}/strict_firewall_enable.sh" "${iface}" || \
      echo "Strict firewall not enabled automatically (sudo prompt required). Run: sudo ${DIST_DIR}/strict_firewall_enable.sh ${iface}"
  else
    echo "Strict firewall not enabled automatically (sudo unavailable). Run as root: ${DIST_DIR}/strict_firewall_enable.sh ${iface}"
  fi
}

if ! have_cmd docker; then
  case "$(uname -s)" in
    Linux*) install_docker_linux ;;
    Darwin*) install_docker_macos ;;
    *)
      echo "Unsupported OS. Install Docker manually and rerun." >&2
      exit 1
      ;;
  esac
fi

wait_for_docker

mkdir -p "${DATA_DIR}"

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  if [[ ! -f "${TAR}" ]]; then
    echo "Missing image archive: ${TAR}" >&2
    exit 1
  fi
  gzip -dc "${TAR}" | docker load >/dev/null
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  RAND() { tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 32; }
  WG_KEY="$(docker run --rm --entrypoint sh "${IMAGE}" -lc 'wg genkey')"
  cat > "${ENV_FILE}" <<ENV
POOL_URL=https://api.dvpn.lol/providers
PAYMENT_API_URL=https://api.dvpn.lol/verify
PAYMENT_PORTAL_URL=https://api.dvpn.lol/portal
PAYMENT_TOKEN=$(RAND)
USER_ID=user-$(RAND | head -c 12)
WG_PRIVATE_KEY=${WG_KEY}
WG_ADDRESS=10.66.0.2/32
WG_DNS=
WG_PERSISTENT_KEEPALIVE=25
SOCKS_PORT=1080
CONNECT_TIMEOUT_SECONDS=5
RETRY_SECONDS=15
ENDPOINT_ROTATE_SECONDS=240
ENDPOINT_ROTATE_JITTER_SECONDS=45
ENABLE_TRAY=false
CONTROL_HOST=127.0.0.1
CONTROL_PORT=8765
TOKEN_STORE_PATH=/var/lib/dvpn/token.store
TOKEN_STORE_PASSPHRASE=$(RAND)
MESH_SAMPLE_SIZE=3
LOG_STDOUT=false
AUDIT_ENABLED=false
FALLBACK_ENABLED=true
FALLBACK_SCRIPT_PATH=/app/scripts/setup_fallback_node.sh
FALLBACK_ORCHESTRATOR_URL=https://api.dvpn.lol
FALLBACK_TIMEOUT_SECONDS=30
AUTO_NETWORK_CONFIG=true
UPNP_ENABLED=true
NODE_REGISTER_ENABLED=true
NODE_ID=node-$(RAND | head -c 12)
NODE_PORT=51820
NODE_PUBLIC_ENDPOINT=
ALLOW_PRIVATE_ENDPOINTS=false
BANDWIDTH_TEST_URL=https://speed.cloudflare.com/__down?bytes=25000000
BANDWIDTH_SAMPLE_SECONDS=4
BANDWIDTH_TOTAL_MBPS=0
ENABLE_WIREGUARD=true
WG_QUICK_CMD=wg-quick
WG_CONFIG_PATH=/tmp/dvpn/wg0.conf
ENABLE_SOCKS=false
DANTED_CMD=danted
DANTED_TEMPLATE_PATH=/app/scripts/danted.conf.template
DANTED_CONFIG_PATH=/tmp/dvpn/danted.conf
ENV
fi

docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
docker run -d \
  --name "${CONTAINER}" \
  --restart unless-stopped \
  --privileged \
  --log-driver=none \
  --device /dev/net/tun:/dev/net/tun \
  --env-file "${ENV_FILE}" \
  -p 8765:8765 \
  -p 51820:51820/udp \
  -v "${DATA_DIR}:/var/lib/dvpn" \
  "${IMAGE}" >/dev/null

maybe_enable_provider_forwarding
maybe_enable_strict_firewall

echo "DVPN started in container '${CONTAINER}'."
echo "Status: docker logs --tail 60 ${CONTAINER}"
echo "Health: curl http://127.0.0.1:8765/health"
