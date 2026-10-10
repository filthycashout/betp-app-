#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${ROOT_DIR}/integrations/upstreams.lock.json"
VENDOR_DIR="${ROOT_DIR}/integrations/vendor"

python3 "${ROOT_DIR}/scripts/validate_upstreams_lock.py"

rm -rf "${VENDOR_DIR}"
mkdir -p "${VENDOR_DIR}"

clone_exact() {
  local name="$1"
  local url="$2"
  local sha="$3"
  local dest="${VENDOR_DIR}/${name}"

  mkdir -p "${dest}"
  git -C "${dest}" init -q
  git -C "${dest}" remote add origin "${url}"
  git -C "${dest}" -c protocol.version=2 fetch -q --depth 1 origin "${sha}"
  git -C "${dest}" checkout -q --detach FETCH_HEAD

  local actual
  actual="$(git -C "${dest}" rev-parse HEAD)"
  if [[ "${actual}" != "${sha}" ]]; then
    echo "ERROR: ${name} resolved to ${actual}; expected ${sha}" >&2
    exit 1
  fi
  printf '%s %s\n' "${name}" "${actual}"
}

mapfile -t LOCKED_REPOS < <(
  python3 - "${LOCK_FILE}" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for item in data["repositories"]:
    if item.get("clone_group") == "sports":
        print("\t".join((item["name"], item["url"], item["commit"])))
PY
)

if [[ "${#LOCKED_REPOS[@]}" -ne 25 ]]; then
  echo "ERROR: expected 25 sports repositories (source indexes 3-27), got ${#LOCKED_REPOS[@]}" >&2
  exit 1
fi

for entry in "${LOCKED_REPOS[@]}"; do
  IFS=$'\t' read -r name url sha <<< "${entry}"
  clone_exact "${name}" "${url}" "${sha}"
done

find "${VENDOR_DIR}" -type d -name .git -prune -exec rm -rf {} +

actual_count="$(find "${VENDOR_DIR}" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
if [[ "${actual_count}" != "25" ]]; then
  echo "ERROR: expected 25 cloned directories, got ${actual_count}" >&2
  exit 1
fi

echo "Pinned upstream repositories 3-27 cloned into ${VENDOR_DIR}"
