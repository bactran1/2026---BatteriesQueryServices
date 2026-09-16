from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "is_day",
    "shortwave_radiation",
    "direct_normal_irradiance",
)


class WeatherClient:
    def __init__(
        self,
        *,
        enabled: bool,
        latitude: float,
        longitude: float,
        location: str,
        timeout_seconds: float = 4.0,
        refresh_seconds: float = 600.0,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled
        self.latitude = latitude
        self.longitude = longitude
        self.location = location
        self.timeout_seconds = max(0.5, timeout_seconds)
        self.refresh_seconds = max(60.0, refresh_seconds)
        self._opener = opener
        self._clock = clock
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def current(self) -> dict[str, Any]:
        if not self.enabled:
            return self._unavailable("disabled")

        with self._lock:
            now = self._clock()
            if self._cached and now - self._cached_at < self.refresh_seconds:
                return dict(self._cached)

            try:
                weather = self._fetch()
            except Exception as error:  # noqa: BLE001 - weather must fail independently
                logger.warning("weather refresh failed: %s", error)
                if self._cached:
                    return {
                        **self._cached,
                        "status": "stale",
                        "error": "Weather refresh temporarily unavailable",
                    }
                return self._unavailable("Weather refresh temporarily unavailable")

            self._cached = weather
            self._cached_at = now
            return dict(weather)

    def _fetch(self) -> dict[str, Any]:
        query = urlencode(
            {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "current": ",".join(CURRENT_FIELDS),
                "timezone": "auto",
                "forecast_days": 1,
            }
        )
        request = Request(
            f"{OPEN_METEO_URL}?{query}",
            headers={"User-Agent": "BatteryMonitor/1.0"},
        )
        with self._opener(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        current = payload.get("current")
        if not isinstance(current, dict):
            raise ValueError("Weather response did not include current conditions")

        observed_at = _observed_at(
            current.get("time"), payload.get("utc_offset_seconds")
        )
        solar_elevation, solar_azimuth = _solar_position(
            observed_at, self.latitude, self.longitude
        )

        return {
            "status": "ok",
            "source": "Open-Meteo",
            "location": self.location,
            "observed_at": observed_at,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "temperature_c": _number(current.get("temperature_2m")),
            "apparent_temperature_c": _number(
                current.get("apparent_temperature")
            ),
            "relative_humidity_percent": _number(
                current.get("relative_humidity_2m")
            ),
            "precipitation_mm": _number(current.get("precipitation")),
            "weather_code": _integer(current.get("weather_code")),
            "cloud_cover_percent": _number(current.get("cloud_cover")),
            "wind_speed_kmh": _number(current.get("wind_speed_10m")),
            "is_day": _boolean(current.get("is_day")),
            "solar_irradiance_w_m2": _number(current.get("shortwave_radiation")),
            "direct_normal_irradiance_w_m2": _number(
                current.get("direct_normal_irradiance")
            ),
            "solar_elevation_degrees": solar_elevation,
            "solar_azimuth_degrees": solar_azimuth,
            "error": None,
        }

    def _unavailable(self, error: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "source": "Open-Meteo",
            "location": self.location,
            "observed_at": None,
            "fetched_at": None,
            "temperature_c": None,
            "apparent_temperature_c": None,
            "relative_humidity_percent": None,
            "precipitation_mm": None,
            "weather_code": None,
            "cloud_cover_percent": None,
            "wind_speed_kmh": None,
            "is_day": None,
            "solar_irradiance_w_m2": None,
            "direct_normal_irradiance_w_m2": None,
            "solar_elevation_degrees": None,
            "solar_azimuth_degrees": None,
            "error": error,
        }


def _observed_at(value: Any, offset_seconds: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        observed = datetime.fromisoformat(value)
        offset = int(offset_seconds or 0)
    except (TypeError, ValueError):
        return value
    return observed.replace(tzinfo=timezone(timedelta(seconds=offset))).isoformat()


def _solar_position(
    observed_at: str | None, latitude: float, longitude: float
) -> tuple[float | None, float | None]:
    """Return geometric sun elevation and clockwise azimuth from true north."""
    if not observed_at:
        return None, None
    try:
        observed = datetime.fromisoformat(observed_at)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        observed = observed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None, None

    julian_day = observed.timestamp() / 86400.0 + 2440587.5
    century = (julian_day - 2451545.0) / 36525.0
    mean_longitude = (
        280.46646 + century * (36000.76983 + century * 0.0003032)
    ) % 360.0
    mean_anomaly = 357.52911 + century * (35999.05029 - 0.0001537 * century)
    eccentricity = 0.016708634 - century * (
        0.000042037 + 0.0000001267 * century
    )
    anomaly_radians = math.radians(mean_anomaly)
    center = (
        math.sin(anomaly_radians)
        * (1.914602 - century * (0.004817 + 0.000014 * century))
        + math.sin(2 * anomaly_radians) * (0.019993 - 0.000101 * century)
        + math.sin(3 * anomaly_radians) * 0.000289
    )
    true_longitude = mean_longitude + center
    omega = 125.04 - 1934.136 * century
    apparent_longitude = (
        true_longitude
        - 0.00569
        - 0.00478 * math.sin(math.radians(omega))
    )
    mean_obliquity = 23.0 + (
        26.0
        + (
            21.448
            - century
            * (46.815 + century * (0.00059 - century * 0.001813))
        )
        / 60.0
    ) / 60.0
    obliquity = mean_obliquity + 0.00256 * math.cos(math.radians(omega))
    obliquity_radians = math.radians(obliquity)
    apparent_longitude_radians = math.radians(apparent_longitude)
    declination = math.asin(
        math.sin(obliquity_radians) * math.sin(apparent_longitude_radians)
    )

    y = math.tan(obliquity_radians / 2.0) ** 2
    longitude_radians = math.radians(mean_longitude)
    equation_of_time = 4.0 * math.degrees(
        y * math.sin(2.0 * longitude_radians)
        - 2.0 * eccentricity * math.sin(anomaly_radians)
        + 4.0
        * eccentricity
        * y
        * math.sin(anomaly_radians)
        * math.cos(2.0 * longitude_radians)
        - 0.5 * y * y * math.sin(4.0 * longitude_radians)
        - 1.25 * eccentricity * eccentricity * math.sin(2.0 * anomaly_radians)
    )
    utc_minutes = (
        observed.hour * 60.0
        + observed.minute
        + observed.second / 60.0
        + observed.microsecond / 60000000.0
    )
    true_solar_minutes = (utc_minutes + equation_of_time + 4.0 * longitude) % 1440.0
    hour_angle = true_solar_minutes / 4.0 - 180.0
    hour_angle_radians = math.radians(hour_angle)
    latitude_radians = math.radians(latitude)
    cosine_zenith = (
        math.sin(latitude_radians) * math.sin(declination)
        + math.cos(latitude_radians)
        * math.cos(declination)
        * math.cos(hour_angle_radians)
    )
    zenith = math.acos(max(-1.0, min(1.0, cosine_zenith)))
    elevation = 90.0 - math.degrees(zenith)
    azimuth = (
        math.degrees(
            math.atan2(
                math.sin(hour_angle_radians),
                math.cos(hour_angle_radians) * math.sin(latitude_radians)
                - math.tan(declination) * math.cos(latitude_radians),
            )
        )
        + 180.0
    ) % 360.0
    return round(elevation, 2), round(azimuth, 2)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 2)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    return None
