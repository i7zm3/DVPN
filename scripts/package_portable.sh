#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

IMAGE="${DVPN_IMAGE:-dvpn-node:portable}"
DIST="${ROOT}/dist"

mkdir -p "${DIST}"

docker build -t "${IMAGE}" .
docker save "${IMAGE}" | gzip -1 > "${DIST}/dvpn-node-image.tar.gz"

cp scripts/portable_run.sh "${DIST}/one-click-run.sh"
cp scripts/portable_run.ps1 "${DIST}/one-click-run.ps1"
cp README.md "${DIST}/README.md"
cp INSTALL.md "${DIST}/INSTALL.md"
mkdir -p "${DIST}/docs"
cp docs/info.html "${DIST}/docs/info.html"
chmod +x "${DIST}/one-click-run.sh"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "${DIST}" && sha256sum dvpn-node-image.tar.gz > dvpn-node-image.tar.gz.sha256)
fi

echo "Portable bundle ready in: ${DIST}"
ls -lh "${DIST}" | sed -n '1,20p'
