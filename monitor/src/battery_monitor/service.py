from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .collector import CollectorClient
from .config import Settings
from .storage import RetentionStore

logger = logging.getLogger(__name__)


class MonitorService:
    def __init__(self, settings: Settings, store: RetentionStore, collector: CollectorClient):
        self.settings = settings
        self.store = store
        self.collector = collector
        self.started_at = _utc_now()
        self.last_log_at: str | None = None
        self.last_prune_at: str | None = None
        self.last_error: str | None = None
        self.collector_status = "pending"
        self.log_count = 0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        logger.info("battery monitor started")
        while not self._stop.is_set():
            await self.log_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.log_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()

    async def log_once(self) -> None:
        try:
            snapshot = await asyncio.to_thread(self.collector.fetch_snapshot)
            await asyncio.to_thread(self.store.insert_snapshot, snapshot)
            self.collector_status = "ok"
            self.last_error = None
            self.last_log_at = _utc_now()
            self.log_count += 1
        except Exception as exc:
            logger.warning("monitor log cycle failed: %s", exc)
            self.collector_status = "error"
            self.last_error = str(exc)

        try:
            await asyncio.to_thread(self.store.prune_older_than_days, self.settings.retention_days)
            self.last_prune_at = _utc_now()
        except Exception as exc:
            logger.warning("retention prune failed: %s", exc)
            self.last_error = str(exc)

    def status(self) -> dict:
        return {
            "started_at": self.started_at,
            "collector_status": self.collector_status,
            "last_log_at": self.last_log_at,
            "last_prune_at": self.last_prune_at,
            "last_error": self.last_error,
            "log_interval_seconds": self.settings.log_interval_seconds,
            "retention_days": self.settings.retention_days,
            "log_count": self.log_count,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
