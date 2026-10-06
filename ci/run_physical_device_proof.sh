#!/usr/bin/env bash
set -euo pipefail

APK="${1:-build/app/outputs/flutter-apk/app-release.apk}"
OUTPUT="${2:-device-report-physical}"

if ! command -v adb >/dev/null 2>&1; then
  echo "ERROR: adb is not installed. Install Android SDK Platform-Tools first." >&2
  exit 2
fi
if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: python is not installed." >&2
  exit 2
fi
if [ ! -f "$APK" ]; then
  echo "ERROR: APK not found: $APK" >&2
  exit 2
fi

adb devices -l
SERIAL="$(adb devices | awk 'NR>1 && $2=="device" && $1 !~ /^emulator-/ {print $1; exit}')"
if [ -z "$SERIAL" ]; then
  echo "ERROR: no authorized physical Android device is visible to adb." >&2
  echo "Unlock the phone, enable USB debugging, connect USB, and accept the debugging prompt." >&2
  exit 3
fi

rm -rf "$OUTPUT"
python ci/device_smoke.py \
  --apk "$APK" \
  --output "$OUTPUT" \
  --serial "$SERIAL" \
  --require-physical

python - "$OUTPUT/device-smoke.json" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
data=json.loads(p.read_text())
required={
    'passed': True,
    'physical_test': True,
    'install': 'PASS',
    'launch': 'PASS',
    'backend_connection_indicator': 'PASS_CONNECTED',
}
failed={k:(data.get(k),v) for k,v in required.items() if data.get(k)!=v}
if failed:
    raise SystemExit('physical proof did not satisfy required fields: '+repr(failed))
print(json.dumps({
    'physical_device_proof':'PASS',
    'apk_sha256':data.get('apk_sha256'),
    'model':data.get('model'),
    'api_level':data.get('api_level'),
    'sport_tabs':data.get('sport_tabs'),
    'best12_navigation':data.get('best12_navigation'),
    'best3_navigation':data.get('best3_navigation'),
    'evidence_sheet':data.get('evidence_sheet'),
}, indent=2))
PY

echo
echo "Share these two files if you want the minimum proof without sharing your adb serial:"
echo "  $OUTPUT/device-smoke.json"
echo "  $OUTPUT/launch.png"
echo "The report does not store the adb serial."
