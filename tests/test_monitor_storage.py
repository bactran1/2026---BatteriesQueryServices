from __future__ import annotations

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
            store.connection.commit()

            deleted = store.prune_older_than_days(90)

            self.assertEqual(deleted, 3)
            self.assertEqual(store.stats(retention_days=90)["row_count"], 0)
            self.assertEqual(store.stats(retention_days=90)["energy_point_count"], 0)
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

            by_date = store.energy_history("date")
            self.assertEqual(len(by_date["points"]), 2)
            latest = by_date["points"][-1]
            self.assertEqual(latest["period"], now.date().isoformat())
            self.assertEqual(latest["consumption_kwh"], 15.0)
            self.assertEqual(latest["solar_generation_kwh"], 8.0)
            self.assertEqual(latest["grid_import_kwh"], 3.0)
            self.assertEqual(by_date["totals"]["consumption_kwh"], 19.0)
            self.assertEqual(by_date["totals"]["solar_generation_kwh"], 14.0)
            self.assertEqual(by_date["totals"]["grid_import_kwh"], 4.5)

            by_month = store.energy_history("month")
            self.assertEqual(len(by_month["points"]), 2)
            self.assertEqual(by_month["totals"], by_date["totals"])
            by_year = store.energy_history("year")
            self.assertEqual(by_year["totals"], by_date["totals"])

            stats = store.stats(retention_days=1095)
            self.assertEqual(stats["energy_point_count"], 2)
            self.assertEqual(stats["newest_energy_date"], now.date().isoformat())
            store.close()


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
) -> dict:
    snapshot = _sample_snapshot()
    snapshot["service"]["captured_at"] = timestamp
    snapshot["inverter"] = {
        "id": "inverter-1",
        "status": "ok",
        "last_reading": {
            "id": "inverter-1",
            "timestamp": timestamp,
            "load_energy_today_kwh": consumption_kwh,
            "pv_energy_today_kwh": solar_generation_kwh,
            "grid_import_energy_today_kwh": grid_import_kwh,
        },
    }
    return snapshot


if __name__ == "__main__":
    unittest.main()
