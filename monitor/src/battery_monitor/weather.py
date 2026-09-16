from __future__ import annotations

import json
import logging
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

        return {
            "status": "ok",
            "source": "Open-Meteo",
            "location": self.location,
            "observed_at": _observed_at(
                current.get("time"), payload.get("utc_offset_seconds")
            ),
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
