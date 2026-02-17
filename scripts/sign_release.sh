#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

VERSION="${1:-dev}"
DIST_DIR="${ROOT}/dist/${VERSION}"

if [[ ! -d "${DIST_DIR}" ]]; then
  echo "Missing release directory: ${DIST_DIR}" >&2
  exit 1
fi

if command -v cosign >/dev/null 2>&1; then
  for f in "${DIST_DIR}"/*; do
    [[ -f "${f}" ]] || continue
    cosign sign-blob --yes --output-signature "${f}.sig" "${f}"
  done
  echo "Signed with cosign"
  exit 0
fi

if command -v gpg >/dev/null 2>&1; then
  for f in "${DIST_DIR}"/*; do
    [[ -f "${f}" ]] || continue
    gpg --armor --detach-sign --output "${f}.asc" "${f}"
  done
  echo "Signed with gpg"
  exit 0
fi

echo "No signing tool found (expected cosign or gpg)" >&2
exit 1
