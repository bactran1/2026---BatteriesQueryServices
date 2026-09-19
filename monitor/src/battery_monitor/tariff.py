"""PSE Schedule 327 -- Residential Time-Of-Use with Super Off-Peak.

Schedule 327 prices a kilowatt-hour by *when* it crossed the meter, so the
savings engine can no longer multiply a period total by one flat rate. This
module owns the period structure: which clock hours belong to which time
period, which months are winter, and which days are legal holidays.

The structure lives in code because it changes only when PSE refiles the
schedule; the prices live in configuration (``BQM_UTILITY_*``) because they
move with every rate filing. Update the prices from your bill or from PSE's
published Schedule 327 sheet -- the defaults in ``config.py`` are a starting
point, not a promise.

Period structure:

* Super off-peak -- every day, 11:00 p.m. to 7:00 a.m., one price year round.
* On-peak -- weekdays only, 7:00-10:00 a.m. and 5:00-8:00 p.m., priced by
  season. Legal holidays are never on-peak.
* Off-peak -- everything else: 10:00 a.m. to 5:00 p.m. and 8:00 to 11:00 p.m.
  on a weekday, and the whole 7:00 a.m. to 11:00 p.m. block on a weekend or
  holiday, where the on-peak windows do not apply.

Seasons follow the schedule's calendar: winter is October 1 through March 31,
summer is April 1 through September 30.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

ON_PEAK = "on_peak"
OFF_PEAK = "off_peak"
SUPER_OFF_PEAK = "super_off_peak"
TOU_PERIODS: tuple[str, ...] = (ON_PEAK, OFF_PEAK, SUPER_OFF_PEAK)

WINTER = "winter"
SUMMER = "summer"

# Super off-peak runs from 23:00 through 07:00, wrapping across midnight.
SUPER_OFF_PEAK_START_HOUR = 23
SUPER_OFF_PEAK_END_HOUR = 7
# On-peak windows are half-open [start, end) in local clock hours, weekdays only.
ON_PEAK_WINDOWS: tuple[tuple[int, int], ...] = ((7, 10), (17, 20))
# October through March. Everything else is the summer season.
WINTER_MONTHS = frozenset({10, 11, 12, 1, 2, 3})


def season_for(moment: datetime) -> str:
    """Winter (Oct 1 - Mar 31) or summer (Apr 1 - Sep 30) for a local moment."""
    return WINTER if moment.month in WINTER_MONTHS else SUMMER


def period_for(moment: datetime) -> str:
    """The Schedule 327 time period a local moment falls in.

    ``moment`` must already be expressed in the tariff's local clock: the
    schedule's hours are wall-clock hours, so they shift with daylight saving
    time exactly as the meter does.
    """
    hour = moment.hour
    if hour >= SUPER_OFF_PEAK_START_HOUR or hour < SUPER_OFF_PEAK_END_HOUR:
        return SUPER_OFF_PEAK
    if is_off_peak_day(moment.date()):
        return OFF_PEAK
    if any(start <= hour < end for start, end in ON_PEAK_WINDOWS):
        return ON_PEAK
    return OFF_PEAK


def is_off_peak_day(day: date) -> bool:
    """True when a day carries no on-peak hours: a weekend or a legal holiday."""
    return day.weekday() >= 5 or day in observed_holidays(day.year)


def observed_holidays(year: int) -> frozenset[date]:
    """The legal holidays Schedule 327 treats as off-peak, as observed.

    These are the six holidays PSE's residential schedules name. A holiday
    landing on a Saturday is observed the Friday before and one landing on a
    Sunday the Monday after, which is the usual tariff convention. Confirm
    against your own schedule sheet if a holiday's classification matters to
    you -- this list is the assumption the savings estimate rests on.
    """
    return frozenset(
        {
            _observed(date(year, 1, 1)),  # New Year's Day
            _last_weekday_of(year, 5, 0),  # Memorial Day: last Monday in May
            _observed(date(year, 7, 4)),  # Independence Day
            _nth_weekday_of(year, 9, 0, 1),  # Labor Day: first Monday in September
            _nth_weekday_of(year, 11, 3, 4),  # Thanksgiving: fourth Thursday
            _observed(date(year, 12, 25)),  # Christmas Day
        }
    )


def rate_for(period: str, season: str, rates: dict[str, float]) -> float | None:
    """Look up the price of one time period in one season.

    ``rates`` is keyed ``"<period>_<season>"`` with a plain ``<period>`` key
    accepted for a period that is priced the same year round.
    """
    if period in rates:
        return rates[period]
    return rates.get(f"{period}_{season}")


def _observed(day: date) -> date:
    if day.weekday() == 5:  # Saturday -> the Friday before
        return day - timedelta(days=1)
    if day.weekday() == 6:  # Sunday -> the Monday after
        return day + timedelta(days=1)
    return day


def _nth_weekday_of(year: int, month: int, weekday: int, count: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (count - 1))


def _last_weekday_of(year: int, month: int, weekday: int) -> date:
    following = (
        date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    )
    last = following - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)
