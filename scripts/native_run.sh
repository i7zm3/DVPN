#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [[ ! -d .venv ]]; then
  echo "Missing .venv; run ./scripts/native_setup_linux.sh first" >&2
  exit 1
fi

. .venv/bin/activate

set -a
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi
set +a

export ENABLE_TRAY="${ENABLE_TRAY:-true}"
python -m app.main
