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
            "BQM_UTILITY_ON_PEAK_WINTER_USD_PER_KWH": "0.52",
            "BQM_UTILITY_MUNICIPAL_TAX_PERCENT": "6.5",
            "BQM_WEATHER_ENABLED": "true",
            "BQM_WEATHER_LATITUDE": "47.61",
            "BQM_WEATHER_LONGITUDE": "-122.33",
            "BQM_WEATHER_LOCATION": "Home",
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
        self.assertEqual(
            settings.utility_tariff.schedule,
            "Residential Time-of-Use with Super Off-Peak (Schedule 327)",
        )
        self.assertEqual(settings.utility_tariff.on_peak_winter_usd_per_kwh, 0.52)
        # Unset prices keep the Schedule 327 defaults, and the tariff carries its
        # own clock so time-of-use periods do not follow the viewer's timezone.
        self.assertEqual(settings.utility_tariff.super_off_peak_winter_usd_per_kwh, 0.083961)
        self.assertEqual(settings.utility_tariff.super_off_peak_summer_usd_per_kwh, 0.082307)
        self.assertEqual(settings.utility_tariff.riders_usd_per_kwh, 0.039102)
        self.assertEqual(settings.utility_tariff.timezone, "America/Los_Angeles")
        self.assertEqual(settings.utility_tariff.municipal_tax_percent, 6.5)
        # Schedule 7, the comparison plan, keeps its defaults when unset.
        self.assertEqual(
            settings.utility_tariff.comparison_schedule, "Residential Service (Schedule 7)"
        )
        self.assertEqual(settings.utility_tariff.comparison_tier_1_usd_per_kwh, 0.148363)
        self.assertEqual(settings.utility_tariff.comparison_tier_2_usd_per_kwh, 0.167780)
        self.assertEqual(settings.utility_tariff.comparison_tier_1_limit_kwh, 600)
        self.assertEqual(settings.utility_tariff.comparison_tier_1_period_days, 30)
        self.assertTrue(settings.weather_enabled)
        self.assertEqual(settings.weather_latitude, 47.61)
        self.assertEqual(settings.weather_longitude, -122.33)
        self.assertEqual(settings.weather_location, "Home")

    def test_the_default_rack_is_four_packs_with_the_314_ah_unit_last(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            profiles = load_settings().battery_profiles
        self.assertEqual([p.id for p in profiles], ["rack-1", "rack-2", "rack-3", "rack-4"])
        self.assertEqual([p.address for p in profiles], [1, 2, 3, 2])
        self.assertEqual(profiles[3].name, "Rack Battery 4")
        self.assertEqual(
            profiles[3].model,
            "Eco-worthy 51.2V 314Ah floor-standing battery (first generation)",
        )
        self.assertEqual(profiles[0].model, "Eco-worthy 48V 100Ah server rack battery")
        self.assertTrue(all(p.ip_address is None for p in profiles))
        # The 314 Ah unit is a floor-standing battery on casters, not a rack module.
        self.assertEqual([p.form_factor for p in profiles], ["rack", "rack", "rack", "floor"])

    def test_form_factors_come_from_the_environment_and_default_to_rack(self) -> None:
        environment = {
            "BQM_BATTERY_IDS": "a,b,c,d,e",
            "BQM_BATTERY_FORM_FACTORS": "Floor,floor-standing,, tower ,nonsense",
        }
        with patch.dict(os.environ, environment, clear=True):
            profiles = load_settings().battery_profiles
        self.assertEqual(
            [p.form_factor for p in profiles], ["floor", "floor", "rack", "floor", "rack"]
        )

    def test_tariff_defaults_follow_the_october_2026_statement(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            tariff = load_settings().utility_tariff
        self.assertEqual(tariff.on_peak_winter_usd_per_kwh, 0.511994)
        self.assertEqual(tariff.off_peak_summer_usd_per_kwh, 0.128820)
        self.assertEqual(tariff.municipal_tax_percent, 6.695)
        # Energy charge plus riders is what a kilowatt-hour costs before tax.
        self.assertAlmostEqual(tariff.rates()["super_off_peak_winter"], 0.123063, 6)
        self.assertAlmostEqual(tariff.rates()["on_peak_winter"], 0.551096, 6)

    def test_one_super_off_peak_price_still_sets_both_seasons(self) -> None:
        with patch.dict(os.environ, {"BQM_UTILITY_SUPER_OFF_PEAK_USD_PER_KWH": "0.09"}, clear=True):
            tariff = load_settings().utility_tariff
        self.assertEqual(tariff.super_off_peak_winter_usd_per_kwh, 0.09)
        self.assertEqual(tariff.super_off_peak_summer_usd_per_kwh, 0.09)

    def test_rack_details_combines_profile_and_live_reading(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings()

        self.assertEqual(settings.weather_latitude, 47.3809)
        self.assertEqual(settings.weather_longitude, -122.2348)
        self.assertEqual(settings.weather_location, "Kent, WA")

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

        self.assertEqual(details["expected_battery_count"], 4)
        self.assertEqual(details["observed_battery_count"], 1)
        self.assertEqual(details["online_battery_count"], 1)
        self.assertEqual(details["batteries"][0]["serial_number"], "EW123")
        self.assertEqual(details["batteries"][0]["status"], "ok")
        self.assertEqual(details["batteries"][1]["status"], "not_seen")
        # The inventory tells the dashboard how each pack is built.
        self.assertEqual(
            [battery["form_factor"] for battery in details["batteries"]],
            ["rack", "rack", "rack", "floor"],
        )

        stale_details = rack_details(settings, details["batteries"], collector_online=False)
        self.assertEqual(stale_details["online_battery_count"], 0)
        self.assertEqual(stale_details["batteries"][0]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
