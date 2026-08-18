from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from battery_monitor.assets import BUILD_TOKEN, asset_version, cache_control_for, render_index

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "monitor" / "src" / "battery_monitor" / "static"


class FrontendContractTests(unittest.TestCase):
    def test_build_version_prevents_stale_asset_deployments(self) -> None:
        html = render_index(STATIC / "index.html", "abc123")

        self.assertNotIn(BUILD_TOKEN, html)
        self.assertIn("/static/app.js?v=abc123", html)
        self.assertIn("/static/styles.css?v=abc123", html)
        self.assertEqual(cache_control_for("/", None, "abc123"), "no-store")
        self.assertEqual(
            cache_control_for("/static/app.js", "abc123", "abc123"),
            "public, max-age=31536000, immutable",
        )
        self.assertEqual(
            cache_control_for("/static/app.js", "old", "abc123"), "no-cache"
        )

        fingerprint = asset_version("abc123", STATIC)
        self.assertRegex(fingerprint, r"^abc123-[0-9a-f]{12}$")
        self.assertEqual(fingerprint, asset_version("abc123", STATIC))

        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            asset = fixture / "app.js"
            asset.write_text("first", encoding="utf-8")
            first_version = asset_version("same-commit", fixture)
            asset.write_text("second", encoding="utf-8")
            self.assertNotEqual(first_version, asset_version("same-commit", fixture))

    def test_refresh_loop_is_controlled_and_visibility_aware(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("setInterval(", javascript)
        self.assertIn("Promise.allSettled", javascript)
        self.assertIn("AbortController", javascript)
        self.assertIn('document.addEventListener("visibilitychange"', javascript)
        self.assertIn("ResizeObserver", javascript)

    def test_history_and_soc_controls_are_interactive_and_accessible(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="chartTooltip"', html)
        self.assertIn('id="historyChart"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('id="fleetSocBar"', html)
        self.assertIn('role="progressbar"', html)
        self.assertIn('chart.addEventListener("pointermove"', javascript)
        self.assertIn("moveChartKeyboardSelection", javascript)
        self.assertIn("formatChartTimestamp", javascript)
        self.assertIn("energyFlowPresentation", javascript)
        self.assertIn("operation_status", javascript)
        self.assertIn("@keyframes soc-flow-sweep", css)
        self.assertIn(".soc-progress--charging", css)
        self.assertIn(".soc-progress--discharging", css)
        self.assertIn(".chart-tooltip[data-mobile=\"true\"]", css)

    def test_layout_contracts_cover_target_viewports(self) -> None:
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        contracts = {
            320: ["width: calc(100% - 16px)", "@media (max-width: 480px)"],
            768: ["@media (max-width: 1120px)", "grid-template-columns: 1fr"],
            1024: ["@media (max-width: 1120px)", "grid-template-columns: 1fr"],
            1440: ["width: min(1480px", "repeat(3, minmax(0, 1fr))"],
        }
        for viewport, markers in contracts.items():
            with self.subTest(viewport=viewport):
                for marker in markers:
                    self.assertIn(marker, css)

        self.assertIn("@container inventory (max-width: 760px)", css)
        self.assertIn('<details id="payloadDetails"', html)
        self.assertNotIn('<details id="payloadDetails" open', html)
        self.assertNotIn('<h2 id="rackName">Eco-worthy Rack</h2>', html)
        self.assertIn("grid-template-columns: minmax(190px, 0.5fr)", css)
        self.assertIn('id="rackDescription">Waiting for rack status', html)
        self.assertIn('"All batteries online"', (STATIC / "app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
