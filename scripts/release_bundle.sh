#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

VERSION="${1:-dev}"
OUT_DIR="${ROOT}/dist/${VERSION}"
mkdir -p "${OUT_DIR}"

tar -czf "${OUT_DIR}/dvpn-src-${VERSION}.tar.gz" \
  --exclude .git \
  --exclude .env \
  --exclude .env.prod \
  --exclude __pycache__ \
  --exclude certs/dev-ca.key \
  --exclude certs/dev-server.key \
  .

cp one-click.sh one-click.ps1 one-click-prod.sh one-click-prod.ps1 "${OUT_DIR}/"

(
  cd "${OUT_DIR}"
  sha256sum * > SHA256SUMS.txt
)

echo "Release bundle created at ${OUT_DIR}"
