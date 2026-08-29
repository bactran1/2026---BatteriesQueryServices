from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__
from .buffer import SnapshotBuffer
from .config import Settings, load_settings
from .metrics import MetricsPublisher
from .poller import BatteryPoller

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    metrics = MetricsPublisher()
    snapshot_buffer = (
        SnapshotBuffer(Path(settings.buffer.path)) if settings.buffer.enabled else None
    )
    poller = BatteryPoller(
        settings=settings,
        metrics=metrics,
        snapshot_buffer=snapshot_buffer,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if snapshot_buffer is not None:
            await asyncio.to_thread(snapshot_buffer.initialize)
        task = asyncio.create_task(poller.run(), name="battery-poller")
        try:
            yield
        finally:
            await poller.stop()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if snapshot_buffer is not None:
                await asyncio.to_thread(snapshot_buffer.close)

    app = FastAPI(
        title="Batteries Query Service",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def live_data_cache_policy(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/healthz" or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    async def healthz():
        return await poller.health()

    @app.get("/api/readings")
    async def readings():
        return await poller.snapshot()

    @app.get("/api/readings/history")
    async def reading_history(after_sequence: int = 0, limit: int = 500):
        if snapshot_buffer is None:
            raise HTTPException(status_code=404, detail="Collector replay buffer is disabled")
        return await asyncio.to_thread(
            snapshot_buffer.read_after, after_sequence, limit
        )

    @app.get("/api/inverter")
    async def inverter():
        snapshot = await poller.snapshot()
        return snapshot["inverter"]

    @app.get("/api/readings/{battery_id}")
    async def reading(battery_id: str):
        snapshot = await poller.snapshot()
        for battery in snapshot["batteries"]:
            if battery["id"] == battery_id:
                return battery
        raise HTTPException(status_code=404, detail=f"Unknown battery id: {battery_id}")

    @app.get("/api/config")
    async def config():
        return settings.safe_dict()

    @app.get("/metrics")
    async def metrics_endpoint():
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("starting Batteries Query Service")
    uvicorn.run(create_app(settings), host=settings.server.host, port=settings.server.port)
