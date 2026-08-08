from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import __version__
from .config import Settings, load_settings
from .metrics import MetricsPublisher
from .poller import BatteryPoller

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    metrics = MetricsPublisher()
    poller = BatteryPoller(settings=settings, metrics=metrics)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(poller.run(), name="battery-poller")
        try:
            yield
        finally:
            await poller.stop()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="Batteries Query Service",
        version=__version__,
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz():
        return await poller.health()

    @app.get("/api/readings")
    async def readings():
        return await poller.snapshot()

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
