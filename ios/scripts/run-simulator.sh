#!/usr/bin/env bash
# One command to see the app running: generate the project, build for the
# Simulator (no signing/Apple account needed), then install + launch on an
# available iPhone simulator.
#   ./scripts/run-simulator.sh                 # auto-pick an iPhone simulator
#   ./scripts/run-simulator.sh "iPhone 16 Pro" # prefer a specific one
set -euo pipefail

cd "$(dirname "$0")/.."
REQUESTED="${1:-}"
PROJECT="BatteryMonitor.xcodeproj"
SCHEME="BatteryMonitor"

# xcodebuild needs a full Xcode; the Command Line Tools alone are not enough.
if ! xcodebuild -version >/dev/null 2>&1; then
  ACTIVE="$(xcode-select -p 2>/dev/null || echo none)"
  XCODE_APP="$(ls -d /Applications/Xcode*.app 2>/dev/null | head -1 || true)"
  echo "" >&2
  echo "xcodebuild can't run — the active developer dir is: $ACTIVE" >&2
  echo "(that's the Command Line Tools; a full Xcode is required)." >&2
  if [ -n "$XCODE_APP" ]; then
    echo "" >&2
    echo "Fix it (asks for your password), then re-run 'make run':" >&2
    echo "  sudo xcode-select -s \"$XCODE_APP/Contents/Developer\"" >&2
  else
    echo "" >&2
    echo "Xcode isn't installed. Get it from the App Store, then re-run:" >&2
    echo "  https://apps.apple.com/app/xcode/id497799835" >&2
  fi
  echo "" >&2
  exit 1
fi

./scripts/bootstrap.sh
xcodegen generate

# Build with a device-agnostic destination so it never depends on which named
# simulators happen to exist on this machine.
echo "Building for the iOS Simulator…"
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO \
  build

APP_PATH="$(find build/Build/Products/Debug-iphonesimulator -maxdepth 1 -name '*.app' | head -1)"
if [[ -z "$APP_PATH" ]]; then
  echo "Build product (.app) not found." >&2
  exit 1
fi
BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$APP_PATH/Info.plist")"

# Choose a simulator: a booted one first, then the requested name, then any iPhone.
udid_of() { awk -F '[()]' "$1{print \$2; exit}"; }
DEVICE_ID="$(xcrun simctl list devices booted 2>/dev/null | udid_of '/iPhone/')"
if [[ -z "$DEVICE_ID" && -n "$REQUESTED" ]]; then
  DEVICE_ID="$(xcrun simctl list devices available | grep -F "$REQUESTED" | udid_of '1')"
  [[ -z "$DEVICE_ID" ]] && echo "Simulator '$REQUESTED' not found; using the first available iPhone." >&2
fi
if [[ -z "$DEVICE_ID" ]]; then
  DEVICE_ID="$(xcrun simctl list devices available | udid_of '/iPhone/')"
fi
if [[ -z "$DEVICE_ID" ]]; then
  echo "No iOS Simulator is installed. Open Xcode → Settings → Components and add an iOS runtime." >&2
  exit 1
fi

open -a Simulator
xcrun simctl boot "$DEVICE_ID" >/dev/null 2>&1 || true
xcrun simctl install "$DEVICE_ID" "$APP_PATH"
xcrun simctl launch "$DEVICE_ID" "$BUNDLE_ID"
DEVICE_NAME="$(xcrun simctl list devices | grep -F "$DEVICE_ID" | sed -E 's/ *\(.*//' | head -1)"
echo "Launched $BUNDLE_ID on:${DEVICE_NAME}"
