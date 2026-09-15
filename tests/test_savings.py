from __future__ import annotations

import unittest

from battery_monitor.config import UtilityTariff
from battery_monitor.savings import build_savings_payload


class SavingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tariff = UtilityTariff(
            provider="Puget Sound Energy",
            schedule="Residential Schedule 7",
            region="King County, WA",
            effective_date="2026-05-01",
            tier_1_usd_per_kwh=0.187465,
            tier_2_usd_per_kwh=0.206882,
            tier_1_limit_kwh=600,
            basic_charge_usd=7.49,
            municipal_tax_percent=0,
        )

    def test_values_solar_and_grid_energy_as_an_honest_rate_range(self) -> None:
        payload = build_savings_payload(
            {
                "month": {
                    "solar_generation_kwh": 100,
                    "grid_import_kwh": 50,
                    "consumption_kwh": 120,
                    "observed_days": 10,
                }
            },
            self.tariff,
        )
        month = payload["periods"]["month"]
        self.assertEqual(month["estimated_savings_usd_low"], 18.75)
        self.assertEqual(month["estimated_savings_usd_high"], 20.69)
        self.assertEqual(month["estimated_grid_cost_usd_low"], 9.37)
        self.assertEqual(month["estimated_grid_cost_usd_high"], 10.34)
        self.assertEqual(month["average_savings_per_observed_day_usd_low"], 1.87)
        self.assertEqual(month["solar_share_percent"], 66.7)
        self.assertTrue(payload["methodology"]["fixed_charge_excluded"])

    def test_missing_data_stays_missing_and_zero_stays_zero(self) -> None:
        payload = build_savings_payload(
            {
                "today": {
                    "solar_generation_kwh": 0,
                    "grid_import_kwh": None,
                    "observed_days": 1,
                }
            },
            self.tariff,
        )
        today = payload["periods"]["today"]
        self.assertEqual(today["estimated_savings_usd_low"], 0)
        self.assertIsNone(today["estimated_grid_cost_usd_low"])
        self.assertIsNone(today["solar_share_percent"])

    def test_configured_municipal_tax_adjusts_variable_rates_only(self) -> None:
        tariff = UtilityTariff(**{**self.tariff.__dict__, "municipal_tax_percent": 10})
        payload = build_savings_payload(
            {"year": {"solar_generation_kwh": 10, "observed_days": 2}}, tariff
        )
        self.assertEqual(payload["periods"]["year"]["estimated_savings_usd_low"], 2.06)
        self.assertEqual(payload["tariff"]["basic_charge_usd"], 7.49)
        self.assertTrue(payload["methodology"]["municipal_tax_included"])


if __name__ == "__main__":
    unittest.main()
