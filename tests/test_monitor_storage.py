from __future__ import annotations

import tempfile
import time
import unittest
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
            old_cutoff = int(time.time()) - 120 * 24 * 60 * 60
            store.connection.execute(
                "UPDATE readings SET captured_at_unix = ?, captured_at = ?",
                (old_cutoff, "2026-01-01T00:00:00Z"),
            )
            store.connection.commit()

            deleted = store.prune_older_than_days(90)

            self.assertEqual(deleted, 2)
            self.assertEqual(store.stats(retention_days=90)["row_count"], 0)
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


if __name__ == "__main__":
    unittest.main()
