#!/usr/bin/env python3
"""Generate the 1024x1024 iOS app icon from the dashboard's Tran T icon.

App Store icons must be square, 1024x1024, and fully opaque (no alpha), so this
flattens any transparency onto a solid background. Re-run after changing the
source icon:

    python3 ios/scripts/make-appicon.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "monitor/src/battery_monitor/static/assets/tran-t-icon.png"
DEST = ROOT / "ios/App/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png"
BACKGROUND = (18, 19, 21)  # #121315, matching the dashboard's dark ground


def main() -> int:
    if not SOURCE.exists():
        print(f"source icon not found: {SOURCE}", file=sys.stderr)
        return 1

    icon = Image.open(SOURCE).convert("RGBA")
    canvas = Image.new("RGB", (1024, 1024), BACKGROUND)
    resized = icon.resize((1024, 1024), Image.LANCZOS)
    canvas.paste(resized, (0, 0), mask=resized.split()[3])

    DEST.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(DEST, format="PNG")
    print(f"wrote {DEST.relative_to(ROOT)} ({canvas.size[0]}x{canvas.size[1]}, opaque)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
