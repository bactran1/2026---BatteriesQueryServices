from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from .collector import CollectorClient, CollectorError
from .config import Settings
from .storage import RetentionStore

logger = logging.getLogger(__name__)


class MonitorService:
    def __init__(self, settings: Settings, store: RetentionStore, collector: CollectorClient):
        self.settings = settings
        self.store = store
        self.collector = collector
        self.started_at = _utc_now()
        self.last_attempt_at: str | None = None
        self.last_success_at: str | None = None
        self.last_data_at: str | None = None
        self.last_log_at: str | None = None
        self.last_prune_at: str | None = None
        self.last_error: str | None = None
        self.last_backfill_error: str | None = None
        self.last_prune_error: str | None = None
        self.last_storage_error: str | None = None
        self.consecutive_failures = 0
        self.log_count = 0
        self.backfilled_snapshot_count = 0
        self._reachable_state = "degraded"
        self._latest_snapshot: dict[str, Any] | None = None
        self._history_supported: bool | None = None
        self._history_retry_at = 0.0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        logger.info("battery monitor connection manager started")
        next_log_at = 0.0
        next_prune_at = 0.0
        while not self._stop.is_set():
            cycle_started = time.monotonic()
            await self.poll_once()

            now = time.monotonic()
            if now >= next_log_at:
                await self.persist_once()
                next_log_at = now + self.settings.log_interval_seconds
            if now >= next_prune_at:
                await self.prune_once()
                next_prune_at = now + 60 * 60

            elapsed = time.monotonic() - cycle_started
            wait_seconds = max(
                0.1, self.settings.live_poll_interval_seconds - elapsed
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()

    async def poll_once(self) -> bool:
        self.last_attempt_at = _utc_now()
        try:
            snapshot = await asyncio.to_thread(self.collector.fetch_snapshot)
        except Exception as exc:
            self.consecutive_failures += 1
            self.last_error = str(exc)
            logger.warning("collector poll failed: %s", exc)
            return False

        self._latest_snapshot = snapshot
        self.last_success_at = _utc_now()
        self.last_data_at = _snapshot_data_at(snapshot) or self.last_success_at
        self.last_error = None
        self.consecutive_failures = 0
        self._reachable_state = _snapshot_state(snapshot)
        await self._backfill(snapshot)
        return True

    async def persist_once(self) -> int:
        snapshot = self._latest_snapshot
        if not snapshot or not snapshot.get("batteries"):
            return 0

        try:
            stream_id, sequence = _snapshot_identity(snapshot)
            if stream_id and sequence is not None and self._history_supported is not False:
                processed = await asyncio.to_thread(
                    self.store.get_metadata, _sequence_key(stream_id)
                )
                if _safe_int(processed) >= sequence:
                    self.last_storage_error = None
                    return 0
                if self.last_backfill_error:
                    return 0

            inserted = await asyncio.to_thread(self.store.insert_snapshot, snapshot)
            if stream_id and sequence is not None:
                await asyncio.to_thread(
                    self.store.set_metadata, _sequence_key(stream_id), str(sequence)
                )
            self.last_storage_error = None
        except Exception as exc:
            self.last_storage_error = str(exc)
            logger.error("archive write failed: %s", exc)
            return 0
        if inserted:
            self.log_count += 1
            self.last_log_at = _snapshot_captured_at(snapshot) or _utc_now()
        return inserted

    async def prune_once(self) -> int:
        try:
            deleted = await asyncio.to_thread(
                self.store.prune_older_than_days, self.settings.retention_days
            )
            self.last_prune_at = _utc_now()
            self.last_prune_error = None
            self.last_storage_error = None
            return deleted
        except Exception as exc:
            self.last_prune_error = str(exc)
            if isinstance(exc, (OSError, sqlite3.Error)):
                self.last_storage_error = str(exc)
            logger.warning("retention prune failed: %s", exc)
            return 0

    async def log_once(self) -> None:
        """Compatibility helper for one explicit archive cycle."""
        if self._latest_snapshot is None:
            await self.poll_once()
        await self.persist_once()
        await self.prune_once()

    @property
    def collector_status(self) -> str:
        return self.connection_state()

    def connection_state(self) -> str:
        contact_age = self.contact_age_seconds()
        if contact_age is None:
            return "offline"
        if self.last_error and contact_age >= self.settings.offline_after_seconds:
            return "offline"
        data_age = self.data_age_seconds()
        if (
            self.last_error
            or data_age is None
            or data_age >= self.settings.stale_after_seconds
        ):
            return "stale"
        return self._reachable_state

    def collector_reachable(self) -> bool:
        contact_age = self.contact_age_seconds()
        return (
            contact_age is not None
            and contact_age < self.settings.offline_after_seconds
            and self.last_error is None
        )

    def data_age_seconds(self) -> float | None:
        if self.last_data_at is None:
            return None
        parsed = _parse_time(self.last_data_at)
        if parsed is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())

    def contact_age_seconds(self) -> float | None:
        if self.last_success_at is None:
            return None
        parsed = _parse_time(self.last_success_at)
        if parsed is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())

    def cached_snapshot(self) -> dict[str, Any]:
        if self._latest_snapshot is not None:
            return self._latest_snapshot
        return {
            "service": {
                "source": "database",
                "message": "waiting for collector; showing last archived readings",
            },
            "batteries": self.store.latest_states(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "collector_status": self.connection_state(),
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_data_at": self.last_data_at,
            "data_age_seconds": self.data_age_seconds(),
            "contact_age_seconds": self.contact_age_seconds(),
            "last_log_at": self.last_log_at,
            "last_prune_at": self.last_prune_at,
            "collector_error": self.last_error,
            "backfill_error": self.last_backfill_error,
            "prune_error": self.last_prune_error,
            "storage_error": self.last_storage_error,
            "consecutive_failures": self.consecutive_failures,
            "live_poll_interval_seconds": self.settings.live_poll_interval_seconds,
            "log_interval_seconds": self.settings.log_interval_seconds,
            "retention_days": self.settings.retention_days,
            "log_count": self.log_count,
            "backfilled_snapshot_count": self.backfilled_snapshot_count,
            "collector_history_supported": self._history_supported,
        }

    async def _backfill(self, snapshot: dict[str, Any]) -> None:
        if self._history_supported is False:
            if time.monotonic() < self._history_retry_at:
                return
            self._history_supported = None
        stream_id, current_sequence = _snapshot_identity(snapshot)
        if not stream_id or current_sequence is None:
            return

        key = _sequence_key(stream_id)
        page_count = 0
        try:
            after_value = await asyncio.to_thread(self.store.get_metadata, key)
            after_sequence = _safe_int(after_value)
            if after_sequence > current_sequence:
                after_sequence = 0

            while after_sequence < current_sequence and page_count < 100:
                page = await asyncio.to_thread(
                    self.collector.fetch_history,
                    after_sequence,
                    self.settings.backfill_page_size,
                )
                self._history_supported = True
                snapshots = [
                    item for item in page.get("snapshots", []) if isinstance(item, dict)
                ]
                if not snapshots:
                    latest = _safe_int(page.get("latest_sequence"))
                    if latest > after_sequence:
                        await asyncio.to_thread(self.store.set_metadata, key, str(latest))
                    break

                await asyncio.to_thread(self.store.insert_snapshots, snapshots)
                self.last_storage_error = None
                sequences = [
                    identity[1]
                    for identity in (_snapshot_identity(item) for item in snapshots)
                    if identity[1] is not None
                ]
                if not sequences:
                    raise CollectorError("collector history snapshots had no sequence IDs")

                next_sequence = max(sequences)
                if next_sequence <= after_sequence:
                    raise CollectorError("collector history sequence did not advance")
                after_sequence = next_sequence
                await asyncio.to_thread(
                    self.store.set_metadata, key, str(after_sequence)
                )
                self.backfilled_snapshot_count += len(snapshots)
                self.log_count += len(snapshots)
                self.last_log_at = _snapshot_captured_at(snapshots[-1]) or _utc_now()
                page_count += 1
                if not page.get("has_more", False):
                    break
            self.last_backfill_error = None
        except CollectorError as exc:
            if exc.status_code == 404:
                self._history_supported = False
                self._history_retry_at = time.monotonic() + 5 * 60
                self.last_backfill_error = None
                logger.info("collector replay API is unavailable; using live archive writes")
            else:
                self.last_backfill_error = str(exc)
                logger.warning("collector history backfill failed: %s", exc)
        except Exception as exc:
            self.last_backfill_error = str(exc)
            if isinstance(exc, (OSError, sqlite3.Error)):
                self.last_storage_error = str(exc)
            logger.warning("collector history backfill failed: %s", exc)


def _snapshot_state(snapshot: dict[str, Any]) -> str:
    batteries = [
        battery for battery in snapshot.get("batteries", []) if isinstance(battery, dict)
    ]
    active = [battery for battery in batteries if battery.get("status") != "disabled"]
    if not active or any(battery.get("status") != "ok" for battery in active):
        return "degraded"
    return "online"


def _snapshot_identity(snapshot: dict[str, Any]) -> tuple[str | None, int | None]:
    service = snapshot.get("service")
    service = service if isinstance(service, dict) else {}
    stream_id = service.get("buffer_stream_id")
    return (str(stream_id) if stream_id else None, _optional_int(service.get("sequence")))


def _snapshot_captured_at(snapshot: dict[str, Any]) -> str | None:
    service = snapshot.get("service")
    if isinstance(service, dict) and isinstance(service.get("captured_at"), str):
        return service["captured_at"]
    return None


def _snapshot_data_at(snapshot: dict[str, Any]) -> str | None:
    captured_at = _snapshot_captured_at(snapshot)
    if captured_at:
        return captured_at
    timestamps = []
    for battery in snapshot.get("batteries", []):
        if not isinstance(battery, dict):
            continue
        reading = battery.get("last_reading")
        if isinstance(reading, dict) and isinstance(reading.get("timestamp"), str):
            timestamps.append(reading["timestamp"])
    return max(timestamps) if timestamps else None


def _sequence_key(stream_id: str) -> str:
    return f"collector_sequence:{stream_id}"


def _safe_int(value: object) -> int:
    parsed = _optional_int(value)
    return parsed if parsed is not None else 0


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
