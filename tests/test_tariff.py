from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from battery_monitor.tariff import (
    OFF_PEAK,
    ON_PEAK,
    SUMMER,
    SUPER_OFF_PEAK,
    WINTER,
    is_off_peak_day,
    observed_holidays,
    period_for,
    rate_for,
    season_for,
)

ZONE = ZoneInfo("America/Los_Angeles")


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ZONE)


class TariffPeriodTests(unittest.TestCase):
    def test_a_weekday_runs_through_all_three_periods(self) -> None:
        # Wednesday, January 14 2026.
        expected = {
            0: SUPER_OFF_PEAK, 6: SUPER_OFF_PEAK,
            7: ON_PEAK, 9: ON_PEAK,
            10: OFF_PEAK, 16: OFF_PEAK,
            17: ON_PEAK, 19: ON_PEAK,
            20: OFF_PEAK, 22: OFF_PEAK,
            23: SUPER_OFF_PEAK,
        }
        for hour, period in expected.items():
            with self.subTest(hour=hour):
                self.assertEqual(period_for(at(2026, 1, 14, hour)), period)

    def test_the_super_off_peak_block_wraps_across_midnight(self) -> None:
        self.assertEqual(period_for(at(2026, 1, 14, 23, 59)), SUPER_OFF_PEAK)
        self.assertEqual(period_for(at(2026, 1, 15, 0, 0)), SUPER_OFF_PEAK)
        self.assertEqual(period_for(at(2026, 1, 15, 6, 59)), SUPER_OFF_PEAK)
        self.assertEqual(period_for(at(2026, 1, 15, 7, 0)), ON_PEAK)

    def test_weekends_carry_no_on_peak_hours(self) -> None:
        for day in (17, 18):  # Saturday and Sunday
            for hour in (8, 12, 18, 22):
                with self.subTest(day=day, hour=hour):
                    self.assertEqual(period_for(at(2026, 1, day, hour)), OFF_PEAK)
        # The overnight block is still super off-peak on a weekend.
        self.assertEqual(period_for(at(2026, 1, 17, 2)), SUPER_OFF_PEAK)

    def test_legal_holidays_are_off_peak_even_on_a_weekday(self) -> None:
        holidays = {
            date(2026, 1, 1),  # New Year's Day, a Thursday
            date(2026, 5, 25),  # Memorial Day, last Monday in May
            date(2026, 9, 7),  # Labor Day, first Monday in September
            date(2026, 11, 26),  # Thanksgiving, fourth Thursday
            date(2026, 12, 25),  # Christmas Day, a Friday
        }
        self.assertTrue(holidays <= observed_holidays(2026))
        for holiday in holidays:
            with self.subTest(holiday=holiday):
                self.assertEqual(
                    period_for(at(holiday.year, holiday.month, holiday.day, 18)),
                    OFF_PEAK,
                )

    def test_a_weekend_holiday_is_observed_on_the_nearest_weekday(self) -> None:
        # July 4 2026 is a Saturday, so the Friday before is the observed holiday.
        self.assertIn(date(2026, 7, 3), observed_holidays(2026))
        self.assertEqual(period_for(at(2026, 7, 3, 18)), OFF_PEAK)
        # January 1 2028 is a Saturday: observed the Friday before, in 2027.
        self.assertIn(date(2027, 12, 31), observed_holidays(2028))
        # November 11 2028 is a Saturday but is not one of the six.
        self.assertNotIn(date(2028, 11, 10), observed_holidays(2028))

    def test_an_ordinary_weekday_is_not_an_off_peak_day(self) -> None:
        self.assertFalse(is_off_peak_day(date(2026, 1, 14)))
        self.assertTrue(is_off_peak_day(date(2026, 1, 17)))
        self.assertTrue(is_off_peak_day(date(2026, 12, 25)))

    def test_seasons_follow_the_schedule_calendar(self) -> None:
        for month in (10, 11, 12, 1, 2, 3):
            self.assertEqual(season_for(at(2026, month, 15, 12)), WINTER)
        for month in (4, 5, 6, 7, 8, 9):
            self.assertEqual(season_for(at(2026, month, 15, 12)), SUMMER)
        # The boundaries themselves.
        self.assertEqual(season_for(at(2026, 3, 31, 23)), WINTER)
        self.assertEqual(season_for(at(2026, 4, 1, 0)), SUMMER)
        self.assertEqual(season_for(at(2026, 9, 30, 23)), SUMMER)
        self.assertEqual(season_for(at(2026, 10, 1, 0)), WINTER)

    def test_periods_follow_the_wall_clock_across_a_daylight_saving_jump(self) -> None:
        # Spring forward: 2 a.m. on March 8 2026 becomes 3 a.m. The meter reads
        # wall-clock hours, so 7 a.m. local is on-peak either side of the jump.
        spring = at(2026, 3, 8, 7)  # a Sunday, so off-peak by the day rule
        self.assertEqual(period_for(spring), OFF_PEAK)
        monday = at(2026, 3, 9, 7)
        self.assertEqual(period_for(monday), ON_PEAK)
        self.assertEqual(monday.utcoffset(), timedelta(hours=-7))
        # A week earlier the same wall-clock hour sat on standard time.
        before = at(2026, 3, 2, 7)
        self.assertEqual(period_for(before), ON_PEAK)
        self.assertEqual(before.utcoffset(), timedelta(hours=-8))

    def test_rate_lookup_prefers_a_year_round_price(self) -> None:
        rates = {
            "on_peak_winter": 0.504,
            "on_peak_summer": 0.272,
            "off_peak_winter": 0.127,
            "off_peak_summer": 0.122,
            "super_off_peak": 0.076,
        }
        self.assertEqual(rate_for(ON_PEAK, WINTER, rates), 0.504)
        self.assertEqual(rate_for(ON_PEAK, SUMMER, rates), 0.272)
        # Super off-peak carries one price, so the season does not change it.
        self.assertEqual(rate_for(SUPER_OFF_PEAK, WINTER, rates), 0.076)
        self.assertEqual(rate_for(SUPER_OFF_PEAK, SUMMER, rates), 0.076)
        self.assertIsNone(rate_for("nonsense", WINTER, rates))


if __name__ == "__main__":
    unittest.main()
