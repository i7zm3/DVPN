#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <dvpn_data tar.gz> <dvpn_wg tar.gz>" >&2
  exit 1
fi

DATA_ARCHIVE="$1"
WG_ARCHIVE="$2"

if [[ ! -f "${DATA_ARCHIVE}" || ! -f "${WG_ARCHIVE}" ]]; then
  echo "Missing backup archive(s)" >&2
  exit 1
fi

echo "[prod-restore] Stopping production service"
docker compose -f docker-compose.prod.yml stop dvpn >/dev/null 2>&1 || true

echo "[prod-restore] Restoring dvpn_data from ${DATA_ARCHIVE}"
docker run --rm \
  -v dvpn_dvpn_data:/dst \
  -v "$(dirname "${DATA_ARCHIVE}"):/backup:ro" \
  alpine:3.20 sh -lc "rm -rf /dst/* && tar -xzf /backup/$(basename "${DATA_ARCHIVE}") -C /dst"

echo "[prod-restore] Restoring dvpn_wg from ${WG_ARCHIVE}"
docker run --rm \
  -v dvpn_dvpn_wg:/dst \
  -v "$(dirname "${WG_ARCHIVE}"):/backup:ro" \
  alpine:3.20 sh -lc "rm -rf /dst/* && tar -xzf /backup/$(basename "${WG_ARCHIVE}") -C /dst"

echo "[prod-restore] Starting production service"
docker compose -f docker-compose.prod.yml up -d dvpn

echo "[prod-restore] Completed"
