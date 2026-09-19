from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from battery_monitor.config import UtilityTariff
from battery_monitor.savings import build_savings_payload

ZONE = ZoneInfo("America/Los_Angeles")
WINTER_NOON = datetime(2026, 1, 14, 12, 0, tzinfo=ZONE)  # a Wednesday
SUMMER_NOON = datetime(2026, 7, 15, 12, 0, tzinfo=ZONE)  # a Wednesday


def split(on_solar=0.0, off_solar=0.0, super_solar=0.0,
          on_grid=0.0, off_grid=0.0, super_grid=0.0):
    return {
        "on_peak": {"solar_generation_kwh": on_solar, "grid_import_kwh": on_grid,
                    "consumption_kwh": 0.0},
        "off_peak": {"solar_generation_kwh": off_solar, "grid_import_kwh": off_grid,
                     "consumption_kwh": 0.0},
        "super_off_peak": {"solar_generation_kwh": super_solar,
                           "grid_import_kwh": super_grid, "consumption_kwh": 0.0},
    }


class SavingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tariff = UtilityTariff(
            provider="Puget Sound Energy",
            schedule="Residential Time-of-Use with Super Off-Peak (Schedule 327)",
            region="King County, WA",
            effective_date="2026-01-29",
            timezone="America/Los_Angeles",
            on_peak_winter_usd_per_kwh=0.475269,
            on_peak_summer_usd_per_kwh=0.256559,
            off_peak_winter_usd_per_kwh=0.119944,
            off_peak_summer_usd_per_kwh=0.115194,
            super_off_peak_usd_per_kwh=0.071296,
            basic_charge_usd=7.49,
            municipal_tax_percent=0,
        )

    def test_each_period_is_priced_at_its_own_rate_not_a_blended_one(self) -> None:
        payload = build_savings_payload(
            {
                "month": {
                    "solar_generation_kwh": 100,
                    "grid_import_kwh": 50,
                    "consumption_kwh": 120,
                    "observed_days": 10,
                    "tou": split(
                        on_solar=20, off_solar=80,
                        on_grid=10, off_grid=15, super_grid=25,
                    ),
                }
            },
            self.tariff,
            now=WINTER_NOON,
        )
        month = payload["periods"]["month"]
        # 20 kWh on-peak + 80 kWh off-peak, at the winter prices.
        self.assertEqual(month["tou"]["on_peak"]["savings_usd"], 9.51)
        self.assertEqual(month["tou"]["off_peak"]["savings_usd"], 9.6)
        self.assertEqual(month["estimated_savings_usd"], 19.11)
        # Grid: 10 on-peak, 15 off-peak, 25 super off-peak.
        self.assertEqual(month["estimated_grid_cost_usd"], 8.33)
        self.assertEqual(month["tou"]["super_off_peak"]["grid_cost_usd"], 1.78)
        self.assertEqual(month["average_savings_per_observed_day_usd"], 1.91)
        self.assertEqual(month["solar_share_percent"], 66.7)
        self.assertTrue(month["tou_classified"])
        self.assertTrue(payload["methodology"]["fixed_charge_excluded"])
        self.assertTrue(payload["methodology"]["priced_by_clock"])

    def test_the_blended_rate_reports_what_the_solar_actually_earned(self) -> None:
        payload = build_savings_payload(
            {"month": {"solar_generation_kwh": 100, "observed_days": 1,
                       "tou": split(on_solar=20, off_solar=80)}},
            self.tariff,
            now=WINTER_NOON,
        )
        month = payload["periods"]["month"]
        # 19.11 / 100 kWh, well above the off-peak price the same energy would
        # have earned on a flat plan.
        self.assertEqual(month["blended_solar_rate_usd_per_kwh"], 0.1911)

    def test_season_selects_the_on_peak_price(self) -> None:
        energy = {"month": {"solar_generation_kwh": 10, "observed_days": 1,
                            "tou": split(on_solar=10)}}
        winter = build_savings_payload(energy, self.tariff, now=WINTER_NOON)
        summer = build_savings_payload(energy, self.tariff, now=SUMMER_NOON)
        self.assertEqual(winter["tariff"]["season"], "winter")
        self.assertEqual(summer["tariff"]["season"], "summer")
        self.assertEqual(winter["periods"]["month"]["estimated_savings_usd"], 4.75)
        self.assertEqual(summer["periods"]["month"]["estimated_savings_usd"], 2.57)
        # Super off-peak carries one price all year.
        self.assertEqual(
            winter["tariff"]["season_rates_usd_per_kwh"]["super_off_peak"],
            summer["tariff"]["season_rates_usd_per_kwh"]["super_off_peak"],
        )

    def test_current_period_follows_the_tariff_clock(self) -> None:
        for moment, expected in (
            (datetime(2026, 1, 14, 8, 30, tzinfo=ZONE), "on_peak"),
            (datetime(2026, 1, 14, 12, 0, tzinfo=ZONE), "off_peak"),
            (datetime(2026, 1, 14, 23, 30, tzinfo=ZONE), "super_off_peak"),
            (datetime(2026, 1, 17, 18, 0, tzinfo=ZONE), "off_peak"),  # Saturday
            (datetime(2026, 7, 3, 18, 0, tzinfo=ZONE), "off_peak"),  # July 4 observed
        ):
            with self.subTest(moment=moment):
                tariff = build_savings_payload({}, self.tariff, now=moment)["tariff"]
                self.assertEqual(tariff["current_period"], expected)
                self.assertEqual(
                    tariff["current_rate_usd_per_kwh"],
                    tariff["season_rates_usd_per_kwh"][expected],
                )

    def test_the_rate_line_spans_the_cheapest_and_dearest_hour(self) -> None:
        tariff = build_savings_payload({}, self.tariff, now=WINTER_NOON)["tariff"]
        self.assertEqual(tariff["effective_rate_low_usd_per_kwh"], 0.071296)
        self.assertEqual(tariff["effective_rate_high_usd_per_kwh"], 0.475269)

    def test_a_window_with_no_rollup_yet_falls_back_to_the_off_peak_price(self) -> None:
        payload = build_savings_payload(
            {"retained": {"solar_generation_kwh": 100, "grid_import_kwh": 10,
                          "observed_days": 30}},
            self.tariff,
            now=WINTER_NOON,
        )
        retained = payload["periods"]["retained"]
        self.assertFalse(retained["tou_classified"])
        self.assertEqual(retained["estimated_savings_usd"], 11.99)
        self.assertEqual(retained["estimated_grid_cost_usd"], 1.2)
        self.assertIsNone(retained["blended_solar_rate_usd_per_kwh"])

    def test_missing_data_stays_missing_and_zero_stays_zero(self) -> None:
        payload = build_savings_payload(
            {"today": {"solar_generation_kwh": 0, "grid_import_kwh": None,
                       "observed_days": 1}},
            self.tariff,
            now=WINTER_NOON,
        )
        today = payload["periods"]["today"]
        self.assertEqual(today["estimated_savings_usd"], 0)
        self.assertIsNone(today["estimated_grid_cost_usd"])
        self.assertIsNone(today["solar_share_percent"])

    def test_configured_municipal_tax_adjusts_variable_rates_only(self) -> None:
        tariff = UtilityTariff(**{**self.tariff.__dict__, "municipal_tax_percent": 10})
        payload = build_savings_payload(
            {"year": {"solar_generation_kwh": 10, "observed_days": 2,
                      "tou": split(off_solar=10)}},
            tariff,
            now=WINTER_NOON,
        )
        # 10 kWh at the winter off-peak price plus 10% tax.
        self.assertEqual(payload["periods"]["year"]["estimated_savings_usd"], 1.32)
        self.assertEqual(payload["tariff"]["basic_charge_usd"], 7.49)
        self.assertTrue(payload["methodology"]["municipal_tax_included"])

    def test_clients_written_against_the_tiered_payload_still_see_a_figure(self) -> None:
        payload = build_savings_payload(
            {"month": {"solar_generation_kwh": 100, "grid_import_kwh": 50,
                       "observed_days": 10, "tou": split(off_solar=100, off_grid=50)}},
            self.tariff,
            now=WINTER_NOON,
        )
        month = payload["periods"]["month"]
        # No tiers left to straddle, so both ends of the legacy pair carry the
        # one exact number and an older client renders it as a single value.
        for field in (
            "estimated_savings_usd",
            "estimated_grid_cost_usd",
            "average_savings_per_observed_day_usd",
        ):
            self.assertEqual(month[f"{field}_low"], month[field])
            self.assertEqual(month[f"{field}_high"], month[field])


if __name__ == "__main__":
    unittest.main()
