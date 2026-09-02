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
        self.assertIn("/static/energy-flow.js?v=abc123", html)
        self.assertIn("/static/vendor/three.module.min.js?v=abc123", html)
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
        self.assertIn('id="fleetCurrent"', html)
        self.assertIn('id="fleetVoltage"', html)
        self.assertIn('id="fleetMosfetTemp"', html)
        self.assertIn('id="fleetAmbientTemp"', html)
        self.assertIn('id="fleetHealth"', html)
        self.assertNotIn('id="rackLocation"', html)
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
        self.assertIn('id="rackDescription"', html)
        self.assertIn('data-i18n="rack.waitingStatus">Waiting for rack status', html)
        self.assertIn('"All batteries online"', (STATIC / "app.js").read_text(encoding="utf-8"))

    def test_language_switch_localizes_live_ui_and_persists_preference(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="languageToggle"', html)
        self.assertIn('role="switch"', html)
        self.assertIn('data-i18n="app.title"', html)
        self.assertIn("battery-monitor-language", html)
        self.assertIn("battery-monitor-language", javascript)
        self.assertIn("function applyLanguage", javascript)
        self.assertIn("function rerenderLocalizedUi", javascript)
        self.assertIn('"page.title": "Giám sát hệ thống pin"', javascript)
        self.assertIn('"status.collectorOnline": "Bộ thu thập trực tuyến"', javascript)
        self.assertIn('Intl.RelativeTimeFormat(currentLocale()', javascript)
        self.assertIn(".language-toggle__track", css)
        self.assertIn(".preference-controls", css)

    def test_three_dimensional_energy_flow_is_live_and_resilient(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        scene = (STATIC / "energy-flow.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="energyFlowCanvas"', html)
        self.assertIn('type="importmap"', html)
        self.assertIn('type="module" src="/static/energy-flow.js', html)
        self.assertIn('CustomEvent("battery-energy-flow"', javascript)
        self.assertIn("function renderEnergyFlow", javascript)
        self.assertIn("packTelemetry", javascript)
        self.assertIn('"energy.title": "Dòng điện trong nhà"', javascript)
        self.assertIn('import * as THREE from "three"', scene)
        self.assertIn("THREE.WebGLRenderer", scene)
        self.assertIn("THREE.OrthographicCamera", scene)
        self.assertIn("THREE.CatmullRomCurve3", scene)
        self.assertIn("function createRenogySystem", scene)
        self.assertIn("function createHouseShell", scene)
        self.assertIn("function createSolarArray", scene)
        self.assertIn("function createPowerCenter", scene)
        self.assertIn("function createUtilityPole", scene)
        self.assertIn("function createFlowNetwork", scene)
        self.assertIn("function createFlowRoute", scene)
        self.assertIn("function configureRoute", scene)
        self.assertIn("const activeCount = active ? 1 : 0", scene)
        self.assertIn("particle.scale.setScalar(endpointFade)", scene)
        self.assertIn("new THREE.SphereGeometry(0.072, 16, 12)", scene)
        self.assertIn('configureRoute(network.grid, "stale", 0, false, 1, false)', scene)
        self.assertIn('configureRoute(network.load, "stale", 0, false, 1, false)', scene)
        self.assertIn("const fillLight = new THREE.DirectionalLight", scene)
        self.assertIn("fillLight.intensity = dark ?", scene)
        self.assertIn("network.battery", scene)
        self.assertIn('canvas.dataset.topology = "home-grid-solar-inverter-battery-load"', scene)
        self.assertIn('canvas.dataset.sceneStyle = "isometric-home-energy"', scene)
        self.assertIn('canvas.dataset.camera = "orthographic"', scene)
        self.assertIn('canvas.dataset.sourceTelemetry = direct ? "inverter" : "battery-only"', scene)
        self.assertIn('? "inverter-to-battery"', scene)
        self.assertIn('? "battery-to-inverter"', scene)
        self.assertIn("canvas.dataset.activeRoutes", scene)
        self.assertIn("IntersectionObserver", scene)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', scene)
        self.assertIn('canvas.addEventListener("webglcontextlost"', scene)
        self.assertIn("gl.readPixels", scene)
        self.assertIn('.energy-flow[data-mode="charging"]', css)
        self.assertIn('.energy-flow[data-mode="discharging"]', css)
        self.assertIn(".energy-flow.is-fallback", css)
        self.assertIn("@keyframes energy-flow-fallback-horizontal", css)
        self.assertIn("@keyframes energy-flow-fallback-vertical", css)
        self.assertIn("border-radius: 50%", css)
        self.assertIn('id="energyGridValue"', html)
        self.assertIn('id="energySolarValue"', html)
        self.assertIn('id="energyInverterValue"', html)
        self.assertIn('id="energyBatteryValue"', html)
        self.assertIn('id="energyLoadValue"', html)
        self.assertIn("energy-flow__system-state", html)
        self.assertIn("energy-flow__callout--bottom", html)
        self.assertIn(".energy-flow__callout--solar", css)
        self.assertIn("--callout-color: #f2ef50", css)
        self.assertIn("--callout-color: #ffdf87", css)
        self.assertIn("@keyframes energy-flow-leader-pulse", css)
        self.assertIn("text-shadow: 0 1px 2px rgba(0, 0, 0, 0.94)", css)

        self.assertTrue((STATIC / "vendor" / "three.module.min.js").is_file())
        self.assertTrue((STATIC / "vendor" / "three.core.min.js").is_file())
        self.assertTrue((STATIC / "vendor" / "three-LICENSE.txt").is_file())
        self.assertIn(
            "Version: `0.185.1`",
            (STATIC / "vendor" / "README.md").read_text(encoding="utf-8"),
        )

    def test_inverter_telemetry_drives_live_metrics_and_power_routes(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        scene = (STATIC / "energy-flow.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn("state.inverter = payload.snapshot?.inverter || null", javascript)
        self.assertIn("function renderInverterTelemetry", javascript)
        self.assertIn("function inverterTelemetry", javascript)
        self.assertIn("grid_import_power_w", javascript)
        self.assertIn("grid_export_power_w", javascript)
        self.assertIn("pv_total_power_w", javascript)
        self.assertIn("load_total_power_w", javascript)
        self.assertIn("home_load_total_power_w", javascript)
        self.assertIn("battery_power_w", javascript)
        self.assertIn('id="inverterBand"', html)
        self.assertIn('id="inverterGridPower"', html)
        self.assertIn('id="inverterSolarPower"', html)
        self.assertIn('id="inverterLoadPower"', html)
        self.assertIn('id="inverterBatteryPower"', html)
        self.assertIn('data-inverter-available="false"', html)
        self.assertIn(".inverter-band", css)
        self.assertIn('.energy-flow[data-inverter-available="false"]', css)
        self.assertIn("flowState.inverterAvailable", scene)
        self.assertIn("routeMagnitude(flowState.gridPower)", scene)
        self.assertIn("routeMagnitude(flowState.solarPower)", scene)
        self.assertIn("routeMagnitude(flowState.loadPower)", scene)
        self.assertIn("routeMagnitude(flowState.batteryPower)", scene)
        self.assertIn("NODE_COLORS.grid", scene)
        self.assertIn("NODE_COLORS.solar", scene)
        self.assertIn("NODE_COLORS.load", scene)
        self.assertIn('"inverter.state.bypass": "Điện lưới chuyển thẳng"', javascript)

    def test_energy_history_has_hour_date_month_and_year_views(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="energyHistoryChart"', html)
        self.assertIn('id="energyConsumptionTotal"', html)
        self.assertIn('id="energySolarTotal"', html)
        self.assertIn('id="energyGridTotal"', html)
        self.assertIn('id="energyHistoryTotals"', html)
        self.assertIn('id="energyConsumptionPeriod"', html)
        self.assertIn('id="energySolarPeriod"', html)
        self.assertIn('id="energyGridPeriod"', html)
        self.assertIn('data-energy-view="hour"', html)
        self.assertIn('data-energy-view="date"', html)
        self.assertIn('data-energy-view="month"', html)
        self.assertIn('data-energy-view="year"', html)
        self.assertIn('getJson(`/api/energy?${params}`, "energy")', javascript)
        self.assertIn("function drawEnergyHistoryChart", javascript)
        self.assertIn('field: "consumption_kwh"', javascript)
        self.assertIn('field: "solar_generation_kwh"', javascript)
        self.assertIn('field: "grid_import_kwh"', javascript)
        self.assertIn("function latestEnergyHistoryPoint", javascript)
        self.assertIn("state.energySummaryPeriod = latestEnergyHistoryPoint", javascript)
        self.assertIn('"energyHistory.kwhPeriod": "kWh · {period}"', javascript)
        self.assertIn('"energyHistory.titleMonth": "Năng lượng theo tháng"', javascript)
        self.assertIn(".energy-history-layout", css)
        self.assertIn("#energyHistoryChart", css)

    def test_power_history_overlays_inverter_sources_and_demand(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="powerSeriesControls"', html)
        self.assertIn('data-power-series="grid_power_w"', html)
        self.assertIn('data-power-series="battery_power_w"', html)
        self.assertIn('data-power-series="solar_power_w"', html)
        self.assertIn('data-power-series="load_power_w"', html)
        self.assertNotIn('id="metricSelect"', html)
        self.assertIn('getJson(`/api/power-history?${params}`, "history")', javascript)
        self.assertIn("function formatPowerHistoryValue", javascript)
        self.assertIn('"history.importing"', javascript)
        self.assertIn('"history.discharging"', javascript)
        self.assertIn(".power-series-toggle", css)
        self.assertIn(".chart-tooltip--power", css)

    def test_default_configured_labels_are_localized_in_vietnamese(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-i18n-alt="logo.alt"', html)
        self.assertIn("function localizedBatteryName", javascript)
        self.assertIn("function localizedBatteryModel", javascript)
        self.assertIn("function localizedCollectorName", javascript)
        self.assertIn("function localizedConnectionName", javascript)
        self.assertIn('"battery.defaultRackName": "Pin {number}"', javascript)
        self.assertIn('"inventory.defaultModel": "Pin tủ máy chủ Eco-worthy"', javascript)
        self.assertIn('"rack.defaultConnection": "Modbus RTU qua RS485"', javascript)
        self.assertIn("localizedBatteryName(profile?.name || battery.id)", javascript)


if __name__ == "__main__":
    unittest.main()
