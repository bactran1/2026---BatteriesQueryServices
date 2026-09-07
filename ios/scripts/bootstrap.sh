#!/usr/bin/env bash
# Ensure XcodeGen is installed (used to generate the .xcodeproj from project.yml).
set -euo pipefail

if command -v xcodegen >/dev/null 2>&1; then
  exit 0
fi

echo "XcodeGen not found — installing…"
if command -v brew >/dev/null 2>&1; then
  brew install xcodegen
elif command -v mint >/dev/null 2>&1; then
  mint install yonaskolb/XcodeGen
else
  cat >&2 <<'EOF'
Could not install XcodeGen automatically (no Homebrew or Mint found).
Install one of:
  brew install xcodegen
  mint install yonaskolb/XcodeGen
See https://github.com/yonaskolb/XcodeGen
EOF
  exit 1
fi
