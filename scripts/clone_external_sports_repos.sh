#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${ROOT_DIR}/integrations/vendor"
mkdir -p "${VENDOR_DIR}"

clone_exact() {
  local name="$1"
  local url="$2"
  local sha="$3"
  local dest="${VENDOR_DIR}/${name}"

  rm -rf "${dest}"
  mkdir -p "${dest}"
  git -C "${dest}" init -q
  git -C "${dest}" remote add origin "${url}"
  git -C "${dest}" fetch -q --depth 1 origin "${sha}"
  git -C "${dest}" checkout -q --detach FETCH_HEAD

  local actual
  actual="$(git -C "${dest}" rev-parse HEAD)"
  if [[ "${actual}" != "${sha}" ]]; then
    echo "ERROR: ${name} resolved to ${actual}; expected ${sha}" >&2
    exit 1
  fi
  echo "${name} ${actual}"
}

clone_exact "draftfast" "https://github.com/BenBrostoff/draftfast.git" "0f5f1f2eb6e2ba7cb4cb6813ee36a3a079369a9b"
clone_exact "odds-api" "https://github.com/odds-api/odds-api.git" "1b8d4bdddf01c610eb725dc610f12ab53a20dba8"
clone_exact "fanduel-api" "https://github.com/Setfive/fanduel-api.git" "c4b9b746555b2f7d5b4a15a747cc82c724109db4"
clone_exact "SportradarAPIs" "https://github.com/johnwmillr/SportradarAPIs.git" "b23e020a29ce7eb792c637ff8e6d34940e1587f1"

find "${VENDOR_DIR}" -type d -name .git -prune -exec rm -rf {} +

echo "Pinned upstream repositories cloned into ${VENDOR_DIR}"
