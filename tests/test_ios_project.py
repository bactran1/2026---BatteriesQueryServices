from __future__ import annotations

import json
import plistlib
import re
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"
APP = IOS / "BatteryMonitor"


class IOSProjectTests(unittest.TestCase):
    def test_universal_project_and_required_sources_exist(self) -> None:
        project = (IOS / "project.yml").read_text(encoding="utf-8")
        self.assertIn('TARGETED_DEVICE_FAMILY: "1,2"', project)
        self.assertIn('iOS: "17.0"', project)
        for relative in (
            "App/BatteryMonitorApp.swift",
            "Models/TelemetryModels.swift",
            "Networking/MonitorAPI.swift",
            "Stores/AppStore.swift",
            "Views/RootView.swift",
            "Views/EnergyFlowView.swift",
            "Views/BatteriesView.swift",
            "Views/HistoryView.swift",
            "Views/SavingsView.swift",
            "Views/SettingsView.swift",
        ):
            self.assertTrue((APP / relative).is_file(), relative)
        self.assertTrue((IOS / "Widget/Sources/BatteryWidget.swift").is_file())
        self.assertTrue((IOS / "Shared/AppConfig.swift").is_file())
        self.assertIn("BatteryWidgetExtension", project)

    def test_local_network_permission_and_orientations(self) -> None:
        with (APP / "Resources/Info.plist").open("rb") as source:
            info = plistlib.load(source)
        self.assertIn("NSLocalNetworkUsageDescription", info)
        self.assertTrue(info["NSAppTransportSecurity"]["NSAllowsLocalNetworking"])
        self.assertIn("UIInterfaceOrientationPortrait", info["UISupportedInterfaceOrientations"])
        self.assertIn("UIInterfaceOrientationLandscapeLeft", info["UISupportedInterfaceOrientations~ipad"])
        with (IOS / "Widget/Resources/Info.plist").open("rb") as source:
            widget = plistlib.load(source)
        self.assertEqual(widget["NSExtension"]["NSExtensionPointIdentifier"], "com.apple.widgetkit-extension")

    def test_assets_and_localizations_are_well_formed(self) -> None:
        assets = APP / "Resources/Assets.xcassets"
        for manifest in assets.rglob("Contents.json"):
            json.loads(manifest.read_text(encoding="utf-8"))
        icon = assets / "AppIcon.appiconset/AppIcon.png"
        self.assertTrue(icon.is_file())
        self.assertGreater(icon.stat().st_size, 10_000)
        png = icon.read_bytes()
        width, height, _, color_type, _, _, _ = struct.unpack(">IIBBBBB", png[16:29])
        self.assertEqual((width, height), (1024, 1024))
        self.assertEqual(color_type, 2, "App Store icon must be opaque RGB without alpha")
        for language in ("en", "vi"):
            strings = (APP / f"Resources/{language}.lproj/Localizable.strings").read_text(encoding="utf-8")
            self.assertIn('"Home"', strings)
            self.assertIn('"Energy Savings"', strings)
            self.assertTrue((APP / f"Resources/{language}.lproj/InfoPlist.strings").is_file())

        key_pattern = re.compile(r'^"((?:[^"\\]|\\.)*)"\s*=', re.MULTILINE)
        english = set(key_pattern.findall((APP / "Resources/en.lproj/Localizable.strings").read_text(encoding="utf-8")))
        vietnamese = set(key_pattern.findall((APP / "Resources/vi.lproj/Localizable.strings").read_text(encoding="utf-8")))
        self.assertEqual(english, vietnamese)

    def test_app_and_widget_share_the_same_app_group(self) -> None:
        groups = []
        for path in (APP / "App.entitlements", IOS / "Widget/Widget.entitlements"):
            with path.open("rb") as source:
                groups.append(plistlib.load(source)["com.apple.security.application-groups"])
        self.assertEqual(groups[0], groups[1])
        self.assertEqual(groups[0], ["group.com.trant.batterymonitor"])

    def test_app_uses_monitor_api_not_collector_api(self) -> None:
        networking = (APP / "Networking/MonitorAPI.swift").read_text(encoding="utf-8")
        self.assertIn('get("api/live")', networking)
        self.assertIn('get("api/power-history"', networking)
        self.assertIn('get("api/savings"', networking)
        self.assertNotIn("api/readings", networking)

    def test_build_automation_is_present(self) -> None:
        makefile = (IOS / "Makefile").read_text(encoding="utf-8")
        self.assertIn("run:", makefile)
        self.assertIn("archive:", makefile)
        self.assertIn("ipa:", makefile)
        workflow = (ROOT / ".github/workflows/ios.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: macos-15", workflow)
        self.assertIn("scripts/test-simulator.sh", workflow)
        simulator_test = (IOS / "scripts/test-simulator.sh").read_text(encoding="utf-8")
        self.assertIn("xcodebuild", simulator_test)


if __name__ == "__main__":
    unittest.main()
