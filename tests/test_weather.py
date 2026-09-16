from __future__ import annotations

import json
import unittest

from battery_monitor.weather import WeatherClient


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class WeatherClientTests(unittest.TestCase):
    def test_fetches_normalizes_and_caches_current_conditions(self) -> None:
        requests = []
        now = [100.0]

        def opener(request, timeout):
            requests.append((request.full_url, timeout))
            return _Response(
                {
                    "utc_offset_seconds": -25200,
                    "current": {
                        "time": "2026-09-15T12:15",
                        "temperature_2m": 18.2,
                        "apparent_temperature": 17.4,
                        "relative_humidity_2m": 71,
                        "precipitation": 0.2,
                        "weather_code": 61,
                        "cloud_cover": 83,
                        "wind_speed_10m": 8.6,
                        "is_day": 1,
                    },
                }
            )

        client = WeatherClient(
            enabled=True,
            latitude=47.6062,
            longitude=-122.3321,
            location="King County, WA",
            opener=opener,
            clock=lambda: now[0],
        )

        first = client.current()
        now[0] += 120
        second = client.current()

        self.assertEqual(len(requests), 1)
        self.assertIn("current=temperature_2m%2Capparent_temperature", requests[0][0])
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["temperature_c"], 18.2)
        self.assertEqual(first["weather_code"], 61)
        self.assertEqual(first["observed_at"], "2026-09-15T12:15:00-07:00")

    def test_returns_stale_cache_when_refresh_fails(self) -> None:
        now = [100.0]
        calls = [0]

        def opener(_request, timeout):
            self.assertGreater(timeout, 0)
            calls[0] += 1
            if calls[0] > 1:
                raise OSError("offline")
            return _Response(
                {
                    "current": {
                        "time": "2026-09-15T12:15",
                        "temperature_2m": 15,
                        "weather_code": 3,
                        "is_day": 1,
                    }
                }
            )

        client = WeatherClient(
            enabled=True,
            latitude=47.6,
            longitude=-122.3,
            location="King County, WA",
            refresh_seconds=60,
            opener=opener,
            clock=lambda: now[0],
        )
        client.current()
        now[0] += 61

        with self.assertLogs("battery_monitor.weather", level="WARNING"):
            stale = client.current()

        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["temperature_c"], 15.0)

    def test_disabled_weather_never_calls_the_provider(self) -> None:
        def opener(*_args, **_kwargs):
            self.fail("disabled weather should not issue a request")

        client = WeatherClient(
            enabled=False,
            latitude=47.6,
            longitude=-122.3,
            location="King County, WA",
            opener=opener,
        )

        self.assertEqual(client.current()["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
