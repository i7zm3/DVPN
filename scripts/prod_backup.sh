#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

BACKUP_DIR="${1:-${ROOT}/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "${BACKUP_DIR}"

DATA_OUT="${BACKUP_DIR}/dvpn_data-${STAMP}.tar.gz"
WG_OUT="${BACKUP_DIR}/dvpn_wg-${STAMP}.tar.gz"

echo "[prod-backup] Backing up dvpn_data -> ${DATA_OUT}"
docker run --rm \
  -v dvpn_dvpn_data:/src:ro \
  -v "${BACKUP_DIR}:/backup" \
  alpine:3.20 sh -lc "tar -czf /backup/$(basename "${DATA_OUT}") -C /src ."

echo "[prod-backup] Backing up dvpn_wg -> ${WG_OUT}"
docker run --rm \
  -v dvpn_dvpn_wg:/src:ro \
  -v "${BACKUP_DIR}:/backup" \
  alpine:3.20 sh -lc "tar -czf /backup/$(basename "${WG_OUT}") -C /src ."

echo "[prod-backup] Completed"
