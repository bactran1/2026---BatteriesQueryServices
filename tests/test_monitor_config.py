from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from battery_monitor.config import load_settings, rack_details


class MonitorConfigTests(unittest.TestCase):
    def test_loads_rack_inventory_from_environment(self) -> None:
        environment = {
            "BQM_RACK_NAME": "Garage Rack",
            "BQM_RACK_BUILDER": "Tran Thanh Tuan",
            "BQM_RACK_LOCATION": "Garage",
            "BQM_BATTERY_IDS": "rack-1,rack-2,rack-3",
            "BQM_BATTERY_ADDRESSES": "1,2,3",
            "BQM_BATTERY_NAMES": "Top,Middle,Bottom",
            "BQM_BATTERY_IPS": "192.168.1.61,,192.168.1.63",
            "BQM_BATTERY_MODELS": "EW-A,EW-B,EW-C",
            "BQM_LIVE_POLL_INTERVAL_SECONDS": "7",
            "BQM_STALE_AFTER_SECONDS": "35",
            "BQM_OFFLINE_AFTER_SECONDS": "150",
        }

        with patch.dict(os.environ, environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.rack_name, "Garage Rack")
        self.assertEqual(len(settings.battery_profiles), 3)
        self.assertEqual(settings.battery_profiles[0].name, "Top")
        self.assertEqual(settings.battery_profiles[1].ip_address, None)
        self.assertEqual(settings.battery_profiles[2].ip_address, "192.168.1.63")
        self.assertEqual(settings.live_poll_interval_seconds, 7.0)
        self.assertEqual(settings.stale_after_seconds, 35.0)
        self.assertEqual(settings.offline_after_seconds, 150.0)

    def test_rack_details_combines_profile_and_live_reading(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        details = rack_details(
            settings,
            [
                {
                    "id": "rack-1",
                    "address": 1,
                    "status": "ok",
                    "last_polled_at": "2026-08-09T12:00:00Z",
                    "last_reading": {
                        "serial_number": "EW123",
                        "firmware_version": "1.2.3",
                        "rs485_protocol": "Pylontech",
                    },
                }
            ],
        )

        self.assertEqual(details["expected_battery_count"], 3)
        self.assertEqual(details["observed_battery_count"], 1)
        self.assertEqual(details["online_battery_count"], 1)
        self.assertEqual(details["batteries"][0]["serial_number"], "EW123")
        self.assertEqual(details["batteries"][0]["status"], "ok")
        self.assertEqual(details["batteries"][1]["status"], "not_seen")

        stale_details = rack_details(settings, details["batteries"], collector_online=False)
        self.assertEqual(stale_details["online_battery_count"], 0)
        self.assertEqual(stale_details["batteries"][0]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
