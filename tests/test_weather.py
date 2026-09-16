from __future__ import annotations

import json
import unittest

from battery_monitor.weather import WeatherClient, _solar_position


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
                        "shortwave_radiation": 482.4,
                        "direct_normal_irradiance": 621.7,
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
        self.assertEqual(first["solar_irradiance_w_m2"], 482.4)
        self.assertEqual(first["direct_normal_irradiance_w_m2"], 621.7)
        self.assertGreater(first["solar_elevation_degrees"], 35)
        self.assertLess(first["solar_elevation_degrees"], 50)
        self.assertGreater(first["solar_azimuth_degrees"], 140)
        self.assertLess(first["solar_azimuth_degrees"], 210)
        self.assertEqual(first["observed_at"], "2026-09-15T12:15:00-07:00")

    def test_solar_position_handles_day_night_and_missing_time(self) -> None:
        elevation, azimuth = _solar_position(
            "2026-06-21T12:00:00-07:00", 47.3809, -122.2348
        )
        self.assertGreater(elevation, 60)
        self.assertTrue(140 <= azimuth <= 220)

        night_elevation, night_azimuth = _solar_position(
            "2026-06-21T00:00:00-07:00", 47.3809, -122.2348
        )
        self.assertLess(night_elevation, 0)
        self.assertIsNotNone(night_azimuth)
        self.assertEqual(_solar_position(None, 47.3809, -122.2348), (None, None))

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
