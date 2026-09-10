from __future__ import annotations

import asyncio
import csv
import hmac
import io
import logging
import time
from contextlib import asynccontextmanager, suppress
from datetime import date as calendar_date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .admin import SESSION_COOKIE, SESSION_TTL_SECONDS, AdminAuth, AdminSettings
from .assets import asset_version, cache_control_for, render_index
from .collector import CollectorClient, CollectorError
from .config import Settings, load_settings, rack_details
from .service import MonitorService
from .storage import EnergyView, HistoryMetric, RetentionStore

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
    admin_settings = AdminSettings(store)
    admin_auth = AdminAuth(store)
    monitor = MonitorService(
        settings=settings,
        store=store,
        collector=collector,
        retention_provider=lambda: admin_settings.effective_retention(settings),
    )

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
        effective = admin_settings.effective_settings(settings)
        snapshot, storage = await asyncio.gather(
            asyncio.to_thread(monitor.cached_snapshot),
            asyncio.to_thread(store.stats, effective.retention_days),
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
                effective,
                batteries,
                collector_online=collector_status in {"online", "degraded"},
            ),
            "ui": {
                "energy_glow_strength": admin_settings.glow_strength(),
                "energy_line_glow": admin_settings.line_glow(),
                "energy_active_opacity": admin_settings.active_opacity(),
                "battery_reserve_percent": effective.battery_reserve_percent,
            },
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

    @app.get("/api/energy")
    async def energy(
        view: EnergyView = Query(default="month"),
        date: str | None = Query(default=None),
        timezone_name: str = Query(default="UTC", alias="timezone"),
    ):
        if date is not None:
            try:
                calendar_date.fromisoformat(date)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail="Date must use YYYY-MM-DD"
                ) from exc
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(status_code=400, detail="Unknown timezone") from exc
        return await asyncio.to_thread(
            store.energy_history,
            view,
            date,
            timezone_name,
        )

    @app.get("/api/power-history")
    async def power_history(
        range: str = Query(default="24h"),
        date: str | None = Query(default=None),
        timezone_name: str = Query(default="UTC", alias="timezone"),
    ):
        selected_date = None
        window_start = None
        window_end = None
        window_start_unix = None
        window_end_unix = None
        if range == "date":
            (
                selected_date,
                window_start,
                window_end,
                window_start_unix,
                window_end_unix,
            ) = _calendar_day_window(date, timezone_name)
            seconds = window_end_unix - window_start_unix
            bucket_seconds = 5 * 60
        else:
            seconds = _range_seconds(range)
            bucket_seconds = _bucket_seconds(seconds)

        payload = {
            "range": range,
            "bucket_seconds": bucket_seconds,
            "sources": {
                "battery_power_w": "direct_battery_telemetry",
                "grid_power_w": "inverter_telemetry",
                "solar_power_w": "inverter_telemetry",
                "load_power_w": "inverter_telemetry",
                "home_load_power_w": "inverter_telemetry",
            },
            "points": await asyncio.to_thread(
                store.power_history,
                seconds,
                bucket_seconds,
                window_start_unix,
                window_end_unix,
            ),
        }
        if range == "date":
            payload.update(
                {
                    "selected_date": selected_date,
                    "timezone": timezone_name,
                    "window_start": window_start,
                    "window_start_unix": window_start_unix,
                    "window_end": window_end,
                    "window_end_unix": window_end_unix,
                }
            )
        return payload

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

    # ---- Admin -----------------------------------------------------------
    def _require_admin(request: Request) -> dict:
        payload = admin_auth.verify_token(request.cookies.get(SESSION_COOKIE))
        if payload is None:
            raise HTTPException(status_code=401, detail="Admin authentication required")
        return payload

    def _require_csrf(request: Request, payload: dict) -> None:
        header = request.headers.get("X-CSRF-Token", "")
        expected = str(payload.get("csrf", ""))
        if not header or not hmac.compare_digest(
            header.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")

    async def _json_body(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001 - any parse failure is a bad request
            raise HTTPException(status_code=400, detail="Expected a JSON body") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Expected a JSON object")
        return body

    def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=max_age,
            httponly=True,
            samesite="strict",
            path="/",
        )

    @app.get("/admin")
    async def admin_page():
        return HTMLResponse(
            render_index(STATIC_DIR / "admin.html", static_version),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/admin/session")
    async def admin_session(request: Request):
        payload = admin_auth.verify_token(request.cookies.get(SESSION_COOKIE))
        session_minutes = admin_settings.session_minutes()
        body = {
            "authenticated": payload is not None,
            "configured": admin_auth.is_configured(),
            "csrf": payload.get("csrf") if payload else None,
            "session_minutes": session_minutes,
        }
        if payload is None:
            return body
        # The dashboard calls this on user activity, so slide the idle window
        # forward (keeping the same CSRF token) each time it does.
        ttl = session_minutes * 60
        token, _ = admin_auth.issue_token(ttl_seconds=ttl, csrf=str(payload.get("csrf")))
        response = JSONResponse(body)
        _set_session_cookie(response, token, ttl)
        return response

    @app.post("/api/admin/login")
    async def admin_login(request: Request):
        body = await _json_body(request)
        if not admin_auth.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Admin access is not configured (set BQM_ADMIN_PASSWORD).",
            )
        if not admin_auth.verify_login(str(body.get("password") or "")):
            raise HTTPException(status_code=401, detail="Incorrect password")
        session_minutes = admin_settings.session_minutes()
        ttl = session_minutes * 60
        token, csrf = admin_auth.issue_token(ttl_seconds=ttl)
        response = JSONResponse(
            {"ok": True, "csrf": csrf, "session_minutes": session_minutes}
        )
        _set_session_cookie(response, token, ttl)
        return response

    @app.post("/api/admin/logout")
    async def admin_logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/api/admin/storage")
    async def admin_storage(request: Request):
        _require_admin(request)
        effective = admin_settings.effective_settings(settings)
        stats, health, integrity = await asyncio.gather(
            asyncio.to_thread(store.stats, effective.retention_days),
            asyncio.to_thread(store.health),
            asyncio.to_thread(store.integrity_check),
        )
        return {"stats": stats, "health": health, "integrity": integrity}

    @app.post("/api/admin/prune")
    async def admin_prune(request: Request):
        payload = _require_admin(request)
        _require_csrf(request, payload)
        effective = admin_settings.effective_settings(settings)
        deleted = await asyncio.to_thread(
            store.prune_older_than_days, effective.retention_days
        )
        return {"deleted": deleted, "retention_days": effective.retention_days}

    @app.get("/api/admin/backup.sqlite")
    async def admin_backup(request: Request):
        _require_admin(request)
        data = await asyncio.to_thread(store.backup_bytes)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"battery-monitor-backup-{stamp}.sqlite3"
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/admin/reset")
    async def admin_reset(request: Request):
        payload = _require_admin(request)
        _require_csrf(request, payload)
        body = await _json_body(request)
        if str(body.get("confirm") or "") != "DELETE":
            raise HTTPException(
                status_code=400,
                detail='Send {"confirm": "DELETE"} to erase all stored history.',
            )
        deleted = await asyncio.to_thread(store.purge_all)
        return {"ok": True, "deleted": deleted}

    @app.post("/api/admin/poll")
    async def admin_poll(request: Request):
        payload = _require_admin(request)
        _require_csrf(request, payload)
        return await monitor.force_cycle()

    @app.post("/api/admin/polling")
    async def admin_polling(request: Request):
        payload = _require_admin(request)
        _require_csrf(request, payload)
        body = await _json_body(request)
        if bool(body.get("paused")):
            monitor.pause()
        else:
            monitor.resume()
        return {"paused": monitor.paused}

    @app.get("/api/admin/collector-test")
    async def admin_collector_test(request: Request):
        _require_admin(request)
        started = time.monotonic()
        try:
            snapshot = await asyncio.to_thread(collector.fetch_snapshot)
        except CollectorError as exc:
            return {
                "reachable": False,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "collector_url": collector.base_url,
                "error": str(exc),
                "status_code": exc.status_code,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "reachable": False,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "collector_url": collector.base_url,
                "error": str(exc),
            }
        batteries = snapshot.get("batteries", []) if isinstance(snapshot, dict) else []
        return {
            "reachable": True,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "collector_url": collector.base_url,
            "battery_count": len(batteries),
        }

    @app.get("/api/admin/diagnostics")
    async def admin_diagnostics(request: Request):
        _require_admin(request)
        return {
            "monitor": monitor.status(),
            "collector_status": monitor.connection_state(),
            "collector_reachable": monitor.collector_reachable(),
            "collector_url": collector.base_url,
            "paused": monitor.paused,
        }

    @app.get("/api/admin/config")
    async def admin_get_config(request: Request):
        _require_admin(request)
        return admin_settings.public_config(settings)

    @app.put("/api/admin/config")
    async def admin_put_config(request: Request):
        payload = _require_admin(request)
        _require_csrf(request, payload)
        body = await _json_body(request)
        try:
            return await asyncio.to_thread(admin_settings.update, body, settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/admin/app-info")
    async def admin_app_info(request: Request):
        _require_admin(request)
        effective = admin_settings.effective_settings(settings)
        return {
            "version": __version__,
            "build_commit": settings.build_commit,
            "started_at": monitor.started_at,
            "paused": monitor.paused,
            "host": settings.host,
            "port": settings.port,
            "collector_url": settings.collector_url,
            "database_path": str(settings.database_path),
            "retention_days": effective.retention_days,
            "session_minutes": admin_settings.session_minutes(),
            "live_poll_interval_seconds": settings.live_poll_interval_seconds,
            "log_interval_seconds": settings.log_interval_seconds,
        }

    @app.post("/api/admin/password")
    async def admin_password(request: Request):
        payload = _require_admin(request)
        _require_csrf(request, payload)
        body = await _json_body(request)
        if not admin_auth.verify_login(str(body.get("current_password") or "")):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        try:
            admin_auth.set_password(str(body.get("new_password") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

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
    current_values = [
        reading.get("current_a")
        for reading in readings
        if isinstance(reading.get("current_a"), (int, float))
    ]
    voltage_values = [
        reading.get("voltage_v")
        for reading in readings
        if isinstance(reading.get("voltage_v"), (int, float))
    ]
    remaining_capacity = [
        reading.get("remaining_capacity_ah")
        for reading in readings
        if isinstance(reading.get("remaining_capacity_ah"), (int, float))
    ]
    full_capacity = [
        reading.get("full_capacity_ah")
        for reading in readings
        if isinstance(reading.get("full_capacity_ah"), (int, float))
    ]
    mosfet_temperatures = [
        reading.get("mosfet_temperature_c")
        for reading in readings
        if isinstance(reading.get("mosfet_temperature_c"), (int, float))
    ]
    ambient_temperatures = [
        reading.get("ambient_temperature_c")
        for reading in readings
        if isinstance(reading.get("ambient_temperature_c"), (int, float))
    ]
    cell_deltas = [
        reading.get("cell_voltage_delta_v")
        for reading in readings
        if isinstance(reading.get("cell_voltage_delta_v"), (int, float))
    ]
    alarm_count = sum(len(reading.get("alarms") or []) for reading in readings)
    fault_count = sum(len(reading.get("faults") or []) for reading in readings)
    return {
        "source": "direct_battery_telemetry",
        "battery_count": len(batteries),
        "online_count": online,
        "average_soc_percent": round(sum(soc_values) / len(soc_values), 1)
        if soc_values
        else None,
        "total_power_w": round(sum(power_values), 1) if power_values else None,
        "total_current_a": round(sum(current_values), 2) if current_values else None,
        "average_voltage_v": round(sum(voltage_values) / len(voltage_values), 2)
        if voltage_values
        else None,
        "remaining_capacity_ah": round(sum(remaining_capacity), 1)
        if remaining_capacity
        else None,
        "full_capacity_ah": round(sum(full_capacity), 1) if full_capacity else None,
        "average_mosfet_temperature_c": round(
            sum(mosfet_temperatures) / len(mosfet_temperatures), 1
        )
        if mosfet_temperatures
        else None,
        "maximum_mosfet_temperature_c": round(max(mosfet_temperatures), 1)
        if mosfet_temperatures
        else None,
        "average_ambient_temperature_c": round(
            sum(ambient_temperatures) / len(ambient_temperatures), 1
        )
        if ambient_temperatures
        else None,
        "maximum_ambient_temperature_c": round(max(ambient_temperatures), 1)
        if ambient_temperatures
        else None,
        "maximum_cell_voltage_delta_v": round(max(cell_deltas), 4)
        if cell_deltas
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


def _calendar_day_window(
    date_value: str | None, timezone_name: str
) -> tuple[str, str, str, int, int]:
    try:
        selected_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Unknown timezone") from exc

    if date_value is None:
        selected_date = datetime.now(selected_zone).date()
    else:
        try:
            selected_date = calendar_date.fromisoformat(date_value)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Date must use YYYY-MM-DD"
            ) from exc

    window_start = datetime(
        selected_date.year,
        selected_date.month,
        selected_date.day,
        tzinfo=selected_zone,
    )
    window_end = window_start + timedelta(days=1)
    return (
        selected_date.isoformat(),
        window_start.isoformat(),
        window_end.isoformat(),
        int(window_start.timestamp()),
        int(window_end.timestamp()),
    )


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
