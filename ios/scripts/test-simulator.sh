#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
bash scripts/bootstrap.sh
xcodegen generate

DEVICE_ID="$(xcrun simctl list devices available | awk -F '[()]' '/iPhone/{print $2; exit}')"
[[ -n "$DEVICE_ID" ]] || { echo "Install an iPhone Simulator runtime in Xcode." >&2; exit 1; }

xcodebuild \
  -project BatteryMonitor.xcodeproj \
  -scheme BatteryMonitor \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,id=$DEVICE_ID" \
  -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO \
  test

