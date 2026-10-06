#!/usr/bin/env bash
set -euo pipefail

APK="${1:-/sdcard/Download/app-release.apk}"
OUTPUT="${2:-device-report-physical}"

cat <<'EOF'
PhilthySports phone-only physical smoke
This path is intended for Termux on the same physical Android phone.
It uses Android Wireless debugging; no PC is required.
EOF

if ! command -v adb >/dev/null 2>&1; then
  echo "ERROR: adb is not installed in Termux." >&2
  echo "Install it with: pkg update && pkg install android-tools python git -y" >&2
  exit 2
fi
if ! command -v python >/dev/null 2>&1; then
  echo "ERROR: python is not installed in Termux." >&2
  echo "Install it with: pkg install python -y" >&2
  exit 2
fi
if [ ! -f "$APK" ]; then
  echo "ERROR: APK not found: $APK" >&2
  echo "Download the signed release APK to the phone, then pass its path as argument 1." >&2
  echo "Example: bash ci/run_phone_only_physical_proof.sh /sdcard/Download/PhilthyParleys.apk" >&2
  exit 2
fi

SERIAL="${ADB_SERIAL:-}"
if [ -z "$SERIAL" ]; then
  SERIAL="$(adb devices | awk 'NR>1 && $2=="device" && $1 !~ /^emulator-/ {print $1; exit}')"
fi

if [ -z "$SERIAL" ]; then
  cat >&2 <<'EOF'
ERROR: no authorized physical Android device is visible to adb.

Phone-only setup:
1. Connect the phone to Wi-Fi.
2. Settings > Developer options > Wireless debugging > On.
3. Tap "Pair device with pairing code" and note the shown IP:pairing-port and code.
4. In Termux run: adb pair IP:PAIRING_PORT
5. Enter the pairing code.
6. Back on the Wireless debugging page, note the main IP address & port.
7. In Termux run: adb connect IP:DEBUG_PORT
8. Verify with: adb devices
9. Re-run this script.

Do not share the pairing code or full adb serial.
EOF
  exit 3
fi

MODEL="$(adb -s "$SERIAL" shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
QEMU="$(adb -s "$SERIAL" shell getprop ro.kernel.qemu 2>/dev/null | tr -d '\r')"
if [ "$QEMU" = "1" ]; then
  echo "ERROR: adb target is an emulator, not a physical phone." >&2
  exit 4
fi

echo "Authorized physical target detected: ${MODEL:-unknown model}"
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

cat <<EOF

PASS output is in: $OUTPUT
Share only these files for minimum proof:
  $OUTPUT/device-smoke.json
  $OUTPUT/launch.png
The report does not store the adb serial.
EOF
