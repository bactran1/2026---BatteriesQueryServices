#!/usr/bin/env bash
set -euo pipefail

if command -v xcodegen >/dev/null 2>&1; then
  exit 0
fi

if command -v brew >/dev/null 2>&1; then
  brew install xcodegen
elif command -v mint >/dev/null 2>&1; then
  mint install yonaskolb/XcodeGen
else
  echo "Install XcodeGen with 'brew install xcodegen' and try again." >&2
  exit 1
fi

