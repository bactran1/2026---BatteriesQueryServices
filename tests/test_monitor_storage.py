from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from battery_monitor.storage import RetentionStore


class RetentionStoreTests(unittest.TestCase):
    def test_insert_snapshot_and_query_latest_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()

            inserted = store.insert_snapshot(_sample_snapshot())

            self.assertEqual(inserted, 2)
            self.assertEqual(len(store.latest_states()), 2)
            history = store.history(
                battery_id="rack-1",
                metric="soc_percent",
                seconds=3600,
                bucket_seconds=60,
            )
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["battery_id"], "rack-1")
            self.assertEqual(history[0]["value"], 74.5)

            stats = store.stats(retention_days=1095)
            self.assertEqual(stats["row_count"], 2)
            store.close()

    def test_retention_prunes_old_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            store.insert_snapshot(_sample_snapshot())
            energy_snapshot = _energy_snapshot(
                datetime.now(timezone.utc).isoformat(),
                consumption_kwh=8.0,
                solar_generation_kwh=5.0,
                grid_import_kwh=3.0,
            )
            energy_snapshot["batteries"] = []
            store.insert_snapshot(energy_snapshot)
            old_cutoff = int(time.time()) - 120 * 24 * 60 * 60
            old_date = (
                datetime.fromtimestamp(old_cutoff, timezone.utc).date().isoformat()
            )
            store.connection.execute(
                "UPDATE readings SET captured_at_unix = ?, captured_at = ?",
                (old_cutoff, "2026-01-01T00:00:00Z"),
            )
            store.connection.execute(
                """
                UPDATE daily_energy
                SET energy_date = ?, captured_at_unix = ?, captured_at = ?
                """,
                (old_date, old_cutoff, "2026-01-01T00:00:00Z"),
            )
            store.connection.execute(
                """
                UPDATE inverter_readings
                SET captured_at_unix = ?, captured_at = ?
                """,
                (old_cutoff, "2026-01-01T00:00:00Z"),
            )
            store.connection.commit()

            deleted = store.prune_older_than_days(90)

            self.assertEqual(deleted, 4)
            self.assertEqual(store.stats(retention_days=90)["row_count"], 0)
            self.assertEqual(store.stats(retention_days=90)["energy_point_count"], 0)
            self.assertEqual(store.stats(retention_days=90)["inverter_point_count"], 0)
            store.close()

    def test_collector_sequence_is_idempotent_and_health_is_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            snapshot = _sample_snapshot()
            snapshot["service"].update(
                {
                    "sequence": 12,
                    "buffer_stream_id": "stream-a",
                }
            )

            self.assertEqual(store.insert_snapshot(snapshot), 2)
            self.assertEqual(store.insert_snapshot(snapshot), 0)
            self.assertEqual(store.stats(retention_days=1095)["row_count"], 2)
            self.assertEqual(store.health()["status"], "ok")
            self.assertTrue(store.health()["writable"])
            self.assertIsNone(store.get_metadata("__health_check__"))

            store.set_metadata("collector_sequence:stream-a", "12")
            self.assertEqual(store.get_metadata("collector_sequence:stream-a"), "12")
            store.close()

    def test_daily_energy_is_upserted_and_aggregated_by_calendar_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            now = datetime.now(timezone.utc).replace(microsecond=0)
            earlier = now - timedelta(days=35)

            store.insert_snapshot(
                _energy_snapshot(
                    earlier.replace(hour=8).isoformat(),
                    consumption_kwh=4.0,
                    solar_generation_kwh=6.0,
                    grid_import_kwh=1.5,
                )
            )
            store.insert_snapshot(
                _energy_snapshot(
                    now.replace(hour=8).isoformat(),
                    consumption_kwh=12.0,
                    solar_generation_kwh=8.0,
                    grid_import_kwh=3.0,
                )
            )
            store.insert_snapshot(
                _energy_snapshot(
                    now.replace(hour=20).isoformat(),
                    consumption_kwh=15.0,
                    solar_generation_kwh=7.0,
                    grid_import_kwh=None,
                )
            )

            by_month = store.energy_history("month")
            self.assertEqual(len(by_month["points"]), 2)
            self.assertEqual(by_month["totals"]["consumption_kwh"], 19.0)
            self.assertEqual(by_month["totals"]["solar_generation_kwh"], 14.0)
            self.assertEqual(by_month["totals"]["grid_import_kwh"], 4.5)
            by_year = store.energy_history("year")
            self.assertEqual(by_year["totals"], by_month["totals"])

            stats = store.stats(retention_days=1095)
            self.assertEqual(stats["energy_point_count"], 2)
            self.assertEqual(stats["inverter_point_count"], 3)
            self.assertEqual(stats["newest_energy_date"], now.date().isoformat())
            store.close()

    def test_hourly_energy_and_signed_power_history_are_archived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            day = datetime.now(timezone.utc).replace(
                hour=0, minute=20, second=0, microsecond=0
            )
            samples = [
                (day, 0.4, 0.1, 0.3, 1200, 250, 310, 180, 1270),
                (day + timedelta(hours=1), 1.2, 0.6, 0.7, -350, -900, -840, 1250, 700),
                (day + timedelta(hours=2), 2.0, 1.5, 0.9, 500, 700, 760, 1800, 1600),
            ]
            for sequence, sample in enumerate(samples, start=1):
                (
                    timestamp,
                    consumption,
                    solar,
                    grid,
                    grid_w,
                    inverter_battery_w,
                    direct_battery_w,
                    solar_w,
                    load_w,
                ) = sample
                snapshot = _energy_snapshot(
                    timestamp.isoformat(),
                    consumption_kwh=consumption,
                    solar_generation_kwh=solar,
                    grid_import_kwh=grid,
                    grid_power_w=grid_w,
                    inverter_battery_power_w=inverter_battery_w,
                    direct_battery_power_w=direct_battery_w,
                    solar_power_w=solar_w,
                    load_power_w=load_w,
                )
                snapshot["service"].update(
                    {"buffer_stream_id": "stream-a", "sequence": sequence}
                )
                store.insert_snapshot(snapshot)

            hourly = store.energy_history("hour")
            self.assertEqual(hourly["window_days"], 7)
            # The leading bucket has no earlier sample to difference against, and
            # the counters reset at the inverter's local midnight rather than at
            # 00:00 UTC, so it is skipped instead of being credited with whatever
            # total the counter happened to be showing.
            self.assertEqual(len(hourly["points"]), 2)
            self.assertEqual(hourly["points"][0]["consumption_kwh"], 0.8)
            self.assertEqual(hourly["points"][0]["solar_generation_kwh"], 0.5)
            self.assertEqual(hourly["points"][0]["grid_import_kwh"], 0.4)
            self.assertEqual(hourly["points"][1]["consumption_kwh"], 0.8)

            selected_date = store.energy_history("date", day.date().isoformat())
            self.assertEqual(selected_date["view"], "date")
            self.assertEqual(selected_date["selected_date"], day.date().isoformat())
            self.assertEqual(
                selected_date["window_end_unix"]
                - selected_date["window_start_unix"],
                24 * 60 * 60,
            )
            self.assertEqual(len(selected_date["points"]), 3)
            self.assertEqual(selected_date["totals"]["consumption_kwh"], 2.0)
            self.assertEqual(selected_date["totals"]["solar_generation_kwh"], 1.5)
            self.assertEqual(selected_date["totals"]["grid_import_kwh"], 0.9)
            self.assertTrue(
                all(
                    selected_date["window_start_unix"]
                    <= point["unix"]
                    < selected_date["window_end_unix"]
                    for point in selected_date["points"]
                )
            )
            los_angeles_date = store.energy_history(
                "date", "2026-09-04", "America/Los_Angeles"
            )
            self.assertEqual(
                los_angeles_date["window_start"], "2026-09-04T07:00:00Z"
            )
            self.assertEqual(
                los_angeles_date["window_end"], "2026-09-05T07:00:00Z"
            )

            power = store.power_history(seconds=24 * 60 * 60, bucket_seconds=3600)
            self.assertEqual(len(power), 3)
            self.assertEqual(power[0]["grid_power_w"], 1200.0)
            self.assertEqual(power[1]["grid_power_w"], -350.0)
            self.assertEqual(power[1]["battery_power_w"], -840.0)
            self.assertEqual(power[2]["solar_power_w"], 1800.0)
            selected_power = store.power_history(
                seconds=2 * 60 * 60,
                bucket_seconds=3600,
                window_start_unix=int(day.replace(hour=1, minute=0).timestamp()),
                window_end_unix=int(day.replace(hour=3, minute=0).timestamp()),
            )
            self.assertEqual(len(selected_power), 2)
            self.assertTrue(
                all(
                    day.replace(hour=1, minute=0).timestamp()
                    <= point["unix"]
                    < day.replace(hour=3, minute=0).timestamp()
                    for point in selected_power
                )
            )
            inverter_battery_values = store.connection.execute(
                "SELECT battery_power_w FROM inverter_readings"
            ).fetchall()
            self.assertTrue(
                all(row["battery_power_w"] is None for row in inverter_battery_values)
            )
            self.assertEqual(store.stats(retention_days=1095)["inverter_point_count"], 3)
            store.close()

    def test_date_view_sheds_pre_reset_reading_at_local_midnight(self) -> None:
        # The inverter's *_energy_today counters reset at local midnight, but a
        # reading captured a moment before the reset still holds yesterday's whole
        # -day total. It must not be reported as today's 00:00 bar (nor its total).
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            day = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            samples = [
                # 00:00:05 — stale carry-over from yesterday, just before the reset.
                (day + timedelta(seconds=5), 25.0, 18.0, 9.0),
                (day + timedelta(minutes=20), 0.4, 0.1, 0.3),
                (day + timedelta(hours=1, minutes=20), 1.2, 0.6, 0.7),
                (day + timedelta(hours=2, minutes=20), 2.0, 1.5, 0.9),
            ]
            for sequence, (timestamp, consumption, solar, grid) in enumerate(
                samples, start=1
            ):
                snapshot = _energy_snapshot(
                    timestamp.isoformat(),
                    consumption_kwh=consumption,
                    solar_generation_kwh=solar,
                    grid_import_kwh=grid,
                )
                snapshot["service"].update(
                    {"buffer_stream_id": "stream-a", "sequence": sequence}
                )
                store.insert_snapshot(snapshot)

            result = store.energy_history("date", day.date().isoformat(), "UTC")
            points = result["points"]
            self.assertEqual(len(points), 3)
            # The 00:00 bar reflects only the hour's own accumulation (0.4), not the
            # 25.0 kWh the counter was still showing from yesterday.
            self.assertEqual(points[0]["unix"], result["window_start_unix"])
            self.assertEqual(points[0]["consumption_kwh"], 0.4)
            self.assertEqual(points[0]["solar_generation_kwh"], 0.1)
            self.assertEqual(points[0]["grid_import_kwh"], 0.3)
            self.assertEqual(points[1]["consumption_kwh"], 0.8)
            self.assertEqual(points[1]["solar_generation_kwh"], 0.5)
            self.assertEqual(points[2]["consumption_kwh"], 0.8)
            self.assertEqual(points[2]["grid_import_kwh"], 0.2)
            # The day total is the end-of-day counter, not the stale peak.
            self.assertEqual(result["totals"]["consumption_kwh"], 2.0)
            self.assertEqual(result["totals"]["solar_generation_kwh"], 1.5)
            self.assertEqual(result["totals"]["grid_import_kwh"], 0.9)
            store.close()

    def test_power_history_works_from_direct_batteries_without_an_inverter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            snapshot = _sample_snapshot()
            snapshot["service"]["captured_at"] = datetime.now(timezone.utc).isoformat()
            snapshot["batteries"][0]["last_reading"]["power_w"] = 300.0
            snapshot["batteries"][1] = {
                "id": "rack-2",
                "address": 2,
                "status": "ok",
                "last_error": None,
                "last_reading": {"power_w": -125.0},
            }

            store.insert_snapshot(snapshot)

            power = store.power_history(seconds=60 * 60, bucket_seconds=60)
            self.assertEqual(len(power), 1)
            self.assertEqual(power[0]["battery_power_w"], 175.0)
            self.assertIsNone(power[0]["grid_power_w"])
            self.assertIsNone(power[0]["solar_power_w"])
            self.assertIsNone(power[0]["load_power_w"])
            store.close()


    def test_home_and_backup_load_are_archived_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            first = _energy_snapshot(now.isoformat(), None, None, None, load_power_w=0)
            first["inverter"]["last_reading"]["home_load_total_power_w"] = 1500
            second = _energy_snapshot((now + timedelta(seconds=30)).isoformat(), None, None, None, load_power_w=400)
            second["inverter"]["last_reading"]["home_load_total_power_w"] = 700
            store.insert_snapshots([first, second])
            points = store.power_history(86400, 3600)
            self.assertEqual(points[0]["home_load_power_w"], 1100)
            self.assertEqual(points[0]["load_power_w"], 200)

            home_only = _energy_snapshot((now + timedelta(hours=1)).isoformat(), None, None, None)
            home_only["batteries"] = []
            home_only["inverter"]["last_reading"]["home_load_total_power_w"] = 0
            store.insert_snapshot(home_only)
            points = store.power_history(86400, 3600)
            self.assertEqual(points[1]["home_load_power_w"], 0)
            self.assertIsNone(points[1]["load_power_w"])
            store.close()

    def test_existing_inverter_archive_migrates_without_fabricating_home_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RetentionStore(Path(directory) / "monitor.sqlite3")
            store.initialize()
            store.insert_snapshot(_energy_snapshot(
                datetime.now(timezone.utc).isoformat(), 1, 2, 3, load_power_w=420,
            ))
            # Reproduce the previous schema, including a real saved reading.
            store.connection.execute("ALTER TABLE inverter_readings DROP COLUMN home_load_power_w")
            store.connection.commit()
            store.close()
            store.initialize()
            store.initialize()
            points = store.power_history(86400, 3600)
            self.assertEqual(points[0]["load_power_w"], 420)
            self.assertIsNone(points[0]["home_load_power_w"])
            self.assertEqual(store.energy_history("month")["points"][0]["consumption_kwh"], 1)
            store.close()


class HourlyEnergyResetTests(unittest.TestCase):
    """The inverter's *_energy_today_kwh counters reset at its LOCAL midnight.

    The hourly view must not assume that happens at 00:00 UTC, or the midnight
    bucket absorbs a whole day of generation and consumption.
    """

    RESET_HOUR_UTC = 7  # local midnight for America/Los_Angeles (UTC-7)
    LOAD_KW = 1.0
    SOLAR_KW = 2.0
    SOLAR_LOCAL_HOURS = range(8, 18)  # 10 h * 2 kW = 20 kWh/day

    def _cumulative(self, hours_since_reset: float) -> tuple[float, float]:
        load = self.LOAD_KW * hours_since_reset
        solar = self.SOLAR_KW * sum(
            max(0.0, min(hours_since_reset, hour + 1) - hour)
            for hour in self.SOLAR_LOCAL_HOURS
        )
        return load, solar

    def _make_store(self) -> RetentionStore:
        directory = tempfile.mkdtemp()
        # LIFO cleanup: close the connection before the temp dir is removed, so
        # a failed assertion reports itself instead of a Windows unlink error.
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        store = RetentionStore(Path(directory) / "monitor.sqlite3")
        store.initialize()
        self.addCleanup(store.close)
        return store

    def test_hourly_view_has_no_midnight_spike(self) -> None:
        store = self._make_store()

        now = int(time.time())
        start = (now // 3600) * 3600 - 48 * 3600
        while datetime.fromtimestamp(start, timezone.utc).hour != self.RESET_HOUR_UTC:
            start += 3600

        for index in range(48):
            bucket = start + index * 3600
            if bucket > now:
                break
            # Sample mid-hour, so the reset hour holds a partial reading.
            load, solar = self._cumulative((index % 24) + 0.5)
            sampled_at = datetime.fromtimestamp(bucket + 1800, timezone.utc)
            store.insert_snapshot(
                _energy_snapshot(
                    sampled_at.isoformat().replace("+00:00", "Z"),
                    consumption_kwh=round(load, 3),
                    solar_generation_kwh=round(solar, 3),
                    grid_import_kwh=0.0,
                )
            )

        points = store.energy_history("hour")["points"]
        self.assertGreater(len(points), 24)

        by_hour = {
            datetime.fromtimestamp(point["unix"], timezone.utc).hour: point
            for point in points
        }

        # No hour may exceed what the simulated system can physically produce.
        for point in points:
            self.assertLessEqual((point["solar_generation_kwh"] or 0), self.SOLAR_KW)
            self.assertLessEqual((point["consumption_kwh"] or 0), self.LOAD_KW)

        # The 00:00 UTC bucket is an ordinary hour, not a whole day's worth.
        self.assertAlmostEqual(by_hour[0]["consumption_kwh"], self.LOAD_KW, places=3)

        # The hour containing the local-midnight reset keeps its partial energy
        # instead of being dropped.
        self.assertAlmostEqual(
            by_hour[self.RESET_HOUR_UTC]["consumption_kwh"], 0.5, places=3
        )


def _sample_snapshot() -> dict:
    return {
        "service": {"poll_count": 1},
        "batteries": [
            {
                "id": "rack-1",
                "address": 1,
                "status": "ok",
                "last_error": None,
                "last_reading": {
                    "id": "rack-1",
                    "address": 1,
                    "voltage_v": 52.4,
                    "current_a": -4.1,
                    "power_w": -214.8,
                    "soc_percent": 74.5,
                    "soh_percent": 100,
                    "remaining_capacity_ah": 74.5,
                    "full_capacity_ah": 100,
                    "rated_capacity_ah": 100,
                    "cycle_count": 4,
                    "cell_voltage_delta_v": 0.011,
                    "average_cell_voltage_v": 3.275,
                    "mosfet_temperature_c": 25.5,
                    "ambient_temperature_c": 24.8,
                    "alarms": [],
                    "faults": [],
                },
            },
            {
                "id": "rack-2",
                "address": 2,
                "status": "error",
                "last_error": "timeout",
                "last_reading": None,
            },
        ],
    }


def _energy_snapshot(
    timestamp: str,
    consumption_kwh: float | None,
    solar_generation_kwh: float | None,
    grid_import_kwh: float | None,
    grid_power_w: float | None = None,
    inverter_battery_power_w: float | None = None,
    direct_battery_power_w: float | None = None,
    solar_power_w: float | None = None,
    load_power_w: float | None = None,
) -> dict:
    snapshot = _sample_snapshot()
    snapshot["service"]["captured_at"] = timestamp
    if direct_battery_power_w is not None:
        reading = snapshot["batteries"][0]["last_reading"]
        reading["power_w"] = direct_battery_power_w
        reading["current_a"] = direct_battery_power_w / reading["voltage_v"]
    snapshot["inverter"] = {
        "id": "inverter-1",
        "status": "ok",
        "last_reading": {
            "id": "inverter-1",
            "timestamp": timestamp,
            "load_energy_today_kwh": consumption_kwh,
            "pv_energy_today_kwh": solar_generation_kwh,
            "grid_import_energy_today_kwh": grid_import_kwh,
            "grid_import_power_w": max(grid_power_w, 0) if grid_power_w is not None else None,
            "grid_export_power_w": max(-grid_power_w, 0) if grid_power_w is not None else None,
            "battery_power_w": inverter_battery_power_w,
            "pv_total_power_w": solar_power_w,
            "load_total_power_w": load_power_w,
        },
    }
    return snapshot


if __name__ == "__main__":
    unittest.main()
