from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from battery_monitor.collector import CollectorError
from battery_monitor.config import load_settings
from battery_monitor.service import MonitorService
from battery_monitor.storage import RetentionStore


class MonitorServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_outage_becomes_stale_then_offline_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings, store = _settings_and_store(directory)
            collector = _FakeCollector(
                [_snapshot(), CollectorError("connection refused"), _snapshot()]
            )
            monitor = MonitorService(settings, store, collector)

            self.assertTrue(await monitor.poll_once())
            self.assertEqual(monitor.connection_state(), "online")

            self.assertFalse(await monitor.poll_once())
            self.assertEqual(monitor.connection_state(), "stale")
            self.assertEqual(monitor.last_error, "connection refused")
            self.assertEqual(store.health()["status"], "ok")

            monitor.last_success_at = (
                datetime.now(timezone.utc) - timedelta(minutes=3)
            ).isoformat()
            self.assertEqual(monitor.connection_state(), "offline")

            self.assertTrue(await monitor.poll_once())
            self.assertEqual(monitor.connection_state(), "online")
            self.assertIsNone(monitor.last_error)
            store.close()

    async def test_partial_battery_failure_is_degraded_not_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings, store = _settings_and_store(directory)
            snapshot = _snapshot()
            snapshot["batteries"][1]["status"] = "error"
            snapshot["batteries"][1]["last_error"] = "battery timeout"
            monitor = MonitorService(settings, store, _FakeCollector([snapshot]))

            self.assertTrue(await monitor.poll_once())
            self.assertEqual(monitor.connection_state(), "degraded")
            self.assertIsNone(monitor.last_error)
            store.close()

    async def test_reachable_collector_with_old_sample_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings, store = _settings_and_store(directory)
            old_sample = (
                datetime.now(timezone.utc) - timedelta(minutes=2)
            ).isoformat()
            monitor = MonitorService(
                settings,
                store,
                _FakeCollector([_snapshot(captured_at=old_sample)]),
            )

            await monitor.poll_once()

            self.assertEqual(monitor.connection_state(), "stale")
            self.assertTrue(monitor.collector_reachable())
            store.close()

    async def test_replay_backfills_missing_samples_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings, store = _settings_and_store(directory)
            history = [
                _snapshot(sequence=1, captured_at="2026-08-10T12:00:00Z"),
                _snapshot(sequence=2, captured_at="2026-08-10T12:01:00Z"),
            ]
            collector = _FakeCollector([history[-1], history[-1]], history=history)
            monitor = MonitorService(settings, store, collector)

            await monitor.poll_once()
            self.assertEqual(store.stats(settings.retention_days)["row_count"], 4)
            self.assertEqual(monitor.backfilled_snapshot_count, 2)

            await monitor.persist_once()
            await monitor.poll_once()
            self.assertEqual(store.stats(settings.retention_days)["row_count"], 4)
            self.assertEqual(
                store.get_metadata("collector_sequence:test-stream"), "2"
            )
            store.close()

    async def test_older_collector_falls_back_to_live_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings, store = _settings_and_store(directory)
            collector = _FakeCollector(
                [_snapshot(sequence=1)],
                history_error=CollectorError("collector returned HTTP 404", 404),
            )
            monitor = MonitorService(settings, store, collector)

            await monitor.poll_once()
            inserted = await monitor.persist_once()

            self.assertEqual(inserted, 2)
            self.assertFalse(monitor.status()["collector_history_supported"])
            self.assertEqual(store.stats(settings.retention_days)["row_count"], 2)
            store.close()

    async def test_storage_failure_is_reported_and_retried_without_stopping_live_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings, store = _settings_and_store(directory)
            monitor = MonitorService(settings, store, _FakeCollector([_snapshot()]))
            await monitor.poll_once()

            with patch.object(
                store,
                "insert_snapshot",
                side_effect=sqlite3.OperationalError("database or disk is full"),
            ):
                self.assertEqual(await monitor.persist_once(), 0)

            self.assertEqual(monitor.connection_state(), "online")
            self.assertIn("disk is full", monitor.status()["storage_error"])
            self.assertEqual(await monitor.persist_once(), 2)
            self.assertIsNone(monitor.status()["storage_error"])
            store.close()


class _FakeCollector:
    def __init__(
        self,
        snapshots: list[object],
        history: list[dict] | None = None,
        history_error: Exception | None = None,
    ):
        self.snapshots = list(snapshots)
        self.history = history or []
        self.history_error = history_error

    def fetch_snapshot(self) -> dict:
        result = self.snapshots.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_history(self, after_sequence: int, limit: int = 500) -> dict:
        if self.history_error:
            raise self.history_error
        available = [
            snapshot
            for snapshot in self.history
            if snapshot["service"]["sequence"] > after_sequence
        ]
        page = available[:limit]
        return {
            "latest_sequence": self.history[-1]["service"]["sequence"]
            if self.history
            else 0,
            "has_more": len(available) > limit,
            "snapshots": page,
        }


def _settings_and_store(directory: str):
    environment = {
        "BQM_DATA_DIR": directory,
        "BQM_DATABASE_PATH": str(Path(directory) / "monitor.sqlite3"),
        "BQM_STALE_AFTER_SECONDS": "30",
        "BQM_OFFLINE_AFTER_SECONDS": "120",
    }
    with patch.dict(os.environ, environment, clear=True):
        settings = load_settings()
    store = RetentionStore(settings.database_path)
    store.initialize()
    return settings, store


def _snapshot(
    sequence: int | None = None,
    captured_at: str | None = None,
) -> dict:
    service = {"captured_at": captured_at or datetime.now(timezone.utc).isoformat()}
    if sequence is not None:
        service.update({"sequence": sequence, "buffer_stream_id": "test-stream"})
    return {
        "service": service,
        "batteries": [
            {
                "id": "rack-1",
                "address": 1,
                "status": "ok",
                "last_error": None,
                "last_reading": {"soc_percent": 80.0, "alarms": [], "faults": []},
            },
            {
                "id": "rack-2",
                "address": 2,
                "status": "ok",
                "last_error": None,
                "last_reading": {"soc_percent": 79.0, "alarms": [], "faults": []},
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
