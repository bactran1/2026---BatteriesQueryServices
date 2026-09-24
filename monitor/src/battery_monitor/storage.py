from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import date as date_type
from datetime import datetime, time as time_type, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from .tariff import TOU_PERIODS, period_for

logger = logging.getLogger(__name__)

HistoryMetric = Literal[
    "voltage_v",
    "current_a",
    "power_w",
    "soc_percent",
    "soh_percent",
    "cell_voltage_delta_v",
    "average_cell_voltage_v",
    "mosfet_temperature_c",
    "ambient_temperature_c",
]

EnergyView = Literal["hour", "date", "month", "year"]


HISTORY_COLUMNS: dict[str, str] = {
    "voltage_v": "voltage_v",
    "current_a": "current_a",
    "power_w": "power_w",
    "soc_percent": "soc_percent",
    "soh_percent": "soh_percent",
    "cell_voltage_delta_v": "cell_voltage_delta_v",
    "average_cell_voltage_v": "average_cell_voltage_v",
    "mosfet_temperature_c": "mosfet_temperature_c",
    "ambient_temperature_c": "ambient_temperature_c",
}


class RetentionStore:
    export_fieldnames = [
        "captured_at",
        "collector_stream_id",
        "collector_sequence",
        "battery_id",
        "address",
        "status",
        "voltage_v",
        "current_a",
        "power_w",
        "soc_percent",
        "soh_percent",
        "remaining_capacity_ah",
        "full_capacity_ah",
        "rated_capacity_ah",
        "cycle_count",
        "cell_voltage_delta_v",
        "alarm_count",
        "fault_count",
        "last_error",
    ]

    def __init__(
        self, database_path: Path, tariff_timezone: str = "America/Los_Angeles"
    ):
        self.database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        # Time-of-use periods are wall-clock hours in the *utility's* timezone,
        # not the viewer's, so the rollup is keyed by the tariff's own calendar.
        self.tariff_timezone = tariff_timezone
        self._tariff_zone = ZoneInfo(tariff_timezone)

    def initialize(self) -> None:
        with self._lock:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self.connection
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    captured_at_unix INTEGER NOT NULL,
                    collector_stream_id TEXT,
                    collector_sequence INTEGER,
                    battery_id TEXT NOT NULL,
                    address INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    voltage_v REAL,
                    current_a REAL,
                    power_w REAL,
                    soc_percent REAL,
                    soh_percent REAL,
                    remaining_capacity_ah REAL,
                    full_capacity_ah REAL,
                    rated_capacity_ah REAL,
                    cycle_count INTEGER,
                    cell_voltage_delta_v REAL,
                    high_cell_voltage_v REAL,
                    low_cell_voltage_v REAL,
                    average_cell_voltage_v REAL,
                    mosfet_temperature_c REAL,
                    ambient_temperature_c REAL,
                    alarm_count INTEGER NOT NULL DEFAULT 0,
                    fault_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    raw_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS monitor_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_energy (
                    energy_date TEXT NOT NULL,
                    inverter_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    captured_at_unix INTEGER NOT NULL,
                    consumption_kwh REAL,
                    solar_generation_kwh REAL,
                    grid_import_kwh REAL,
                    PRIMARY KEY (energy_date, inverter_id)
                );
                CREATE TABLE IF NOT EXISTS inverter_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    captured_at_unix INTEGER NOT NULL,
                    collector_stream_id TEXT,
                    collector_sequence INTEGER,
                    inverter_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    grid_power_w REAL,
                    battery_power_w REAL,
                    solar_power_w REAL,
                    load_power_w REAL,
                    home_load_power_w REAL,
                    consumption_meter_kwh REAL,
                    solar_generation_meter_kwh REAL,
                    grid_import_meter_kwh REAL
                );
                CREATE INDEX IF NOT EXISTS idx_readings_time
                    ON readings (captured_at_unix);
                CREATE INDEX IF NOT EXISTS idx_readings_battery_time
                    ON readings (battery_id, captured_at_unix);
                CREATE INDEX IF NOT EXISTS idx_readings_events
                    ON readings (captured_at_unix, alarm_count, fault_count, status);
                CREATE INDEX IF NOT EXISTS idx_daily_energy_date
                    ON daily_energy (energy_date);
                CREATE TABLE IF NOT EXISTS tou_energy (
                    energy_date TEXT NOT NULL,
                    day_start_unix INTEGER NOT NULL,
                    tou_period TEXT NOT NULL,
                    consumption_kwh REAL NOT NULL DEFAULT 0,
                    solar_generation_kwh REAL NOT NULL DEFAULT 0,
                    grid_import_kwh REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (energy_date, tou_period)
                );
                CREATE INDEX IF NOT EXISTS idx_tou_energy_day
                    ON tou_energy (day_start_unix);
                CREATE INDEX IF NOT EXISTS idx_inverter_readings_time
                    ON inverter_readings (captured_at_unix);
                CREATE INDEX IF NOT EXISTS idx_inverter_readings_inverter_time
                    ON inverter_readings (inverter_id, captured_at_unix);
                """
            )
            self._ensure_column("collector_stream_id", "TEXT")
            self._ensure_column("collector_sequence", "INTEGER")
            self._ensure_column("home_load_power_w", "REAL", "inverter_readings")
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_collector_sample
                ON readings (battery_id, collector_stream_id, collector_sequence)
                WHERE collector_sequence IS NOT NULL
                  AND collector_stream_id IS NOT NULL
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_inverter_collector_sample
                ON inverter_readings (
                    inverter_id,
                    collector_stream_id,
                    collector_sequence
                )
                WHERE collector_sequence IS NOT NULL
                  AND collector_stream_id IS NOT NULL
                """
            )
            self._migrate_tou_rollup_locked()
            connection.execute("PRAGMA optimize")
            connection.commit()

    # Bumped whenever the rollup's arithmetic changes. Rows carry no version of
    # their own, so on mismatch every rollup is dropped and the bounded backfill
    # rebuilds the archive from the raw readings, newest days first.
    #   1  unseeded: a day's first reading credited with its whole counter
    #   2  seeded from the last reading before the day (see _recompute_tou_day_locked)
    TOU_ROLLUP_VERSION = 2

    def _migrate_tou_rollup_locked(self) -> None:
        row = self.connection.execute(
            "SELECT value FROM monitor_metadata WHERE key = 'tou_rollup_version'"
        ).fetchone()
        stored = str(row["value"]) if row is not None else None
        if stored == str(self.TOU_ROLLUP_VERSION):
            return
        dropped = self.connection.execute("DELETE FROM tou_energy").rowcount
        self.connection.execute(
            """
            INSERT INTO monitor_metadata (key, value) VALUES ('tou_rollup_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(self.TOU_ROLLUP_VERSION),),
        )
        if dropped:
            logger.info(
                "dropped %s time-of-use rollup row(s) written by rollup version %s; "
                "rebuilding from readings",
                dropped,
                stored or "unknown",
            )

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.database_path,
                check_same_thread=False,
                timeout=30,
            )
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def insert_snapshot(self, snapshot: dict[str, Any]) -> int:
        with self._lock:
            inserted = self._insert_snapshot_locked(snapshot)
            self._insert_inverter_reading_locked(snapshot)
            self._upsert_daily_energy_locked(snapshot)
            self._recompute_tou_days_locked(self._tou_days_for(snapshot))
            self.connection.commit()
            return inserted

    def insert_snapshots(self, snapshots: list[dict[str, Any]]) -> int:
        with self._lock:
            inserted = 0
            touched: set[date_type] = set()
            for snapshot in snapshots:
                if not isinstance(snapshot, dict):
                    continue
                inserted += self._insert_snapshot_locked(snapshot)
                self._insert_inverter_reading_locked(snapshot)
                self._upsert_daily_energy_locked(snapshot)
                touched.update(self._tou_days_for(snapshot))
            # One rollup pass per affected day, not per snapshot: a backfill page
            # covering an hour of history would otherwise rebuild the same day
            # sixty times over.
            self._recompute_tou_days_locked(touched)
            self.connection.commit()
            return inserted

    def prune_older_than_days(self, days: int) -> int:
        cutoff = int(time.time()) - days * 24 * 60 * 60
        cutoff_date = datetime.fromtimestamp(cutoff, timezone.utc).date().isoformat()
        with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM readings WHERE captured_at_unix < ?", (cutoff,)
            )
            energy_cursor = self.connection.execute(
                "DELETE FROM daily_energy WHERE energy_date < ?", (cutoff_date,)
            )
            tou_cursor = self.connection.execute(
                "DELETE FROM tou_energy WHERE day_start_unix < ?", (cutoff,)
            )
            inverter_cursor = self.connection.execute(
                "DELETE FROM inverter_readings WHERE captured_at_unix < ?", (cutoff,)
            )
            self.connection.commit()
            return (
                int(cursor.rowcount or 0)
                + int(energy_cursor.rowcount or 0)
                + int(tou_cursor.rowcount or 0)
                + int(inverter_cursor.rowcount or 0)
            )

    def integrity_check(self) -> dict[str, Any]:
        with self._lock:
            quick_row = self.connection.execute("PRAGMA quick_check").fetchone()
            integrity_row = self.connection.execute("PRAGMA integrity_check(1)").fetchone()
        quick = str(quick_row[0]) if quick_row else "unknown"
        integrity = str(integrity_row[0]) if integrity_row else "unknown"
        return {
            "quick_check": quick,
            "integrity_check": integrity,
            "ok": quick == "ok" and integrity == "ok",
        }

    def purge_all(self) -> dict[str, int]:
        """Delete every stored reading. Metadata (sequence markers, admin
        settings) is intentionally preserved so live writes keep flowing."""
        with self._lock:
            readings = self.connection.execute("DELETE FROM readings")
            inverter = self.connection.execute("DELETE FROM inverter_readings")
            energy = self.connection.execute("DELETE FROM daily_energy")
            tou = self.connection.execute("DELETE FROM tou_energy")
            self.connection.commit()
            try:
                self.connection.execute("VACUUM")
                self.connection.commit()
            except sqlite3.Error:
                pass  # reclaiming disk is best-effort; the delete already committed
            return {
                "readings": int(readings.rowcount or 0),
                "inverter_readings": int(inverter.rowcount or 0),
                "daily_energy": int(energy.rowcount or 0),
                "tou_energy": int(tou.rowcount or 0),
            }

    def backup_bytes(self) -> bytes:
        """Return a consistent copy of the database (WAL included) as bytes."""
        import os
        import tempfile

        with self._lock:
            handle, temp_path = tempfile.mkstemp(suffix=".sqlite3")
            os.close(handle)
            try:
                target = sqlite3.connect(temp_path)
                try:
                    self.connection.backup(target)
                finally:
                    target.close()
                with open(temp_path, "rb") as backup_file:
                    return backup_file.read()
            finally:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def latest_states(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT raw_json
                FROM readings
                WHERE id IN (SELECT MAX(id) FROM readings GROUP BY battery_id)
                ORDER BY battery_id
                """
            ).fetchall()
        states = []
        for row in rows:
            payload = _load_json(row["raw_json"])
            if payload:
                states.append(payload)
        return states

    def history(
        self,
        battery_id: str,
        metric: HistoryMetric,
        seconds: int,
        bucket_seconds: int,
    ) -> list[dict[str, Any]]:
        column = HISTORY_COLUMNS[str(metric)]
        since = int(time.time()) - seconds
        params: list[object] = [bucket_seconds, bucket_seconds, since]
        battery_filter = ""
        if battery_id != "all":
            battery_filter = "AND battery_id = ?"
            params.append(battery_id)

        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT
                    CAST(captured_at_unix / ? AS INTEGER) * ? AS bucket_unix,
                    battery_id,
                    AVG({column}) AS value
                FROM readings
                WHERE captured_at_unix >= ?
                  AND {column} IS NOT NULL
                  {battery_filter}
                GROUP BY bucket_unix, battery_id
                ORDER BY bucket_unix ASC, battery_id ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "timestamp": _iso_from_unix(int(row["bucket_unix"])),
                "unix": int(row["bucket_unix"]),
                "battery_id": row["battery_id"],
                "value": round(float(row["value"]), 4),
            }
            for row in rows
            if row["value"] is not None
        ]

    def energy_history(
        self,
        view: EnergyView,
        energy_date: str | None = None,
        energy_timezone: str = "UTC",
    ) -> dict[str, Any]:
        if view == "hour":
            return self._energy_interval_history()
        if view == "date":
            selected_date = energy_date or datetime.now(
                ZoneInfo(energy_timezone)
            ).date().isoformat()
            return self._energy_interval_history(selected_date, energy_timezone)

        # "month" breaks the current calendar month into its days; "year" breaks
        # the current calendar year into its months. Both bucket by the *viewer's*
        # local day (not the UTC date the daily_energy table is keyed by), so an
        # evening reading whose UTC clock has already rolled past midnight is not
        # filed under tomorrow. Each local day's energy is the sum of its counter's
        # increments across the day: a reading adds the rise since the previous one,
        # or its own value when the counter has dropped (a reset). The energy_today
        # counters reset at local midnight, but this also stays correct if a counter
        # resets again mid-day (e.g. an inverter restart). The day partition makes
        # the first reading of each day contribute its own value, and the local date
        # is derived with the viewer's current UTC offset.
        zone = ZoneInfo(energy_timezone)
        now_local = datetime.now(zone)
        offset_seconds = int((now_local.utcoffset() or timedelta()).total_seconds())
        if view == "month":
            period_expression = "local_date"  # one bucket per local day
            selected_period = now_local.strftime("%Y-%m")
            start_local = now_local.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            end_local = (start_local + timedelta(days=32)).replace(day=1)
        else:  # year
            period_expression = "substr(local_date, 1, 7)"  # one bucket per month
            selected_period = now_local.strftime("%Y")
            start_local = now_local.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            end_local = start_local.replace(year=start_local.year + 1)
        consumption_delta = _counter_delta_expression(
            "consumption_meter_kwh", "previous_consumption_kwh"
        )
        solar_delta = _counter_delta_expression(
            "solar_generation_meter_kwh", "previous_solar_kwh"
        )
        grid_delta = _counter_delta_expression(
            "grid_import_meter_kwh", "previous_grid_kwh"
        )
        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT
                    {period_expression} AS period,
                    SUM({consumption_delta}) AS consumption_kwh,
                    SUM({solar_delta}) AS solar_generation_kwh,
                    SUM({grid_delta}) AS grid_import_kwh
                FROM (
                    SELECT
                        date(captured_at_unix + ?, 'unixepoch') AS local_date,
                        consumption_meter_kwh,
                        solar_generation_meter_kwh,
                        grid_import_meter_kwh,
                        LAG(consumption_meter_kwh) OVER day_window
                            AS previous_consumption_kwh,
                        LAG(solar_generation_meter_kwh) OVER day_window
                            AS previous_solar_kwh,
                        LAG(grid_import_meter_kwh) OVER day_window
                            AS previous_grid_kwh
                    FROM inverter_readings
                    WHERE captured_at_unix >= ? AND captured_at_unix < ?
                    WINDOW day_window AS (
                        PARTITION BY
                            inverter_id, date(captured_at_unix + ?, 'unixepoch')
                        ORDER BY captured_at_unix
                    )
                )
                GROUP BY period
                HAVING consumption_kwh IS NOT NULL
                    OR solar_generation_kwh IS NOT NULL
                    OR grid_import_kwh IS NOT NULL
                ORDER BY period ASC
                """,
                (
                    offset_seconds,
                    int(start_local.timestamp()),
                    int(end_local.timestamp()),
                    offset_seconds,
                ),
            ).fetchall()

        points = []
        for row in rows:
            timestamp, unix = _energy_period_time(str(row["period"]), view)
            points.append(
                {
                    "period": row["period"],
                    "timestamp": timestamp,
                    "unix": unix,
                    "consumption_kwh": _rounded_number(row["consumption_kwh"]),
                    "solar_generation_kwh": _rounded_number(
                        row["solar_generation_kwh"]
                    ),
                    "grid_import_kwh": _rounded_number(row["grid_import_kwh"]),
                }
            )

        return {
            "view": view,
            "selected_period": selected_period,
            "points": points,
            "totals": _sum_energy_rows(rows),
        }

    def power_history(
        self,
        seconds: int,
        bucket_seconds: int,
        window_start_unix: int | None = None,
        window_end_unix: int | None = None,
    ) -> list[dict[str, Any]]:
        if window_start_unix is not None and window_end_unix is not None:
            time_filter = "captured_at_unix >= ? AND captured_at_unix < ?"
            time_params: tuple[object, ...] = (
                window_start_unix,
                window_end_unix,
            )
        else:
            time_filter = "captured_at_unix >= ?"
            time_params = (int(time.time()) - seconds,)
        with self._lock:
            rows = self.connection.execute(
                f"""
                WITH inverter_by_device AS (
                    SELECT
                        CAST(captured_at_unix / ? AS INTEGER) * ? AS bucket_unix,
                        inverter_id,
                        AVG(grid_power_w) AS grid_power_w,
                        AVG(solar_power_w) AS solar_power_w,
                        AVG(load_power_w) AS load_power_w,
                        AVG(home_load_power_w) AS home_load_power_w
                    FROM inverter_readings
                    WHERE {time_filter}
                      AND (
                          grid_power_w IS NOT NULL
                          OR solar_power_w IS NOT NULL
                          OR load_power_w IS NOT NULL
                          OR home_load_power_w IS NOT NULL
                      )
                    GROUP BY bucket_unix, inverter_id
                ),
                inverter_by_bucket AS (
                    SELECT
                        bucket_unix,
                        SUM(grid_power_w) AS grid_power_w,
                        SUM(solar_power_w) AS solar_power_w,
                        SUM(load_power_w) AS load_power_w,
                        SUM(home_load_power_w) AS home_load_power_w
                    FROM inverter_by_device
                    GROUP BY bucket_unix
                ),
                battery_by_pack AS (
                    SELECT
                        CAST(captured_at_unix / ? AS INTEGER) * ? AS bucket_unix,
                        battery_id,
                        AVG(power_w) AS battery_power_w,
                        AVG(CASE WHEN soc_percent BETWEEN 0 AND 100
                            THEN soc_percent END) AS battery_soc_percent
                    FROM readings
                    WHERE {time_filter}
                      AND status = 'ok'
                      AND (power_w IS NOT NULL OR soc_percent BETWEEN 0 AND 100)
                    GROUP BY bucket_unix, battery_id
                ),
                battery_by_bucket AS (
                    SELECT
                        bucket_unix,
                        SUM(battery_power_w) AS battery_power_w,
                        AVG(battery_soc_percent) AS battery_soc_percent
                    FROM battery_by_pack
                    GROUP BY bucket_unix
                ),
                buckets AS (
                    SELECT bucket_unix FROM inverter_by_bucket
                    UNION
                    SELECT bucket_unix FROM battery_by_bucket
                )
                SELECT
                    buckets.bucket_unix,
                    inverter_by_bucket.grid_power_w,
                    battery_by_bucket.battery_power_w,
                    battery_by_bucket.battery_soc_percent,
                    inverter_by_bucket.solar_power_w,
                    inverter_by_bucket.load_power_w,
                    inverter_by_bucket.home_load_power_w
                FROM buckets
                LEFT JOIN inverter_by_bucket USING (bucket_unix)
                LEFT JOIN battery_by_bucket USING (bucket_unix)
                ORDER BY buckets.bucket_unix ASC
                """,
                (
                    bucket_seconds,
                    bucket_seconds,
                    *time_params,
                    bucket_seconds,
                    bucket_seconds,
                    *time_params,
                ),
            ).fetchall()

        return [
            {
                "timestamp": _iso_from_unix(int(row["bucket_unix"])),
                "unix": int(row["bucket_unix"]),
                "grid_power_w": _rounded_power(row["grid_power_w"]),
                "battery_power_w": _rounded_power(row["battery_power_w"]),
                "battery_soc_percent": _rounded_number(row["battery_soc_percent"]),
                "solar_power_w": _rounded_power(row["solar_power_w"]),
                "load_power_w": _rounded_power(row["load_power_w"]),
                "home_load_power_w": _rounded_power(row["home_load_power_w"]),
            }
            for row in rows
        ]

    def savings_energy(
        self,
        energy_timezone: str,
        retention_days: int = 1095,
        selected_date: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        zone = ZoneInfo(energy_timezone)
        now = datetime.now(zone)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        selected_day = selected_date or today_start.date().isoformat()
        selected_day_start = datetime.strptime(selected_day, "%Y-%m-%d").replace(
            tzinfo=zone
        )
        month_start = today_start.replace(day=1)
        year_start = month_start.replace(month=1)
        retained_start = now - timedelta(days=retention_days)
        with self._lock:
            retained_totals = self._energy_totals_locked()
        periods = {
            "date": (
                self.energy_history("date", selected_day, energy_timezone),
                selected_day_start,
                selected_day_start + timedelta(days=1),
            ),
            "today": (
                self.energy_history("date", today_start.date().isoformat(), energy_timezone),
                today_start,
                today_start + timedelta(days=1),
            ),
            "month": (
                self.energy_history("month", None, energy_timezone),
                month_start,
                (month_start + timedelta(days=32)).replace(day=1),
            ),
            "year": (
                self.energy_history("year", None, energy_timezone),
                year_start,
                year_start.replace(year=year_start.year + 1),
            ),
            "retained": (
                {"totals": retained_totals},
                retained_start,
                now + timedelta(seconds=1),
            ),
        }
        return {
            key: {
                **payload.get("totals", {}),
                "observed_days": self._observed_solar_days(start, end, zone),
                # Each reporting window also carries its time-of-use split, so
                # the savings engine can price the window by the clock rather
                # than by one blended rate.
                "tou": self.tou_energy_totals(
                    int(start.timestamp()), int(end.timestamp())
                ),
            }
            for key, (payload, start, end) in periods.items()
        }

    def _observed_solar_days(
        self, start: datetime, end: datetime, zone: ZoneInfo
    ) -> int:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT MIN(captured_at_unix) AS oldest, MAX(captured_at_unix) AS newest
                FROM inverter_readings
                WHERE captured_at_unix >= ? AND captured_at_unix < ?
                  AND solar_generation_meter_kwh IS NOT NULL
                """,
                (int(start.timestamp()), int(end.timestamp())),
            ).fetchone()
        if row["oldest"] is None or row["newest"] is None:
            return 0
        oldest = datetime.fromtimestamp(int(row["oldest"]), zone).date()
        newest = datetime.fromtimestamp(int(row["newest"]), zone).date()
        return (newest - oldest).days + 1

    def _energy_interval_history(
        self, energy_date: str | None = None, energy_timezone: str = "UTC"
    ) -> dict[str, Any]:
        seed_sql = ""
        emit_filter = ""
        if energy_date is None:
            # The Hour tab is a rolling 60-minute view. Five-minute counter
            # deltas preserve useful detail without mistaking instantaneous
            # power for energy.
            bucket_seconds = 5 * 60
            window_end_unix = int(time.time())
            window_start_unix = window_end_unix - 60 * 60
            time_filter = "captured_at_unix >= ? AND captured_at_unix < ?"
            params: tuple[object, ...] = (window_start_unix, window_end_unix)
            window_partition = "inverter_id"
            bucket_expression = f"""
                CAST((captured_at_unix - {window_start_unix}) / {bucket_seconds}
                    AS INTEGER) * {bucket_seconds} + {window_start_unix}
            """
            seed_sql = f"""
                UNION ALL
                SELECT
                    {window_start_unix - bucket_seconds} AS bucket_unix,
                    inverter_id,
                    MAX(captured_at_unix) AS last_captured_unix,
                    consumption_meter_kwh AS consumption_meter_kwh,
                    solar_generation_meter_kwh AS solar_generation_meter_kwh,
                    grid_import_meter_kwh AS grid_import_meter_kwh
                FROM inverter_readings
                WHERE captured_at_unix >= {window_start_unix - 6 * 3600}
                    AND captured_at_unix < {window_start_unix}
                GROUP BY inverter_id
            """
            emit_filter = f"WHERE bucket_unix >= {window_start_unix}"
            # Without a preceding reading, the existing daily counter cannot
            # reveal how much belongs to the first interval.
            first_bucket_condition = "1 = 0"
        else:
            bucket_seconds = 60 * 60
            selected_zone = ZoneInfo(energy_timezone)
            selected_day = datetime.strptime(energy_date, "%Y-%m-%d").replace(
                tzinfo=selected_zone
            )
            window_start_unix = int(selected_day.timestamp())
            window_end_unix = int((selected_day + timedelta(days=1)).timestamp())
            time_filter = "captured_at_unix >= ? AND captured_at_unix < ?"
            params = (window_start_unix, window_end_unix)
            window_partition = "inverter_id"
            bucket_expression = f"""
                CAST((captured_at_unix - {window_start_unix}) / {bucket_seconds}
                    AS INTEGER) * {bucket_seconds} + {window_start_unix}
            """
            # The window starts at this timezone's local midnight, but the inverter
            # resets its "today" counters at *its own* clock's midnight, which may be
            # set to a different zone. Seed the first hour with the reading captured
            # just before the window (placed one hour ahead of it so it becomes the
            # 00:00 bucket's LAG predecessor): the delta logic then measures only the
            # energy inside the first hour whether or not the reset lines up with the
            # window edge. The seed row is filtered back out of the emitted buckets.
            # When there is no earlier reading the seed is empty and the first hour
            # falls back to reporting its counter directly.
            first_bucket_condition = f"""
                previous_bucket_unix IS NULL
                AND bucket_unix - {window_start_unix} < {bucket_seconds}
            """
            seed_sql = f"""
                UNION ALL
                SELECT
                    {window_start_unix - bucket_seconds} AS bucket_unix,
                    inverter_id,
                    MAX(captured_at_unix) AS last_captured_unix,
                    consumption_meter_kwh AS consumption_meter_kwh,
                    solar_generation_meter_kwh AS solar_generation_meter_kwh,
                    grid_import_meter_kwh AS grid_import_meter_kwh
                FROM inverter_readings
                WHERE captured_at_unix >= {window_start_unix - 6 * 3600}
                    AND captured_at_unix < {window_start_unix}
                GROUP BY inverter_id
            """
            emit_filter = f"WHERE bucket_unix >= {window_start_unix}"

        consumption_expression = _interval_energy_expression(
            "consumption_meter_kwh",
            "previous_consumption_kwh",
            first_bucket_condition,
            bucket_seconds,
        )
        solar_expression = _interval_energy_expression(
            "solar_generation_meter_kwh",
            "previous_solar_kwh",
            first_bucket_condition,
            bucket_seconds,
        )
        grid_expression = _interval_energy_expression(
            "grid_import_meter_kwh",
            "previous_grid_kwh",
            first_bucket_condition,
            bucket_seconds,
        )

        with self._lock:
            rows = self.connection.execute(
                f"""
                WITH intervals AS (
                    SELECT
                        {bucket_expression} AS bucket_unix,
                        inverter_id,
                        -- Take each hour's counters from its *latest* reading, not
                        -- the hour's MAX. The daily counters reset at the inverter's
                        -- local midnight, so a reading captured just before the reset
                        -- still holds yesterday's whole-day total; MAX would let that
                        -- stale peak win the 00:00 bucket and report it as today's
                        -- first hour. The counter only climbs within a day, so the
                        -- last reading equals the MAX except across the reset, which
                        -- is exactly the case we need to shed. SQLite fills the bare
                        -- columns from the row holding MAX(captured_at_unix).
                        MAX(captured_at_unix) AS last_captured_unix,
                        consumption_meter_kwh AS consumption_meter_kwh,
                        solar_generation_meter_kwh
                            AS solar_generation_meter_kwh,
                        grid_import_meter_kwh AS grid_import_meter_kwh
                    FROM inverter_readings
                    WHERE {time_filter}
                    GROUP BY bucket_unix, inverter_id
                    {seed_sql}
                ),
                deltas AS (
                    SELECT
                        *,
                        LAG(bucket_unix) OVER day_window AS previous_bucket_unix,
                        LAG(consumption_meter_kwh) OVER day_window
                            AS previous_consumption_kwh,
                        LAG(solar_generation_meter_kwh) OVER day_window
                            AS previous_solar_kwh,
                        LAG(grid_import_meter_kwh) OVER day_window
                            AS previous_grid_kwh
                    FROM intervals
                    WINDOW day_window AS (
                        PARTITION BY {window_partition}
                        ORDER BY bucket_unix
                    )
                )
                SELECT
                    bucket_unix,
                    SUM({consumption_expression}) AS consumption_kwh,
                    SUM({solar_expression}) AS solar_generation_kwh,
                    SUM({grid_expression}) AS grid_import_kwh
                FROM deltas
                {emit_filter}
                GROUP BY bucket_unix
                HAVING consumption_kwh IS NOT NULL
                    OR solar_generation_kwh IS NOT NULL
                    OR grid_import_kwh IS NOT NULL
                ORDER BY bucket_unix ASC
                """,
                params,
            ).fetchall()
            # Totals always describe the visible window. Long-term savings use
            # the retained daily-energy aggregate separately.
            totals = _sum_energy_rows(rows)

        return {
            "view": "date" if energy_date is not None else "hour",
            "retention_years": 3,
            "bucket_seconds": bucket_seconds,
            "window_seconds": window_end_unix - window_start_unix,
            "selected_date": energy_date,
            "timezone": energy_timezone if energy_date is not None else "UTC",
            "window_start": _iso_from_unix(window_start_unix),
            "window_start_unix": window_start_unix,
            "window_end": _iso_from_unix(window_end_unix),
            "window_end_unix": window_end_unix,
            "points": [
                {
                    "period": _iso_from_unix(int(row["bucket_unix"]))[
                        : 13 if energy_date is not None else 16
                    ],
                    "timestamp": _iso_from_unix(int(row["bucket_unix"])),
                    "unix": int(row["bucket_unix"]),
                    "consumption_kwh": _rounded_number(row["consumption_kwh"]),
                    "solar_generation_kwh": _rounded_number(
                        row["solar_generation_kwh"]
                    ),
                    "grid_import_kwh": _rounded_number(row["grid_import_kwh"]),
                }
                for row in rows
            ],
            "totals": totals,
        }

    # ----- Time-of-use rollup -------------------------------------------
    # Schedule 327 prices a kilowatt-hour by the clock, so the savings engine
    # needs each day split across on-peak, off-peak and super off-peak. Deriving
    # that from raw readings costs seconds over a three-year window, far too slow
    # for a polled endpoint, so each tariff-local day is rolled up once into
    # tou_energy and every later query is a plain SUM over at most ~1095 days.

    def tou_energy_totals(
        self, start_unix: int, end_unix: int
    ) -> dict[str, dict[str, float]]:
        """Time-of-use split of the days starting inside a unix range."""
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT tou_period,
                       SUM(consumption_kwh) AS consumption_kwh,
                       SUM(solar_generation_kwh) AS solar_generation_kwh,
                       SUM(grid_import_kwh) AS grid_import_kwh
                FROM tou_energy
                WHERE day_start_unix >= ? AND day_start_unix < ?
                GROUP BY tou_period
                """,
                (int(start_unix), int(end_unix)),
            ).fetchall()
        totals = {
            period: {
                "consumption_kwh": 0.0,
                "solar_generation_kwh": 0.0,
                "grid_import_kwh": 0.0,
            }
            for period in TOU_PERIODS
        }
        for row in rows:
            period = str(row["tou_period"])
            if period not in totals:
                continue
            totals[period] = {
                "consumption_kwh": float(row["consumption_kwh"] or 0.0),
                "solar_generation_kwh": float(row["solar_generation_kwh"] or 0.0),
                "grid_import_kwh": float(row["grid_import_kwh"] or 0.0),
            }
        return totals

    def backfill_tou_energy(self, budget_seconds: float = 5.0) -> int:
        """Roll up days that have readings but no time-of-use split yet.

        History logged before the rate change has no rollup, so it is rebuilt
        here rather than at read time. The pass is bounded by a wall-clock
        budget and picks up where it left off, so a three-year archive fills in
        without blocking startup or a poll cycle.
        """
        deadline = time.monotonic() + max(0.0, budget_seconds)
        rebuilt = 0
        while time.monotonic() < deadline:
            with self._lock:
                day = self._next_unrolled_day_locked()
                if day is None:
                    return rebuilt
                self._recompute_tou_days_locked({day})
                self.connection.commit()
            rebuilt += 1
        return rebuilt

    def _next_unrolled_day_locked(self) -> date_type | None:
        """The oldest reading day with no rollup row, newest history first.

        Recent days matter most on the dashboard, so the scan walks backwards
        from the newest reading and returns the first day that is still missing.
        """
        rows = self.connection.execute(
            """
            SELECT DISTINCT captured_at_unix
            FROM inverter_readings
            ORDER BY captured_at_unix DESC
            """
        )
        seen: set[date_type] = set()
        for row in rows:
            day = self._tariff_day(int(row["captured_at_unix"]))
            if day in seen:
                continue
            seen.add(day)
            covered = self.connection.execute(
                "SELECT 1 FROM tou_energy WHERE energy_date = ? LIMIT 1",
                (day.isoformat(),),
            ).fetchone()
            if covered is None:
                return day
        return None

    def _tou_days_for(self, snapshot: dict[str, Any]) -> set[date_type]:
        row = _daily_energy_row(snapshot)
        if row is None:
            return set()
        return {self._tariff_day(int(row["captured_at_unix"]))}

    def _tariff_day(self, unix: int) -> date_type:
        return datetime.fromtimestamp(unix, self._tariff_zone).date()

    def _day_bounds(self, day: date_type) -> tuple[int, int]:
        """Unix span of one tariff-local day, 23 or 25 hours long across DST."""
        start = datetime.combine(day, time_type.min, tzinfo=self._tariff_zone)
        end = datetime.combine(
            day + timedelta(days=1), time_type.min, tzinfo=self._tariff_zone
        )
        return int(start.timestamp()), int(end.timestamp())

    def _recompute_tou_days_locked(self, days: set[date_type]) -> None:
        for day in sorted(days):
            self._recompute_tou_day_locked(day)

    def _recompute_tou_day_locked(self, day: date_type) -> None:
        """Rebuild one day's time-of-use split from its raw readings.

        Rebuilding the whole day is deliberate: it costs about a thousand rows
        and keeps the rollup self-healing, where an incremental counter would
        drift the first time a reading arrived late or out of order. Each
        reading's rise is credited to the period its own timestamp falls in,
        and the timestamp is converted with a real timezone so an hour on a
        daylight-saving boundary is priced the way the meter saw it.

        The day's first reading is measured against the last reading before
        the day began, not against nothing. The inverter's "today" counters
        reset at *its* clock's midnight, which need not be the tariff's: a
        clock a couple of minutes slow, or set to UTC, leaves yesterday's whole
        total in the counter at 00:00 local. Without the seed that total is
        credited to the first reading -- and midnight is super off-peak, so the
        overnight period swallows a day's energy every day. The lookback is
        bounded to six hours, as the hourly view's is: a reading from days ago
        is on the far side of at least one reset and would only undercount.
        """
        day_start, day_end = self._day_bounds(day)
        previous = self._counters_before_locked(day_start)
        rows = self.connection.execute(
            """
            SELECT inverter_id, captured_at_unix, consumption_meter_kwh,
                   solar_generation_meter_kwh, grid_import_meter_kwh
            FROM inverter_readings
            WHERE captured_at_unix >= ? AND captured_at_unix < ?
            ORDER BY inverter_id, captured_at_unix
            """,
            (day_start, day_end),
        ).fetchall()

        buckets = {
            period: {
                "consumption_kwh": 0.0,
                "solar_generation_kwh": 0.0,
                "grid_import_kwh": 0.0,
            }
            for period in TOU_PERIODS
        }
        columns = (
            ("consumption_kwh", "consumption_meter_kwh"),
            ("solar_generation_kwh", "solar_generation_meter_kwh"),
            ("grid_import_kwh", "grid_import_meter_kwh"),
        )
        for row in rows:
            inverter = str(row["inverter_id"])
            last = previous.setdefault(inverter, {})
            moment = datetime.fromtimestamp(
                int(row["captured_at_unix"]), self._tariff_zone
            )
            bucket = buckets[period_for(moment)]
            for field, meter in columns:
                value = row[meter]
                if value is None:
                    continue
                meter_value = float(value)
                bucket[field] += _counter_rise(last.get(field), meter_value)
                last[field] = meter_value

        self.connection.execute(
            "DELETE FROM tou_energy WHERE energy_date = ?", (day.isoformat(),)
        )
        if not rows:
            return
        self.connection.executemany(
            """
            INSERT INTO tou_energy (
                energy_date, day_start_unix, tou_period,
                consumption_kwh, solar_generation_kwh, grid_import_kwh
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    day.isoformat(),
                    day_start,
                    period,
                    round(values["consumption_kwh"], 6),
                    round(values["solar_generation_kwh"], 6),
                    round(values["grid_import_kwh"], 6),
                )
                for period, values in buckets.items()
            ],
        )

    # How far back the day's seed reading may come from. Matches the hourly
    # view's seed window: long enough to bridge a collector restart around
    # midnight, short enough that the reading is on this side of the last reset.
    TOU_SEED_LOOKBACK_SECONDS = 6 * 3600

    def _counters_before_locked(
        self, day_start: int
    ) -> dict[str, dict[str, float | None]]:
        """Each inverter's last counters before a day began, if recent enough."""
        rows = self.connection.execute(
            """
            SELECT inverter_id,
                   MAX(captured_at_unix) AS captured_at_unix,
                   consumption_meter_kwh,
                   solar_generation_meter_kwh,
                   grid_import_meter_kwh
            FROM inverter_readings
            WHERE captured_at_unix >= ? AND captured_at_unix < ?
            GROUP BY inverter_id
            """,
            (day_start - self.TOU_SEED_LOOKBACK_SECONDS, day_start),
        ).fetchall()
        seeds: dict[str, dict[str, float | None]] = {}
        for row in rows:
            seeds[str(row["inverter_id"])] = {
                field: (None if row[meter] is None else float(row[meter]))
                for field, meter in (
                    ("consumption_kwh", "consumption_meter_kwh"),
                    ("solar_generation_kwh", "solar_generation_meter_kwh"),
                    ("grid_import_kwh", "grid_import_meter_kwh"),
                )
            }
        return seeds

    def _energy_totals_locked(self) -> dict[str, float | None]:
        row = self.connection.execute(
            """
            SELECT
                SUM(consumption_kwh) AS consumption_kwh,
                SUM(solar_generation_kwh) AS solar_generation_kwh,
                SUM(grid_import_kwh) AS grid_import_kwh
            FROM daily_energy
            WHERE energy_date >= date('now', '-3 years')
            """
        ).fetchone()
        return {
            "consumption_kwh": _rounded_number(row["consumption_kwh"]),
            "solar_generation_kwh": _rounded_number(
                row["solar_generation_kwh"]
            ),
            "grid_import_kwh": _rounded_number(row["grid_import_kwh"]),
        }

    def events(self, seconds: int, limit: int) -> list[dict[str, Any]]:
        since = int(time.time()) - seconds
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT captured_at, battery_id, address, status, alarm_count,
                       fault_count, last_error, raw_json
                FROM readings
                WHERE captured_at_unix >= ?
                  AND (alarm_count > 0 OR fault_count > 0 OR status != 'ok')
                ORDER BY captured_at_unix DESC, id DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        events = []
        for row in rows:
            raw = _load_json(row["raw_json"])
            reading = raw.get("last_reading") if isinstance(raw, dict) else {}
            if not isinstance(reading, dict):
                reading = {}
            events.append(
                {
                    "captured_at": row["captured_at"],
                    "battery_id": row["battery_id"],
                    "address": row["address"],
                    "status": row["status"],
                    "alarm_count": row["alarm_count"],
                    "fault_count": row["fault_count"],
                    "alarms": reading.get("alarms") or [],
                    "faults": reading.get("faults") or [],
                    "last_error": row["last_error"],
                }
            )
        return events

    def export_rows(self, battery_id: str, days: int) -> list[dict[str, Any]]:
        since = int(time.time()) - days * 24 * 60 * 60
        params: list[object] = [since]
        battery_filter = ""
        if battery_id != "all":
            battery_filter = "AND battery_id = ?"
            params.append(battery_id)
        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT {','.join(self.export_fieldnames)}
                FROM readings
                WHERE captured_at_unix >= ?
                  {battery_filter}
                ORDER BY captured_at_unix ASC, battery_id ASC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self, retention_days: int) -> dict[str, Any]:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS row_count,
                       MIN(captured_at) AS oldest_reading_at,
                       MAX(captured_at) AS newest_reading_at,
                       COUNT(DISTINCT battery_id) AS battery_count
                FROM readings
                """
            ).fetchone()
            energy_row = self.connection.execute(
                """
                SELECT COUNT(*) AS point_count,
                       MIN(energy_date) AS oldest_energy_date,
                       MAX(energy_date) AS newest_energy_date
                FROM daily_energy
                """
            ).fetchone()
            inverter_row = self.connection.execute(
                """
                SELECT COUNT(*) AS point_count,
                       MIN(captured_at) AS oldest_reading_at,
                       MAX(captured_at) AS newest_reading_at
                FROM inverter_readings
                """
            ).fetchone()
        return {
            "database_path": str(self.database_path),
            "database_size_bytes": self._database_size_bytes(),
            "row_count": int(row["row_count"] or 0),
            "battery_count": int(row["battery_count"] or 0),
            "oldest_reading_at": row["oldest_reading_at"],
            "newest_reading_at": row["newest_reading_at"],
            "energy_point_count": int(energy_row["point_count"] or 0),
            "oldest_energy_date": energy_row["oldest_energy_date"],
            "newest_energy_date": energy_row["newest_energy_date"],
            "inverter_point_count": int(inverter_row["point_count"] or 0),
            "oldest_inverter_reading_at": inverter_row["oldest_reading_at"],
            "newest_inverter_reading_at": inverter_row["newest_reading_at"],
            "retention_days": retention_days,
        }

    def health(self) -> dict[str, Any]:
        readable = False
        try:
            with self._lock:
                self.connection.execute("SELECT 1").fetchone()
                readable = True
                self._verify_writable()
            return {
                "status": "ok",
                "database_path": str(self.database_path),
                "readable": True,
                "writable": True,
            }
        except sqlite3.Error as exc:
            return {
                "status": "error",
                "database_path": str(self.database_path),
                "readable": readable,
                "writable": False,
                "error": str(exc),
            }

    def get_metadata(self, key: str) -> str | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT value FROM monitor_metadata WHERE key = ?", (key,)
            ).fetchone()
            return str(row["value"]) if row is not None else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO monitor_metadata (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            self.connection.commit()

    def _ensure_column(
        self, name: str, declaration: str,
        table: Literal["readings", "inverter_readings"] = "readings",
    ) -> None:
        columns = {
            str(row["name"])
            for row in self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if name not in columns:
            self.connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"
            )

    def _verify_writable(self) -> None:
        self.connection.execute("SAVEPOINT monitor_health_check")
        try:
            self.connection.execute(
                """
                INSERT INTO monitor_metadata (key, value)
                VALUES ('__health_check__', 'ok')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )
            self.connection.execute("ROLLBACK TO monitor_health_check")
        finally:
            self.connection.execute("RELEASE monitor_health_check")

    def _insert_snapshot_locked(self, snapshot: dict[str, Any]) -> int:
        service = snapshot.get("service")
        service = service if isinstance(service, dict) else {}
        stream_id = _optional_string(service.get("buffer_stream_id"))
        sequence = _int(service.get("sequence"))
        captured_at, captured_at_unix = _snapshot_time(snapshot)
        rows = []

        for battery in snapshot.get("batteries", []):
            if not isinstance(battery, dict):
                continue
            reading = battery.get("last_reading") or {}
            if not isinstance(reading, dict):
                reading = {}
            rows.append(
                {
                    "captured_at": captured_at,
                    "captured_at_unix": captured_at_unix,
                    "collector_stream_id": stream_id,
                    "collector_sequence": sequence,
                    "battery_id": str(battery.get("id", reading.get("id", "unknown"))),
                    "address": _int(battery.get("address", reading.get("address"))) or 0,
                    "status": str(battery.get("status", "unknown")),
                    "voltage_v": _number(reading.get("voltage_v")),
                    "current_a": _number(reading.get("current_a")),
                    "power_w": _number(reading.get("power_w")),
                    "soc_percent": _number(reading.get("soc_percent")),
                    "soh_percent": _number(reading.get("soh_percent")),
                    "remaining_capacity_ah": _number(reading.get("remaining_capacity_ah")),
                    "full_capacity_ah": _number(reading.get("full_capacity_ah")),
                    "rated_capacity_ah": _number(reading.get("rated_capacity_ah")),
                    "cycle_count": _int(reading.get("cycle_count")),
                    "cell_voltage_delta_v": _number(reading.get("cell_voltage_delta_v")),
                    "high_cell_voltage_v": _number(reading.get("high_cell_voltage_v")),
                    "low_cell_voltage_v": _number(reading.get("low_cell_voltage_v")),
                    "average_cell_voltage_v": _number(reading.get("average_cell_voltage_v")),
                    "mosfet_temperature_c": _number(reading.get("mosfet_temperature_c")),
                    "ambient_temperature_c": _number(reading.get("ambient_temperature_c")),
                    "alarm_count": len(reading.get("alarms") or []),
                    "fault_count": len(reading.get("faults") or []),
                    "last_error": battery.get("last_error"),
                    "raw_json": json.dumps(battery, separators=(",", ":"), sort_keys=True),
                }
            )

        if not rows:
            return 0

        columns = list(rows[0].keys())
        placeholders = ",".join(f":{column}" for column in columns)
        inserted = 0
        for row in rows:
            cursor = self.connection.execute(
                f"INSERT OR IGNORE INTO readings ({','.join(columns)}) VALUES ({placeholders})",
                row,
            )
            inserted += max(0, int(cursor.rowcount or 0))
        return inserted

    def _insert_inverter_reading_locked(self, snapshot: dict[str, Any]) -> int:
        row = _inverter_reading_row(snapshot)
        if row is None:
            return 0
        columns = list(row.keys())
        placeholders = ",".join(f":{column}" for column in columns)
        cursor = self.connection.execute(
            f"""
            INSERT OR IGNORE INTO inverter_readings ({','.join(columns)})
            VALUES ({placeholders})
            """,
            row,
        )
        return max(0, int(cursor.rowcount or 0))

    def _upsert_daily_energy_locked(self, snapshot: dict[str, Any]) -> None:
        row = _daily_energy_row(snapshot)
        if row is None:
            return
        self.connection.execute(
            """
            INSERT INTO daily_energy (
                energy_date,
                inverter_id,
                captured_at,
                captured_at_unix,
                consumption_kwh,
                solar_generation_kwh,
                grid_import_kwh
            ) VALUES (
                :energy_date,
                :inverter_id,
                :captured_at,
                :captured_at_unix,
                :consumption_kwh,
                :solar_generation_kwh,
                :grid_import_kwh
            )
            ON CONFLICT(energy_date, inverter_id) DO UPDATE SET
                captured_at = CASE
                    WHEN excluded.captured_at_unix >= daily_energy.captured_at_unix
                    THEN excluded.captured_at
                    ELSE daily_energy.captured_at
                END,
                captured_at_unix = MAX(
                    daily_energy.captured_at_unix,
                    excluded.captured_at_unix
                ),
                consumption_kwh = CASE
                    WHEN excluded.consumption_kwh IS NULL
                    THEN daily_energy.consumption_kwh
                    WHEN daily_energy.consumption_kwh IS NULL
                    THEN excluded.consumption_kwh
                    ELSE MAX(daily_energy.consumption_kwh, excluded.consumption_kwh)
                END,
                solar_generation_kwh = CASE
                    WHEN excluded.solar_generation_kwh IS NULL
                    THEN daily_energy.solar_generation_kwh
                    WHEN daily_energy.solar_generation_kwh IS NULL
                    THEN excluded.solar_generation_kwh
                    ELSE MAX(
                        daily_energy.solar_generation_kwh,
                        excluded.solar_generation_kwh
                    )
                END,
                grid_import_kwh = CASE
                    WHEN excluded.grid_import_kwh IS NULL
                    THEN daily_energy.grid_import_kwh
                    WHEN daily_energy.grid_import_kwh IS NULL
                    THEN excluded.grid_import_kwh
                    ELSE MAX(daily_energy.grid_import_kwh, excluded.grid_import_kwh)
                END
            """,
            row,
        )

    def _database_size_bytes(self) -> int:
        paths = [
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ]
        return sum(path.stat().st_size for path in paths if path.exists())


def _snapshot_time(snapshot: dict[str, Any]) -> tuple[str, int]:
    service = snapshot.get("service")
    service = service if isinstance(service, dict) else {}
    candidates: list[object] = [service.get("captured_at")]
    for battery in snapshot.get("batteries", []):
        if not isinstance(battery, dict):
            continue
        reading = battery.get("last_reading")
        if isinstance(reading, dict):
            candidates.append(reading.get("timestamp"))

    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return candidate, int(parsed.timestamp())
        except ValueError:
            continue

    now_unix = int(time.time())
    return _iso_from_unix(now_unix), now_unix


def _daily_energy_row(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    inverter = snapshot.get("inverter")
    if not isinstance(inverter, dict):
        return None
    reading = inverter.get("last_reading")
    if not isinstance(reading, dict):
        return None

    energy = {
        "consumption_kwh": _nonnegative_number(
            reading.get("load_energy_today_kwh")
        ),
        "solar_generation_kwh": _nonnegative_number(
            reading.get("pv_energy_today_kwh")
        ),
        "grid_import_kwh": _nonnegative_number(
            reading.get("grid_import_energy_today_kwh")
        ),
    }
    if all(value is None for value in energy.values()):
        return None

    captured_at, captured_at_unix = _energy_sample_time(snapshot, reading)
    parsed = datetime.fromtimestamp(captured_at_unix, timezone.utc)
    return {
        "energy_date": parsed.date().isoformat(),
        "inverter_id": str(inverter.get("id") or reading.get("id") or "inverter"),
        "captured_at": captured_at,
        "captured_at_unix": captured_at_unix,
        **energy,
    }


def _inverter_reading_row(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    inverter = snapshot.get("inverter")
    if not isinstance(inverter, dict):
        return None
    reading = inverter.get("last_reading")
    if not isinstance(reading, dict):
        return None

    grid_import = _number(reading.get("grid_import_power_w"))
    grid_export = _number(reading.get("grid_export_power_w"))
    if grid_import is not None or grid_export is not None:
        grid_power = (grid_import or 0.0) - (grid_export or 0.0)
    else:
        grid_total = _number(reading.get("grid_total_power_w"))
        grid_power = -grid_total if grid_total is not None else None

    values = {
        "grid_power_w": grid_power,
        "solar_power_w": _number(reading.get("pv_total_power_w")),
        "load_power_w": _number(reading.get("load_total_power_w")),
        "home_load_power_w": _number(reading.get("home_load_total_power_w")),
        "consumption_meter_kwh": _nonnegative_number(
            reading.get("load_energy_today_kwh")
        ),
        "solar_generation_meter_kwh": _nonnegative_number(
            reading.get("pv_energy_today_kwh")
        ),
        "grid_import_meter_kwh": _nonnegative_number(
            reading.get("grid_import_energy_today_kwh")
        ),
    }
    if all(value is None for value in values.values()):
        return None

    service = snapshot.get("service")
    service = service if isinstance(service, dict) else {}
    captured_at, captured_at_unix = _energy_sample_time(snapshot, reading)
    return {
        "captured_at": captured_at,
        "captured_at_unix": captured_at_unix,
        "collector_stream_id": _optional_string(service.get("buffer_stream_id")),
        "collector_sequence": _int(service.get("sequence")),
        "inverter_id": str(inverter.get("id") or reading.get("id") or "inverter"),
        "status": str(inverter.get("status") or "unknown"),
        **values,
    }


def _energy_sample_time(
    snapshot: dict[str, Any], reading: dict[str, Any]
) -> tuple[str, int]:
    service = snapshot.get("service")
    service = service if isinstance(service, dict) else {}
    for candidate in (reading.get("timestamp"), service.get("captured_at")):
        if not isinstance(candidate, str) or not candidate:
            continue
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc)
            return _iso_from_unix(int(parsed.timestamp())), int(parsed.timestamp())
        except ValueError:
            continue
    return _snapshot_time(snapshot)


def _counter_rise(previous: float | None, meter: float) -> float:
    """Energy one reading adds to a resetting counter.

    The Python twin of ``_counter_delta_expression``: the rise since the
    previous reading, or the reading's own value when the counter dropped (it
    reset) or when there is no previous reading yet.
    """
    if previous is None or meter < previous:
        return max(0.0, meter)
    return meter - previous


def _counter_delta_expression(meter: str, previous: str) -> str:
    """Energy a reading adds to a resetting daily counter.

    The rise since the previous reading, or the reading's own value when the
    counter has dropped (it reset since the previous reading) or has no previous
    reading in the partition. Summed over a day partition this yields the day's
    total even if the counter resets more than once within the day.
    """
    return f"""
        CASE
            WHEN {previous} IS NULL THEN {meter}
            WHEN {meter} >= {previous} THEN {meter} - {previous}
            ELSE {meter}
        END
    """


def _sum_energy_rows(rows: list[Any]) -> dict[str, float | None]:
    """Total a window as the sum of its emitted intervals.

    Keeping the total in step with the bars means it stays correct even when the
    counter's daily reset lands inside the window (an inverter clock set to a
    different zone than the viewer): each point already measures its own interval,
    so their sum is the real window energy, not a single end-of-window counter
    reading that would miss everything before a mid-window reset.
    """

    def total(field: str) -> float | None:
        values = [row[field] for row in rows if row[field] is not None]
        return sum(values) if values else None

    return {
        "consumption_kwh": _rounded_number(total("consumption_kwh")),
        "solar_generation_kwh": _rounded_number(total("solar_generation_kwh")),
        "grid_import_kwh": _rounded_number(total("grid_import_kwh")),
    }


def _interval_energy_expression(
    meter: str,
    previous: str,
    first_bucket_condition: str,
    bucket_seconds: int,
) -> str:
    """SQL for one interval of energy from a counter that resets every local day.

    The inverter's ``*_energy_today_kwh`` counters restart at its local midnight,
    which is not 00:00 UTC. Rather than assume when that happens, a reset is
    detected from the data: if the counter reads *lower* than the previous interval
    it restarted inside this bucket, so everything it now reads accumulated
    during this interval. Non-adjacent buckets contribute nothing, because the
    energy between them cannot be attributed to a single interval.
    """
    return f"""
        CASE
            WHEN {first_bucket_condition}
            THEN {meter}
            WHEN bucket_unix - previous_bucket_unix = {bucket_seconds}
                 AND {meter} < {previous}
            THEN {meter}
            WHEN bucket_unix - previous_bucket_unix = {bucket_seconds}
                 AND {meter} >= {previous}
            THEN {meter} - {previous}
        END
    """


def _energy_period_time(period: str, view: EnergyView) -> tuple[str, int]:
    if view == "year":
        # period is a YYYY-MM month; anchor it mid-month.
        value = f"{period}-15T12:00:00Z"
    else:
        # "date" and "month" periods are a full YYYY-MM-DD calendar day.
        value = f"{period}T12:00:00Z"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value, int(parsed.timestamp())


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _nonnegative_number(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and number >= 0 else None


def _rounded_number(value: object) -> float | None:
    number = _number(value)
    return round(number, 3) if number is not None else None


def _rounded_power(value: object) -> float | None:
    number = _number(value)
    return round(number, 1) if number is not None else None


def _int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _optional_string(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _iso_from_unix(value: int) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
