#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

install_docker_linux() {
  if have_cmd docker; then
    return
  fi
  if have_cmd curl; then
    curl -fsSL https://get.docker.com | sh
  elif have_cmd wget; then
    wget -qO- https://get.docker.com | sh
  else
    echo "Missing curl/wget for Docker bootstrap" >&2
    exit 1
  fi
}

install_docker_macos() {
  if have_cmd docker; then
    return
  fi
  if have_cmd brew; then
    brew install --cask docker
    open -a Docker || true
  else
    echo "Install Docker Desktop manually, then rerun: https://www.docker.com/products/docker-desktop/" >&2
    exit 1
  fi
}

wait_for_docker() {
  for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
      return
    fi
    sleep 2
  done
  echo "Docker daemon did not become ready" >&2
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
    ./scripts/provider_enable_forwarding.sh "${iface}" || true
    return
  fi
  if have_cmd sudo; then
    sudo -n ./scripts/provider_enable_forwarding.sh "${iface}" || \
      echo "Provider forwarding not enabled automatically (sudo prompt required). Run: sudo ./scripts/provider_enable_forwarding.sh ${iface}"
  else
    echo "Provider forwarding not enabled automatically (sudo unavailable). Run as root: ./scripts/provider_enable_forwarding.sh ${iface}"
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
    ./scripts/strict_firewall_enable.sh "${iface}" || true
    return
  fi
  if have_cmd sudo; then
    sudo -n ./scripts/strict_firewall_enable.sh "${iface}" || \
      echo "Strict firewall not enabled automatically (sudo prompt required). Run: sudo ./scripts/strict_firewall_enable.sh ${iface}"
  else
    echo "Strict firewall not enabled automatically (sudo unavailable). Run as root: ./scripts/strict_firewall_enable.sh ${iface}"
  fi
}

case "$(uname -s)" in
  Linux*) install_docker_linux ;;
  Darwin*) install_docker_macos ;;
  *)
    echo "Unsupported OS for one-click.sh. Use one-click.ps1 on Windows." >&2
    exit 1
    ;;
esac

wait_for_docker

python3 scripts/prepare_env.py
./scripts/gen_dev_certs.sh

docker compose up -d --build
maybe_enable_provider_forwarding
maybe_enable_strict_firewall
echo "DVPN started. Check status: docker compose ps"
