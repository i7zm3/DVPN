#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

if [[ ! -f .env.prod ]]; then
  cp .env.prod.example .env.prod
  echo "Created .env.prod from template. Fill production endpoints/tokens before rerunning."
  exit 0
fi

docker compose -f docker-compose.prod.yml up -d --build
echo "Production stack started. Check: docker compose -f docker-compose.prod.yml ps"
