from __future__ import annotations

import asyncio
import csv
import io
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .assets import asset_version, cache_control_for, render_index
from .collector import CollectorClient
from .config import Settings, load_settings, rack_details
from .service import MonitorService
from .storage import HistoryMetric, RetentionStore

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    static_version = asset_version(settings.build_commit, STATIC_DIR)
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

    @app.middleware("http")
    async def cache_policy(request: Request, call_next):
        response = await call_next(request)
        policy = cache_control_for(
            request.url.path,
            request.query_params.get("v"),
            static_version,
        )
        if policy:
            response.headers["Cache-Control"] = policy
        return response

    @app.get("/")
    async def index():
        return HTMLResponse(
            render_index(STATIC_DIR / "index.html", static_version),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/healthz")
    async def healthz():
        database = await asyncio.to_thread(store.health)
        if monitor.last_storage_error:
            database = {
                **database,
                "last_write_error": monitor.last_storage_error,
            }
        collector_state = monitor.connection_state()
        payload = {
            "status": "ok" if database["status"] == "ok" else "error",
            "version": __version__,
            "build_commit": settings.build_commit,
            "collector_status": collector_state,
            "last_log_at": monitor.last_log_at,
            "last_error": monitor.last_error,
            "database": database,
            "collector": {
                "status": collector_state,
                "reachable": monitor.collector_reachable(),
                "last_success_at": monitor.last_success_at,
                "last_data_at": monitor.last_data_at,
                "last_attempt_at": monitor.last_attempt_at,
                "error": monitor.last_error,
            },
            "retention_days": settings.retention_days,
        }
        return JSONResponse(
            payload,
            status_code=200 if database["status"] == "ok" else 503,
        )

    @app.get("/api/live")
    async def live():
        snapshot, storage = await asyncio.gather(
            asyncio.to_thread(monitor.cached_snapshot),
            asyncio.to_thread(store.stats, settings.retention_days),
        )
        collector_status = monitor.connection_state()
        batteries = snapshot.get("batteries", [])

        return {
            "version": __version__,
            "build_commit": settings.build_commit,
            "collector_status": collector_status,
            "collector_error": monitor.last_error,
            "collector_reachable": monitor.collector_reachable(),
            "monitor": monitor.status(),
            "storage": storage,
            "summary": _summary(batteries),
            "rack": rack_details(
                settings,
                batteries,
                collector_online=collector_status in {"online", "degraded"},
            ),
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
            "points": await asyncio.to_thread(
                store.history,
                battery_id,
                metric,
                seconds,
                bucket_seconds,
            ),
        }

    @app.get("/api/events")
    async def events(range: str = Query(default="7d"), limit: int = Query(default=80, ge=1, le=300)):
        return {
            "range": range,
            "events": await asyncio.to_thread(
                store.events, _range_seconds(range), limit
            ),
        }

    @app.get("/api/export.csv")
    async def export_csv(
        battery_id: str = Query(default="all"),
        days: int = Query(default=30, ge=1, le=settings.retention_days),
    ):
        rows = await asyncio.to_thread(store.export_rows, battery_id, days)
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
