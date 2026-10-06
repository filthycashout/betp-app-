#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${ROOT_DIR}/integrations/vendor"
DEST="${VENDOR_DIR}/bytecode-viewer"
URL="https://github.com/Konloch/bytecode-viewer.git"
SHA="31430e0033fa220db566b5ef461256727ff6793b"

rm -rf "${DEST}"
mkdir -p "${DEST}"
git -C "${DEST}" init -q
git -C "${DEST}" remote add origin "${URL}"
git -C "${DEST}" config core.sparseCheckout true
cat > "${DEST}/.git/info/sparse-checkout" <<'EOF'
/README.md
/pom.xml
/src/main/java/the/bytecode/club/bytecodeviewer/BytecodeViewer.java
/src/main/java/the/bytecode/club/bytecodeviewer/cli/BCVCommandLine.java
/src/main/java/the/bytecode/club/bytecodeviewer/plugin/PluginManager.java
/src/main/java/the/bytecode/club/bytecodeviewer/api/BCV.java
/src/main/java/the/bytecode/club/bytecodeviewer/api/Plugin.java
/plugins/java/Skeleton.java
EOF

git -C "${DEST}" -c protocol.version=2 fetch -q --depth 1 --filter=blob:none origin "${SHA}"
git -C "${DEST}" checkout -q --detach FETCH_HEAD
ACTUAL="$(git -C "${DEST}" rev-parse HEAD)"
if [[ "${ACTUAL}" != "${SHA}" ]]; then
  echo "ERROR: bytecode-viewer resolved to ${ACTUAL}; expected ${SHA}" >&2
  exit 1
fi

test -f "${DEST}/pom.xml"
test -f "${DEST}/README.md"
test -f "${DEST}/src/main/java/the/bytecode/club/bytecodeviewer/api/BCV.java"
test -f "${DEST}/src/main/java/the/bytecode/club/bytecodeviewer/api/Plugin.java"

grep -q '<version>2.13.2</version>' "${DEST}/pom.xml"
grep -q 'public class BCV' "${DEST}/src/main/java/the/bytecode/club/bytecodeviewer/api/BCV.java"
grep -q 'execute(List<ClassNode>' "${DEST}/src/main/java/the/bytecode/club/bytecodeviewer/api/Plugin.java"

printf 'bytecode-viewer %s\n' "${ACTUAL}"
