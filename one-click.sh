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
echo "DVPN started. Check status: docker compose ps"
