from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .config import BatterySettings, Settings
from .ecoworthy import EcoWorthyModbusClient, SerialConnectionSettings
from .metrics import MetricsPublisher

logger = logging.getLogger(__name__)


class BatteryPoller:
    def __init__(self, settings: Settings, metrics: MetricsPublisher):
        self.settings = settings
        self.metrics = metrics
        self.started_at = _utc_now()
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._states: dict[str, dict[str, Any]] = {
            battery.id: self._pending_state(battery) for battery in settings.batteries
        }
        self._poll_count = 0

    async def run(self) -> None:
        logger.info("battery poller started with %d configured batteries", len(self.settings.batteries))
        while not self._stop.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.polling.interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()

    async def poll_once(self) -> None:
        self._poll_count += 1
        for battery in self.settings.batteries:
            if not battery.enabled:
                await self._set_state(battery.id, self._disabled_state(battery))
                continue

            serial_port = battery.resolved_serial_port(self.settings.serial.port)
            client = EcoWorthyModbusClient(
                SerialConnectionSettings(
                    port=serial_port,
                    baudrate=self.settings.serial.baudrate,
                    timeout_seconds=self.settings.serial.timeout_seconds,
                )
            )

            try:
                reading = await asyncio.to_thread(
                    client.read_pack_status,
                    battery.address,
                    battery.id,
                )
            except Exception as exc:
                logger.warning(
                    "battery poll failed for %s address %s on %s: %s",
                    battery.id,
                    battery.address,
                    serial_port,
                    exc,
                )
                self.metrics.record_error(battery.id, battery.address)
                await self._set_state(
                    battery.id,
                    {
                        "id": battery.id,
                        "address": battery.address,
                        "serial_port": serial_port,
                        "status": "error",
                        "last_polled_at": _utc_now(),
                        "last_error": str(exc),
                        "last_reading": None,
                    },
                )
                continue

            self.metrics.record_reading(reading)
            await self._set_state(
                battery.id,
                {
                    "id": battery.id,
                    "address": battery.address,
                    "serial_port": serial_port,
                    "status": "ok",
                    "last_polled_at": _utc_now(),
                    "last_error": None,
                    "last_reading": reading.to_dict(),
                },
            )

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            batteries = [dict(state) for state in self._states.values()]
        return {
            "service": {
                "started_at": self.started_at,
                "build_commit": self.settings.build_commit,
                "poll_count": self._poll_count,
                "poll_interval_seconds": self.settings.polling.interval_seconds,
            },
            "batteries": batteries,
        }

    async def health(self) -> dict[str, Any]:
        snapshot = await self.snapshot()
        statuses = [battery["status"] for battery in snapshot["batteries"]]
        return {
            "status": "ok",
            "version": __version__,
            "build_commit": self.settings.build_commit,
            "battery_count": len(statuses),
            "ok_count": statuses.count("ok"),
            "error_count": statuses.count("error"),
            "pending_count": statuses.count("pending"),
            "poll_count": self._poll_count,
        }

    async def _set_state(self, battery_id: str, state: dict[str, Any]) -> None:
        async with self._lock:
            self._states[battery_id] = state

    def _pending_state(self, battery: BatterySettings) -> dict[str, Any]:
        return {
            "id": battery.id,
            "address": battery.address,
            "serial_port": battery.resolved_serial_port(self.settings.serial.port),
            "status": "pending",
            "last_polled_at": None,
            "last_error": None,
            "last_reading": None,
        }

    def _disabled_state(self, battery: BatterySettings) -> dict[str, Any]:
        return {
            "id": battery.id,
            "address": battery.address,
            "serial_port": battery.resolved_serial_port(self.settings.serial.port),
            "status": "disabled",
            "last_polled_at": _utc_now(),
            "last_error": None,
            "last_reading": None,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
