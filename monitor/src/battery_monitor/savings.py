from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import UtilityTariff
from .tariff import (
    OFF_PEAK,
    ON_PEAK,
    SUPER_OFF_PEAK,
    TOU_PERIODS,
    period_for,
    rate_for,
    season_for,
)


def build_savings_payload(
    energy: dict[str, dict[str, Any]],
    tariff: UtilityTariff,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Price recorded energy under a time-of-use schedule.

    Schedule 327 has no consumption tiers, so a period's value is no longer a
    range between a tier-1 and a tier-2 guess: every kilowatt-hour has one
    price, set by the time period it crossed the meter. Each window is priced
    from its own time-of-use split and the season that split fell in.
    """
    tax_multiplier = 1.0 + tariff.municipal_tax_percent / 100.0
    zone = ZoneInfo(tariff.timezone)
    moment = now.astimezone(zone) if now else datetime.now(zone)
    season = season_for(moment)
    base_rates = tariff.rates()
    taxed = {key: value * tax_multiplier for key, value in base_rates.items()}
    season_rates = {
        period: rate_for(period, season, taxed) or 0.0 for period in TOU_PERIODS
    }
    all_rates = [value for value in taxed.values() if value > 0]
    current_period = period_for(moment)

    periods = {
        key: _period_value(value, taxed, season_rates)
        for key, value in energy.items()
    }
    return {
        "currency": "USD",
        "default_period": "month",
        "periods": periods,
        "tariff": {
            "provider": tariff.provider,
            "schedule": tariff.schedule,
            "region": tariff.region,
            "effective_date": tariff.effective_date,
            "timezone": tariff.timezone,
            "season": season,
            "kind": "time_of_use",
            # Which period the meter is in right now, resolved on the tariff's
            # own clock so a browser in another timezone still sees the truth.
            "current_period": current_period,
            "current_rate_usd_per_kwh": round(season_rates[current_period], 6),
            "rates_usd_per_kwh": {
                "on_peak_winter": round(taxed["on_peak_winter"], 6),
                "on_peak_summer": round(taxed["on_peak_summer"], 6),
                "off_peak_winter": round(taxed["off_peak_winter"], 6),
                "off_peak_summer": round(taxed["off_peak_summer"], 6),
                "super_off_peak": round(taxed["super_off_peak"], 6),
            },
            "season_rates_usd_per_kwh": {
                period: round(season_rates[period], 6) for period in TOU_PERIODS
            },
            "windows": {
                ON_PEAK: "Weekdays 7-10 a.m. and 5-8 p.m., excluding holidays",
                OFF_PEAK: "All other hours between 7 a.m. and 11 p.m.",
                SUPER_OFF_PEAK: "Every day 11 p.m. to 7 a.m.",
            },
            "basic_charge_usd": round(tariff.basic_charge_usd, 2),
            "municipal_tax_percent": tariff.municipal_tax_percent,
            # The cheapest and dearest kilowatt-hour the schedule can bill, which
            # is what a plain "variable rate" line should show under a TOU plan.
            "effective_rate_low_usd_per_kwh": (
                round(min(all_rates), 6) if all_rates else None
            ),
            "effective_rate_high_usd_per_kwh": (
                round(max(all_rates), 6) if all_rates else None
            ),
        },
        "methodology": {
            "kind": "time_of_use_solar_value",
            "net_metering_assumed": True,
            "fixed_charge_excluded": True,
            "municipal_tax_included": tariff.municipal_tax_percent > 0,
            "priced_by_clock": True,
        },
    }


def _period_value(
    energy: dict[str, Any],
    taxed: dict[str, float],
    season_rates: dict[str, float],
) -> dict[str, Any]:
    solar = _nonnegative_number(energy.get("solar_generation_kwh"))
    grid = _nonnegative_number(energy.get("grid_import_kwh"))
    consumption = _nonnegative_number(energy.get("consumption_kwh"))
    observed_days = max(0, int(energy.get("observed_days") or 0))
    supplied = None if solar is None or grid is None else solar + grid
    solar_share = (
        None
        if supplied is None or supplied <= 0
        else round(solar / supplied * 100.0, 1)
    )

    split = _tou_split(energy.get("tou"))
    priced = {
        period: _priced_period(period, split.get(period), season_rates[period])
        for period in TOU_PERIODS
    }
    classified_solar = sum(item["solar_generation_kwh"] for item in priced.values())
    classified_grid = sum(item["grid_import_kwh"] for item in priced.values())
    has_split = classified_solar > 0 or classified_grid > 0

    # With no rollup yet (a window older than the archive, or one still being
    # backfilled) the honest fallback is the season's off-peak price: solar and
    # household draw both sit mostly in the off-peak block.
    fallback = season_rates[OFF_PEAK]
    savings = (
        round(sum(item["savings_usd"] for item in priced.values()), 2)
        if has_split
        else _money(solar, fallback)
    )
    grid_cost = (
        round(sum(item["grid_cost_usd"] for item in priced.values()), 2)
        if has_split
        else _money(grid, fallback)
    )
    solar_rate = (
        round(savings / classified_solar, 6)
        if has_split and classified_solar > 0 and savings is not None
        else None
    )
    daily = (
        None
        if savings is None or observed_days <= 0
        else round(savings / observed_days, 2)
    )

    return {
        "solar_generation_kwh": _rounded(solar),
        "grid_import_kwh": _rounded(grid),
        "consumption_kwh": _rounded(consumption),
        "observed_days": observed_days,
        "estimated_savings_usd": savings,
        "estimated_grid_cost_usd": grid_cost,
        "average_savings_per_observed_day_usd": daily,
        "solar_share_percent": solar_share,
        "blended_solar_rate_usd_per_kwh": solar_rate,
        "tou_classified": has_split,
        "tou": {period: priced[period] for period in TOU_PERIODS},
        # A time-of-use bill has one price per kilowatt-hour rather than a tier
        # the month's total might or might not reach, so there is no longer a
        # spread to report. The low/high pair is kept, with both ends equal, so
        # clients written against the tiered payload keep rendering a figure.
        "estimated_savings_usd_low": savings,
        "estimated_savings_usd_high": savings,
        "estimated_grid_cost_usd_low": grid_cost,
        "estimated_grid_cost_usd_high": grid_cost,
        "average_savings_per_observed_day_usd_low": daily,
        "average_savings_per_observed_day_usd_high": daily,
    }


def _priced_period(
    period: str, values: dict[str, float] | None, rate: float
) -> dict[str, Any]:
    solar = max(0.0, float((values or {}).get("solar_generation_kwh") or 0.0))
    grid = max(0.0, float((values or {}).get("grid_import_kwh") or 0.0))
    consumption = max(0.0, float((values or {}).get("consumption_kwh") or 0.0))
    return {
        "period": period,
        "solar_generation_kwh": round(solar, 4),
        "grid_import_kwh": round(grid, 4),
        "consumption_kwh": round(consumption, 4),
        "rate_usd_per_kwh": round(rate, 6),
        "savings_usd": round(solar * rate, 2),
        "grid_cost_usd": round(grid * rate, 2),
    }


def _tou_split(value: Any) -> dict[str, dict[str, float]]:
    if not isinstance(value, dict):
        return {}
    return {
        period: values
        for period, values in value.items()
        if period in TOU_PERIODS and isinstance(values, dict)
    }


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number >= 0 else None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _money(value: float | None, rate: float) -> float | None:
    return None if value is None else round(value * rate, 2)
