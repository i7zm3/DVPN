#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

COMPOSE=(docker compose -f docker-compose.prod.yml)

echo "[prod-update] Pulling/building latest image"
"${COMPOSE[@]}" build dvpn

echo "[prod-update] Starting replacement container"
"${COMPOSE[@]}" up -d --no-deps dvpn

echo "[prod-update] Waiting for health"
for _ in $(seq 1 40); do
  health="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' dvpn-prod 2>/dev/null || true)"
  if [[ "${health}" == "healthy" ]]; then
    echo "[prod-update] Service healthy"
    exit 0
  fi
  sleep 3
done

echo "[prod-update] Timed out waiting for healthy container" >&2
exit 1
