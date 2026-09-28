from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from battery_monitor.assets import BUILD_TOKEN, asset_version, cache_control_for, render_index

ROOT = Path(__file__).resolve().parents[1]
MONITOR = Path(__file__).resolve().parents[1] / "monitor/src/battery_monitor"
STATIC = ROOT / "monitor" / "src" / "battery_monitor" / "static"


class FrontendContractTests(unittest.TestCase):
    def test_build_version_prevents_stale_asset_deployments(self) -> None:
        html = render_index(STATIC / "index.html", "abc123")

        self.assertNotIn(BUILD_TOKEN, html)
        self.assertIn("/static/app.js?v=abc123", html)
        self.assertIn("/static/styles.css?v=abc123", html)
        self.assertIn("/static/home-scene.js?v=abc123", html)
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
        self.assertIn("grid-template-columns: minmax(320px, 0.95fr)", css)
        # Rack identity/status was folded into the Rack summary card.
        self.assertIn('class="rack-summary__meta"', html)
        self.assertNotIn('class="rack-overview"', html)
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

    def test_collector_host_readout_is_present_and_localised(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        # One quiet line under the connection detail, hidden until it has data.
        self.assertIn('id="collectorHost" class="connection-host" hidden', html)
        self.assertIn("function renderHostStats(", javascript)
        self.assertIn("renderHostStats(payload.snapshot?.host, payload.collector_status)", javascript)
        # Every label exists in both languages.
        for key in ("host.label", "host.cpu", "host.memory", "host.disk", "host.throttled", "host.tooltip"):
            with self.subTest(key=key):
                self.assertEqual(javascript.count(f'"{key}":'), 2)
        for selector in (".connection-host {", ".connection-host__item--warm", ".connection-host__item--hot",
                         ':root[data-theme="dark"] .connection-host__item--hot'):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)

    def test_rack_overview_animates_eco_worthy_packs_and_their_flow(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        scene = (STATIC / "rack-flow.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        # The Rack overview carries its own WebGL stage, loaded like the home scene.
        self.assertIn('id="rackSummarySection"', html)
        self.assertIn('id="rackFlowStage"', html)
        self.assertIn('id="rackFlowCanvas"', html)
        self.assertIn('type="module" src="/static/rack-flow.js', html)
        self.assertIn('data-rack-packs="[]"', html)
        self.assertLess(
            html.index('id="rackFlowStage"'), html.index('class="rack-summary__soc"')
        )

        # The dashboard feeds it per-pack telemetry.
        self.assertIn("function renderRackFlow", javascript)
        self.assertIn('CustomEvent("battery-rack-flow"', javascript)
        self.assertIn("section.dataset.rackPacks = JSON.stringify(packs)", javascript)
        self.assertIn("function packHasAlert", javascript)
        self.assertIn("const RACK_SCENE_MAX_PACKS = 8", javascript)
        self.assertIn('"rack.flowEyebrow": "Rack energy flow"', javascript)
        self.assertIn('"rack.flowEyebrow": "Dòng năng lượng tủ pin"', javascript)
        self.assertIn("Eco-worthy 48 V LiFePO4", javascript)

        # The stage holds Eco-worthy packs and their conduits, and nothing else.
        self.assertIn('import * as THREE from "three"', scene)
        self.assertIn("THREE.WebGLRenderer", scene)
        self.assertIn("THREE.OrthographicCamera", scene)
        self.assertIn("THREE.LineCurve3", scene)
        self.assertIn("function createBatteryModule", scene)
        self.assertIn("function createRackNetwork", scene)
        self.assertIn("function createStraightPath", scene)
        self.assertIn("function createFlowRoute", scene)
        self.assertIn("function configureRoute", scene)
        self.assertIn("function brandTexture", scene)
        self.assertIn("function drawModuleScreen", scene)
        self.assertIn('canvas.dataset.topology = "packs-and-bus-only"', scene)
        self.assertIn('canvas.dataset.hardware = "eco-worthy-rack"', scene)
        self.assertIn('ctx.fillText("ECO", 78, 62)', scene)
        self.assertIn('ctx.fillText("-WORTHY", 200, 62)', scene)
        self.assertIn("LiFePO4  48V  100Ah", scene)
        # Nothing from the home scene's cast is modelled here: no house, no solar
        # array, no utility pole, no inverter, no metered grid or load.
        for absent in (
            "createHouseShell",
            "createSolarArray",
            "createUtilityPole",
            "createPowerCenter",
            "windowMaterial",
            "homeGlow",
            "inverterSignalMaterial",
            "gridPower",
            "solarPower",
            "loadPower",
        ):
            self.assertNotIn(absent, scene)

        # Pulses share the home scene's constant-speed model and flow palette.
        self.assertIn("const speed = pulseProgressRate(route, pulseSpeed)", scene)
        self.assertIn("length: Math.max(curve.getLength(), 0.001)", scene)
        self.assertIn("const PULSE_REFERENCE_LENGTH = 3.5", scene)
        self.assertIn("charging: 0xd9ff3f", scene)
        self.assertIn("discharging: 0xff6258", scene)
        self.assertIn('"energy-pulse-speed-change"', scene)
        self.assertIn('"energy-line-glow-change"', scene)
        self.assertIn('"energy-glow-change"', scene)
        self.assertIn("function mirrorSceneSetting", javascript)

        # Same resilience contract as the home scene.
        self.assertIn("IntersectionObserver", scene)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', scene)
        self.assertIn('canvas.addEventListener("webglcontextlost"', scene)
        self.assertIn("function showFallback", scene)
        self.assertIn("function disposeObject", scene)
        self.assertIn(".rack-summary.is-rack-fallback .rack-flow__fallback", css)
        self.assertIn("@keyframes rack-flow-fallback-cell", css)
        self.assertIn('.rack-summary[data-rack-mode="charging"] .rack-flow', css)
        self.assertIn('.rack-summary[data-rack-mode="discharging"] .rack-flow', css)
        self.assertIn(".rack-flow__copy", css)

    def test_illustrated_home_scene_is_live_and_lit_by_the_sun(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        scene = (STATIC / "home-scene.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        # The hero is one illustrated SVG built by the scene module, fed by the
        # same event and section attributes the dashboard already maintains.
        self.assertIn('id="homeScene"', html)
        self.assertIn('type="module" src="/static/home-scene.js', html)
        self.assertNotIn("energy-flow.js", html)
        self.assertNotIn('id="energyFlowCanvas"', html)
        self.assertIn('CustomEvent("battery-energy-flow"', javascript)
        self.assertIn('CustomEvent("battery-weather"', javascript)
        self.assertIn("function renderEnergyFlow", javascript)
        self.assertIn("packTelemetry", javascript)
        self.assertIn('"energy.title": "Dòng điện trong nhà"', javascript)
        self.assertIn('window.addEventListener("battery-energy-flow"', scene)
        self.assertIn('window.addEventListener("battery-weather"', scene)

        # Lit by the real sun: the NOAA position, recomputed from the feed's
        # coordinates, with a clock fallback and a preview override.
        self.assertIn("function solarPosition(date, latitude, longitude)", scene)
        self.assertIn("function clockSolarPosition", scene)
        self.assertIn("function scenePhase", scene)
        self.assertIn("function skyPalette", scene)
        self.assertIn("function sunScreenPosition", scene)
        self.assertIn('params.get("sceneClock")', scene)
        for phase in ("night", "dawn", "golden", "day"):
            with self.subTest(phase=phase):
                self.assertIn(f'.energy-flow[data-phase="{phase}"]', css)

        # The parts that answer to data: sky, stars, sun and moon, clouds by
        # cover, windows and porch lamp by light, panel glints while producing,
        # the cabinet's charge gauge and LEDs, and the five conduits.
        for marker in ("function buildScene", "function house", "function batteryCabinet",
                       "function inverterBox", "function utilityPole", "function flows",
                       "function flowsFor", "hs-panel-glint", "hsSocFill", "hs-led",
                       "hsLampGlow", "hs-window", "animateMotion"):
            with self.subTest(marker=marker):
                self.assertIn(marker, scene)
        self.assertIn("const ROUTES = {", scene)
        for route in ("solar", "battery", "home", "backup", "grid"):
            with self.subTest(route=route):
                self.assertIn(f"\n  {route}: `M ", scene)

        # Motion respects the viewer and the viewport.
        self.assertIn("IntersectionObserver", scene)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', scene)
        self.assertIn("@keyframes hs-flow-dash", css)
        self.assertIn("@keyframes hs-twinkle", css)
        self.assertIn("@keyframes hs-drift", css)
        self.assertIn("@keyframes hs-glint", css)
        self.assertIn(".energy-flow.is-offscreen", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

        # The callouts keep their ids, so the live renderers are untouched.
        for element_id in ("energyGridValue", "energySolarValue", "energySolarDetail",
                           "energyInverterValue", "energyBatteryValue", "energyLoadValue",
                           "energyBackupValue", "energyWeather", "energyWeatherTemperature",
                           "energyWeatherSolar"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', html)
        self.assertIn(
            '`${formatValue(inverter.solarVoltage, "V")} · '
            '${formatValue(inverter.solarCurrent, "A")}`',
            javascript,
        )
        self.assertIn('href="https://open-meteo.com/"', html)

    def test_inverter_telemetry_drives_live_metrics_and_power_routes(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        scene = (STATIC / "home-scene.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn("state.inverter = payload.snapshot?.inverter || null", javascript)
        self.assertIn("function renderInverterTelemetry", javascript)
        self.assertIn("function inverterTelemetry", javascript)
        self.assertIn("function rackBatteryTelemetry", javascript)
        self.assertIn("const battery = rackBatteryTelemetry()", javascript)
        self.assertIn('section.dataset.batterySource = "direct-battery-telemetry"', javascript)
        self.assertNotIn("inverter.batteryPower", javascript)
        self.assertNotIn("reading.battery_voltage_v", javascript)
        self.assertNotIn("reading.battery_current_a", javascript)
        self.assertNotIn("reading.battery_soc_percent", javascript)
        self.assertNotIn("reading.battery_temperature_c", javascript)
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
        self.assertIn('data-i18n="inverter.battery">Battery rack', html)
        self.assertIn('data-inverter-available="false"', html)
        self.assertIn(".inverter-band", css)
        self.assertIn('.energy-flow[data-inverter-available="false"]', css)
        # The scene routes power only from the inverter's meters, and rests the
        # solar, grid and home conduits when the inverter is not reporting.
        self.assertIn("const inverter = Boolean(input.inverterAvailable)", scene)
        self.assertIn('flow("solar", inverter ? solar : 0', scene)
        self.assertIn('flow("grid", inverter ? grid : 0', scene)
        self.assertIn('flow("home", inverter ? load : 0', scene)
        self.assertIn('flow("battery", batteryKnown ? battery : 0', scene)
        self.assertIn("FLOW_COLORS.grid", scene)
        self.assertIn("FLOW_COLORS.solar", scene)
        self.assertIn("FLOW_COLORS.load", scene)
        self.assertIn('"inverter.state.bypass": "Điện lưới chuyển thẳng"', javascript)

    def test_energy_history_has_hour_date_month_and_year_views(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="energyHistoryChart"', html)
        self.assertIn('id="energyHistoryTooltip"', html)
        self.assertIn('aria-describedby="energyHistoryTooltip"', html)
        self.assertIn('id="energyConsumptionTotal"', html)
        self.assertIn('id="energySolarTotal"', html)
        self.assertIn('id="energyGridTotal"', html)
        self.assertIn('id="energyHistoryTotals"', html)
        self.assertIn('id="energyConsumptionPeriod"', html)
        self.assertIn('id="energySolarPeriod"', html)
        self.assertIn('id="energyGridPeriod"', html)
        self.assertIn('id="energyDateInput"', html)
        self.assertIn('id="energyDateControl"', html)
        self.assertIn('data-energy-view="hour"', html)
        self.assertIn('data-energy-view="date"', html)
        self.assertIn('data-energy-view="month"', html)
        self.assertIn('data-energy-view="year"', html)
        self.assertIn('getJson(`/api/energy?${params}`, "energy")', javascript)
        self.assertIn("function drawEnergyHistoryChart", javascript)
        self.assertIn("function renderEnergyChartTooltip", javascript)
        self.assertIn("function updateEnergyChartHoverFromClient", javascript)
        self.assertIn('new Date(`${point.period}-15T12:00:00Z`)', javascript)
        self.assertIn('bindChartInspection(energyChart, $("energyHistoryTooltip")', javascript)
        self.assertIn('chart.addEventListener("pointerup"', javascript)
        self.assertIn('chart.addEventListener("pointercancel"', javascript)
        self.assertIn('[data-dismiss-chart]', javascript)
        self.assertIn("moveEnergyChartKeyboardSelection", javascript)
        self.assertIn('field: "consumption_kwh"', javascript)
        self.assertIn('field: "solar_generation_kwh"', javascript)
        self.assertIn('field: "grid_import_kwh"', javascript)
        self.assertIn("function latestEnergyHistoryPoint", javascript)
        self.assertIn("function sumEnergyHistoryPoints", javascript)
        self.assertIn('params.set("date", requestedDate)', javascript)
        self.assertIn('params.set("timezone", state.energyTimezone)', javascript)
        self.assertIn("function localCalendarDateValue", javascript)
        self.assertIn('canvas.dataset.chartType = "overlapping-areas"', javascript)
        self.assertIn("function drawEnergyAreaSeries", javascript)
        # The areas are smoothed with monotone cubics, so corners round off without
        # the curve overshooting a reading or dipping below the zero baseline.
        self.assertIn("function energyCurveTangents", javascript)
        self.assertIn("function traceEnergyCurve", javascript)
        self.assertIn("ctx.bezierCurveTo(", javascript)
        self.assertIn('id="energyChartScroll"', html)
        self.assertIn("function energyAxisMaximum", javascript)
        self.assertIn("state.energySummaryPeriod = latestEnergyHistoryPoint", javascript)
        self.assertIn('"energyHistory.kwhPeriod": "kWh · {period}"', javascript)
        self.assertIn('"energyHistory.titleMonth": "Năng lượng tháng này"', javascript)
        self.assertIn(".energy-history-layout", css)
        self.assertIn("#energyHistoryChart", css)
        self.assertIn(".chart-tooltip--energy", css)
        self.assertIn(".energy-tooltip__row", css)

    def test_energy_savings_uses_logged_energy_and_pse_rate_metadata(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="energySavingsSection"', html)
        self.assertIn('id="savingsEstimate"', html)
        self.assertIn('data-savings-period="date"', html)
        self.assertIn('id="savingsDateInput"', html)
        self.assertIn('id="savingsDateControl"', html)
        self.assertIn('data-savings-period="retained"', html)
        self.assertIn('getJson(`/api/savings?${params}`, "savings")', javascript)
        self.assertIn('date: requestedDate', javascript)
        self.assertIn("function renderSavings", javascript)
        self.assertIn('"savings.title": "Energy Savings"', javascript)
        self.assertIn('"savings.title": "Tiết kiệm năng lượng"', javascript)
        self.assertIn(".savings-layout", css)
        self.assertIn(".savings-tariff", css)

        # Schedule 327 prices by the clock, so the panel shows a per-period
        # breakdown and one exact figure instead of a tier range.
        self.assertIn('id="savingsTouRows"', html)
        self.assertIn('id="savingsCurrentPeriod"', html)
        self.assertIn('id="savingsCurrentRate"', html)
        self.assertIn("function renderSavingsTou", javascript)
        self.assertIn("function savingsFigure", javascript)
        self.assertIn("function formatRate", javascript)
        self.assertIn('"savings.periodSuperOffPeak": "Super off-peak"', javascript)
        self.assertIn('"savings.periodSuperOffPeak": "Giờ siêu thấp điểm"', javascript)
        self.assertIn(
            '"savings.windowOnPeak": "Weekdays 7–10 AM, 5–8 PM · not holidays"',
            javascript,
        )
        # Off-peak is two weekday blocks, not one 7 a.m.-11 p.m. run; that shape
        # only holds on a weekend or holiday.
        self.assertIn(
            '"savings.windowOffPeak": "10 AM–5 PM, 8–11 PM · weekends all day"',
            javascript,
        )
        self.assertIn(".savings-tou__row", css)

        # Grid purchase cost per period, and the donut that divides the whole.
        self.assertIn('data-i18n="savings.touGridCost"', html)
        self.assertIn('id="savingsTouTotalGridCost"', html)
        self.assertIn('id="savingsDonutChart"', html)
        self.assertIn('id="savingsDonutLegend"', html)
        self.assertIn('id="savingsDonutTotal"', html)
        self.assertIn("function renderSavingsDonut", javascript)
        self.assertIn("function donutArcPath", javascript)
        self.assertIn("cost_without_solar_usd", (MONITOR / "savings.py").read_text(encoding="utf-8"))
        self.assertIn('"savings.donutSolar": "Solar offset"', javascript)
        self.assertIn('"savings.donutSolar": "Mặt trời bù đắp"', javascript)
        # The chart palette is its own token set, validated against each surface
        # rather than reusing the interface status colours.
        for token in ("--tou-on-peak", "--tou-off-peak", "--tou-super-off-peak", "--tou-solar"):
            self.assertEqual(css.count(f"{token}:"), 2, f"{token} needs a light and a dark step")
        self.assertIn(".savings-donut__arc", css)
        # The donut is described for screen readers and repeated as a table.
        self.assertIn('id="savingsDonutDesc"', html)
        self.assertIn('role="img"', html)
        # One period-colour mapping, shared by the table dots and the donut.
        self.assertIn('[data-tou="on_peak"] {', css)
        self.assertIn("--tou-colour: var(--tou-on-peak)", css)
        # The tier range is gone from the markup, the strings and the code.
        for retired in ("savingsTierLimit", "savings.tierThreshold", "Schedule 7"):
            self.assertNotIn(retired, html)
        for retired in (
            "formatCurrencyRange",
            "renderPrimaryCurrencyRange",
            "tier_1_limit_kwh",
            "savings.rangeSeparator",
        ):
            self.assertNotIn(retired, javascript)

    def test_live_views_show_estimated_battery_support_time(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="energyBatteryRuntime"', html)
        self.assertIn('id="inverterBatteryRuntime"', html)
        self.assertIn("const BATTERY_RESERVE_PERCENT = 20", javascript)
        self.assertIn("remaining_capacity_ah", javascript)
        self.assertIn("function usableBatteryEnergyWh", javascript)
        self.assertIn("remainingCapacity - reserveCapacity", javascript)
        self.assertIn("usableEnergyWh / Math.abs(power)", javascript)
        # Discharge floor is configurable to match the inverter's depth of discharge.
        self.assertIn("function batteryReservePercent", javascript)
        self.assertIn("payload.ui?.battery_reserve_percent", javascript)
        self.assertIn("to {reserve}% charge at this discharge rate", javascript)
        self.assertIn("function formatBatteryRuntime", javascript)
        self.assertIn('"energy.runtimeRemaining"', javascript)
        # Charging-side counterpart, derived from the pack's depth of discharge.
        self.assertIn("const BATTERY_CHARGE_CEILING_PERCENT = 100", javascript)
        self.assertIn("function chargeDeficitEnergyWh", javascript)
        self.assertIn("function depthOfDischargePercent", javascript)
        self.assertIn("function batteryTimeEstimate", javascript)
        self.assertIn("chargeDeficitWh / power", javascript)
        self.assertIn('"energy.chargeFullRemaining"', javascript)
        self.assertIn("until full at this charge rate", javascript)
        self.assertIn(".energy-flow__runtime", css)
        self.assertIn(".inverter-runtime", css)

    def test_battery_packs_show_mosfet_limiting_and_balancing_state(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function packSwitchesHtml", javascript)
        # Sourced from the BMS mosfet_state bits and the balance_status_mask.
        self.assertIn('mosfet.includes("charge")', javascript)
        self.assertIn('mosfet.includes("discharge")', javascript)
        self.assertIn('mosfet.includes("current_limiting")', javascript)
        self.assertIn("reading.balance_status_mask", javascript)
        # This BMS reports 0 as the equalizing state, not non-zero.
        self.assertIn("balanceMask === 0", javascript)
        self.assertIn('"battery.chargeMos": "Charge MOS"', javascript)
        self.assertIn('"battery.dischargeMos": "Discharge MOS"', javascript)
        self.assertIn('"battery.limiting": "Limiting"', javascript)
        self.assertIn('"battery.equalizing": "Equalizing"', javascript)
        self.assertIn('"battery.notEqualizing": "Not equalizing"', javascript)
        self.assertIn(".pack-switch", css)
        self.assertIn(".pack__switches", css)

    def test_power_history_overlays_inverter_sources_and_demand(self) -> None:
        javascript = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="powerSeriesControls"', html)
        self.assertIn('data-range="date"', html)
        self.assertIn('id="powerDateControl"', html)
        self.assertIn('id="powerDateInput"', html)
        self.assertIn('data-power-series="grid_power_w"', html)
        self.assertIn('data-power-series="battery_power_w"', html)
        self.assertIn('data-power-series="solar_power_w"', html)
        self.assertIn('data-power-series="load_power_w"', html)
        self.assertIn('data-power-series="home_load_power_w"', html)
        # Live energy flow leads, with the power-history chart below it.
        self.assertLess(html.index('id="energyFlowSection"'), html.index('id="powerHistorySection"'))
        self.assertNotIn('id="metricSelect"', html)
        self.assertIn('getJson(`/api/power-history?${params}`, "history")', javascript)
        self.assertIn('params.set("date", requestedDate)', javascript)
        self.assertIn('params.set("timezone", state.powerTimezone)', javascript)
        self.assertIn("state.powerWindowStart", javascript)
        self.assertIn("state.powerWindowEnd", javascript)
        self.assertIn('powerTimeTick(unix, ratio)', javascript)
        self.assertIn('"history.battery": "Battery rack"', javascript)
        self.assertIn("function renderChartTooltip", javascript)
        self.assertIn("function updateChartHoverFromClient", javascript)
        self.assertIn("if (points.length <= 80)", javascript)
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
