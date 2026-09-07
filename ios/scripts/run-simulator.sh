#!/usr/bin/env bash
# One command to see the app running: generate the project, build for the
# Simulator (no signing/Apple account needed), install, and launch.
#   ./scripts/run-simulator.sh ["iPhone 15"]
set -euo pipefail

cd "$(dirname "$0")/.."
SIM_NAME="${1:-iPhone 15}"
PROJECT="BatteryMonitor.xcodeproj"
SCHEME="BatteryMonitor"

./scripts/bootstrap.sh
xcodegen generate

echo "Building for Simulator ($SIM_NAME)…"
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,name=${SIM_NAME}" \
  -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO \
  build

APP_PATH="$(find build/Build/Products/Debug-iphonesimulator -maxdepth 1 -name '*.app' | head -1)"
if [[ -z "$APP_PATH" ]]; then
  echo "Build product (.app) not found." >&2
  exit 1
fi
BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$APP_PATH/Info.plist")"

open -a Simulator
xcrun simctl boot "$SIM_NAME" >/dev/null 2>&1 || true
xcrun simctl install booted "$APP_PATH"
xcrun simctl launch booted "$BUNDLE_ID"
echo "Launched $BUNDLE_ID in the $SIM_NAME simulator."
