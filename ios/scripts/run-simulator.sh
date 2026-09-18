#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
REQUESTED="${1:-}"

if ! xcodebuild -version >/dev/null 2>&1; then
  ACTIVE="$(xcode-select -p 2>/dev/null || echo none)"
  XCODE_APP="$(ls -d /Applications/Xcode*.app 2>/dev/null | head -1 || true)"
  echo "xcodebuild cannot run; active developer directory: $ACTIVE" >&2
  if [[ -n "$XCODE_APP" ]]; then
    echo "Run: sudo xcode-select -s \"$XCODE_APP/Contents/Developer\"" >&2
  else
    echo "Install the full Xcode app, then run make run again." >&2
  fi
  exit 1
fi

bash scripts/bootstrap.sh
xcodegen generate
xcodebuild -project BatteryMonitor.xcodeproj -scheme BatteryMonitor \
  -configuration Debug -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO build

APP_PATH="$(find build/Build/Products/Debug-iphonesimulator -maxdepth 1 -name '*.app' | head -1)"
[[ -n "$APP_PATH" ]] || { echo "Simulator app was not produced." >&2; exit 1; }
BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$APP_PATH/Info.plist")"

udid_of() { awk -F '[()]' "$1{print \$2; exit}"; }
DEVICE_ID="$(xcrun simctl list devices booted 2>/dev/null | udid_of '/iPhone/')"
if [[ -z "$DEVICE_ID" && -n "$REQUESTED" ]]; then
  DEVICE_ID="$(xcrun simctl list devices available | grep -F "$REQUESTED" | udid_of '1')"
fi
if [[ -z "$DEVICE_ID" ]]; then
  DEVICE_ID="$(xcrun simctl list devices available | udid_of '/iPhone/')"
fi
[[ -n "$DEVICE_ID" ]] || { echo "Install an iOS Simulator runtime in Xcode." >&2; exit 1; }

open -a Simulator
xcrun simctl boot "$DEVICE_ID" >/dev/null 2>&1 || true
xcrun simctl install "$DEVICE_ID" "$APP_PATH"
xcrun simctl launch "$DEVICE_ID" "$BUNDLE_ID"

