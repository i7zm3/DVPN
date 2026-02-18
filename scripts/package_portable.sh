#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

IMAGE="${DVPN_IMAGE:-dvpn-node:portable}"
DIST="${ROOT}/dist"
BUILD_NETWORK="${DVPN_BUILD_NETWORK:-host}"

mkdir -p "${DIST}"

docker build --network="${BUILD_NETWORK}" -t "${IMAGE}" .
docker save "${IMAGE}" | gzip -1 > "${DIST}/dvpn-node-image.tar.gz"

cp scripts/portable_run.sh "${DIST}/one-click-run.sh"
cp scripts/portable_run.ps1 "${DIST}/one-click-run.ps1"
cp scripts/portable_stop.sh "${DIST}/one-click-stop.sh"
cp scripts/portable_stop.ps1 "${DIST}/one-click-stop.ps1"
cp scripts/provider_enable_forwarding.sh "${DIST}/provider_enable_forwarding.sh"
cp scripts/provider_disable_forwarding.sh "${DIST}/provider_disable_forwarding.sh"
cp scripts/strict_firewall_enable.sh "${DIST}/strict_firewall_enable.sh"
cp scripts/strict_firewall_disable.sh "${DIST}/strict_firewall_disable.sh"
cp README.md "${DIST}/README.md"
cp INSTALL.md "${DIST}/INSTALL.md"
mkdir -p "${DIST}/docs"
cp docs/info.html "${DIST}/docs/info.html"
chmod +x "${DIST}/one-click-run.sh"
chmod +x "${DIST}/one-click-stop.sh"
chmod +x "${DIST}/provider_enable_forwarding.sh"
chmod +x "${DIST}/provider_disable_forwarding.sh"
chmod +x "${DIST}/strict_firewall_enable.sh"
chmod +x "${DIST}/strict_firewall_disable.sh"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "${DIST}" && sha256sum dvpn-node-image.tar.gz > dvpn-node-image.tar.gz.sha256)
fi

echo "Portable bundle ready in: ${DIST}"
ls -lh "${DIST}" | sed -n '1,20p'
