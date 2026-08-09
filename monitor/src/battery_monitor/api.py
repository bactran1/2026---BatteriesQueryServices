from __future__ import annotations

import asyncio
import csv
import io
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .collector import CollectorClient, CollectorError
from .config import Settings, load_settings
from .service import MonitorService
from .storage import HistoryMetric, RetentionStore

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = RetentionStore(settings.database_path)
    collector = CollectorClient(
        base_url=settings.collector_url,
        timeout_seconds=settings.collector_timeout_seconds,
    )
    monitor = MonitorService(settings=settings, store=store, collector=collector)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        task = asyncio.create_task(monitor.run(), name="battery-monitor")
        try:
            yield
        finally:
            await monitor.stop()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            store.close()

    app = FastAPI(
        title="Battery Monitor",
        version=__version__,
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def healthz():
        return {
            "status": "ok",
            "version": __version__,
            "collector_status": monitor.collector_status,
            "last_log_at": monitor.last_log_at,
            "last_error": monitor.last_error,
            "retention_days": settings.retention_days,
        }

    @app.get("/api/live")
    async def live():
        try:
            snapshot = await asyncio.to_thread(collector.fetch_snapshot)
            collector_status = "ok"
            collector_error = None
            batteries = snapshot.get("batteries", [])
        except CollectorError as exc:
            snapshot = {
                "service": {
                    "source": "database",
                    "message": "collector unavailable",
                },
                "batteries": store.latest_states(),
            }
            collector_status = "error"
            collector_error = str(exc)
            batteries = snapshot["batteries"]

        return {
            "version": __version__,
            "collector_status": collector_status,
            "collector_error": collector_error,
            "monitor": monitor.status(),
            "storage": store.stats(settings.retention_days),
            "summary": _summary(batteries),
            "snapshot": snapshot,
        }

    @app.get("/api/history")
    async def history(
        battery_id: str = Query(default="all"),
        metric: HistoryMetric = Query(default="soc_percent"),
        range: str = Query(default="24h"),
    ):
        seconds = _range_seconds(range)
        bucket_seconds = _bucket_seconds(seconds)
        return {
            "battery_id": battery_id,
            "metric": metric,
            "range": range,
            "bucket_seconds": bucket_seconds,
            "points": store.history(
                battery_id=battery_id,
                metric=metric,
                seconds=seconds,
                bucket_seconds=bucket_seconds,
            ),
        }

    @app.get("/api/events")
    async def events(range: str = Query(default="7d"), limit: int = Query(default=80, ge=1, le=300)):
        return {
            "range": range,
            "events": store.events(seconds=_range_seconds(range), limit=limit),
        }

    @app.get("/api/export.csv")
    async def export_csv(
        battery_id: str = Query(default="all"),
        days: int = Query(default=30, ge=1, le=settings.retention_days),
    ):
        rows = store.export_rows(battery_id=battery_id, days=days)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=store.export_fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        filename = f"battery-log-{battery_id}-{days}d.csv".replace("/", "-")
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return app


def _summary(batteries: list[dict]) -> dict:
    readings = [
        battery.get("last_reading")
        for battery in batteries
        if isinstance(battery.get("last_reading"), dict)
    ]
    online = sum(1 for battery in batteries if battery.get("status") == "ok")
    soc_values = [
        reading.get("soc_percent")
        for reading in readings
        if isinstance(reading.get("soc_percent"), (int, float))
    ]
    power_values = [
        reading.get("power_w")
        for reading in readings
        if isinstance(reading.get("power_w"), (int, float))
    ]
    remaining_capacity = [
        reading.get("remaining_capacity_ah")
        for reading in readings
        if isinstance(reading.get("remaining_capacity_ah"), (int, float))
    ]
    alarm_count = sum(len(reading.get("alarms") or []) for reading in readings)
    fault_count = sum(len(reading.get("faults") or []) for reading in readings)
    return {
        "battery_count": len(batteries),
        "online_count": online,
        "average_soc_percent": round(sum(soc_values) / len(soc_values), 1)
        if soc_values
        else None,
        "total_power_w": round(sum(power_values), 1) if power_values else None,
        "remaining_capacity_ah": round(sum(remaining_capacity), 1)
        if remaining_capacity
        else None,
        "alarm_count": alarm_count,
        "fault_count": fault_count,
    }


def _range_seconds(value: str) -> int:
    ranges = {
        "1h": 60 * 60,
        "6h": 6 * 60 * 60,
        "24h": 24 * 60 * 60,
        "7d": 7 * 24 * 60 * 60,
        "30d": 30 * 24 * 60 * 60,
        "365d": 365 * 24 * 60 * 60,
        "3y": 1095 * 24 * 60 * 60,
    }
    try:
        return ranges[value]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported range: {value}") from exc


def _bucket_seconds(seconds: int) -> int:
    if seconds <= 6 * 60 * 60:
        return 60
    if seconds <= 24 * 60 * 60:
        return 5 * 60
    if seconds <= 7 * 24 * 60 * 60:
        return 30 * 60
    if seconds <= 30 * 24 * 60 * 60:
        return 3 * 60 * 60
    if seconds <= 365 * 24 * 60 * 60:
        return 24 * 60 * 60
    return 7 * 24 * 60 * 60


def main() -> None:
    import uvicorn

    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("starting Battery Monitor")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
