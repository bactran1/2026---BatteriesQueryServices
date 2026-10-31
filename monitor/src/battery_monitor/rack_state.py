"""Rack-wide figures derived from the packs' own readings.

The rack is no longer a set of identical packs: three 100 Ah modules share
the bus with a 314 Ah one. An equal-weight mean of pack SOCs would let a
small pack move the rack figure as much as the big one, so the rack's
state of charge is weighted by capacity whenever the packs report it.
"""

from __future__ import annotations

from typing import Any

CAPACITY_WEIGHTED = "capacity"
EQUAL_WEIGHTED = "equal"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def rack_state_of_charge(
    readings: list[dict[str, Any]],
) -> tuple[float | None, str | None]:
    """The rack's state of charge and how it was weighted.

    Capacity-weighted (the sum of the packs' remaining amp-hours over the sum
    of their full-charge amp-hours) when every pack that reports a state of
    charge also reports both capacities; the plain mean of the packs' SOC
    otherwise, which is what a rack of identical packs gets either way.
    Returns ``(None, None)`` when no pack reports a state of charge.
    """
    socs: list[float] = []
    remaining_total = 0.0
    full_total = 0.0
    every_pack_has_capacity = True
    for reading in readings:
        if not isinstance(reading, dict):
            continue
        soc = _number(reading.get("soc_percent"))
        if soc is None:
            continue
        socs.append(soc)
        remaining = _number(reading.get("remaining_capacity_ah"))
        full = _number(reading.get("full_capacity_ah"))
        if full is None or full <= 0:
            full = _number(reading.get("rated_capacity_ah"))
        if remaining is None or remaining < 0 or full is None or full <= 0:
            every_pack_has_capacity = False
            continue
        remaining_total += remaining
        full_total += full
    if not socs:
        return None, None
    if every_pack_has_capacity and full_total > 0:
        return round(100.0 * remaining_total / full_total, 1), CAPACITY_WEIGHTED
    return round(sum(socs) / len(socs), 1), EQUAL_WEIGHTED
