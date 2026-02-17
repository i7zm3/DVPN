#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

have_cmd() { command -v "$1" >/dev/null 2>&1; }

if ! have_cmd python3; then
  echo "python3 is required" >&2
  exit 1
fi

if have_cmd sudo && sudo -n true >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y wireguard-tools dante-server miniupnpc python3-venv python3-pip
else
  echo "sudo unavailable/non-functional; skipping system package install"
fi

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-native.txt

python3 scripts/build_icons.py || true
python3 scripts/prepare_env.py
echo "Native setup completed"
