from __future__ import annotations

from typing import Any

from .config import UtilityTariff


def build_savings_payload(
    energy: dict[str, dict[str, Any]], tariff: UtilityTariff
) -> dict[str, Any]:
    tax_multiplier = 1.0 + tariff.municipal_tax_percent / 100.0
    rates = sorted(
        (
            tariff.tier_1_usd_per_kwh * tax_multiplier,
            tariff.tier_2_usd_per_kwh * tax_multiplier,
        )
    )
    periods = {
        key: _period_value(value, rates[0], rates[1])
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
            "tier_1_usd_per_kwh": round(tariff.tier_1_usd_per_kwh, 6),
            "tier_2_usd_per_kwh": round(tariff.tier_2_usd_per_kwh, 6),
            "tier_1_limit_kwh": tariff.tier_1_limit_kwh,
            "basic_charge_usd": round(tariff.basic_charge_usd, 2),
            "municipal_tax_percent": tariff.municipal_tax_percent,
            "effective_rate_low_usd_per_kwh": round(rates[0], 6),
            "effective_rate_high_usd_per_kwh": round(rates[1], 6),
        },
        "methodology": {
            "kind": "current_rate_solar_value",
            "net_metering_assumed": True,
            "fixed_charge_excluded": True,
            "municipal_tax_included": tariff.municipal_tax_percent > 0,
        },
    }


def _period_value(
    energy: dict[str, Any], low_rate: float, high_rate: float
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
    return {
        "solar_generation_kwh": _rounded(solar),
        "grid_import_kwh": _rounded(grid),
        "consumption_kwh": _rounded(consumption),
        "observed_days": observed_days,
        "estimated_savings_usd_low": _money(solar, low_rate),
        "estimated_savings_usd_high": _money(solar, high_rate),
        "estimated_grid_cost_usd_low": _money(grid, low_rate),
        "estimated_grid_cost_usd_high": _money(grid, high_rate),
        "solar_share_percent": solar_share,
        "average_savings_per_observed_day_usd_low": _daily_money(
            solar, low_rate, observed_days
        ),
        "average_savings_per_observed_day_usd_high": _daily_money(
            solar, high_rate, observed_days
        ),
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


def _daily_money(
    value: float | None, rate: float, observed_days: int
) -> float | None:
    if value is None or observed_days <= 0:
        return None
    return round(value * rate / observed_days, 2)
