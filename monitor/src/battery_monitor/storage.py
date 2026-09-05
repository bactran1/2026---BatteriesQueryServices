from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

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

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

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
                CREATE INDEX IF NOT EXISTS idx_inverter_readings_time
                    ON inverter_readings (captured_at_unix);
                CREATE INDEX IF NOT EXISTS idx_inverter_readings_inverter_time
                    ON inverter_readings (inverter_id, captured_at_unix);
                """
            )
            self._ensure_column("collector_stream_id", "TEXT")
            self._ensure_column("collector_sequence", "INTEGER")
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
            connection.execute("PRAGMA optimize")
            connection.commit()

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
            self.connection.commit()
            return inserted

    def insert_snapshots(self, snapshots: list[dict[str, Any]]) -> int:
        with self._lock:
            inserted = 0
            for snapshot in snapshots:
                if not isinstance(snapshot, dict):
                    continue
                inserted += self._insert_snapshot_locked(snapshot)
                self._insert_inverter_reading_locked(snapshot)
                self._upsert_daily_energy_locked(snapshot)
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
            inverter_cursor = self.connection.execute(
                "DELETE FROM inverter_readings WHERE captured_at_unix < ?", (cutoff,)
            )
            self.connection.commit()
            return (
                int(cursor.rowcount or 0)
                + int(energy_cursor.rowcount or 0)
                + int(inverter_cursor.rowcount or 0)
            )

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
            return self._hourly_energy_history()
        if view == "date":
            selected_date = energy_date or datetime.now(
                ZoneInfo(energy_timezone)
            ).date().isoformat()
            return self._hourly_energy_history(selected_date, energy_timezone)

        period_expression = {
            "month": "substr(energy_date, 1, 7)",
            "year": "substr(energy_date, 1, 4)",
        }[str(view)]
        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT
                    {period_expression} AS period,
                    SUM(consumption_kwh) AS consumption_kwh,
                    SUM(solar_generation_kwh) AS solar_generation_kwh,
                    SUM(grid_import_kwh) AS grid_import_kwh
                FROM daily_energy
                WHERE energy_date >= date('now', '-3 years')
                GROUP BY period
                ORDER BY period ASC
                """
            ).fetchall()
            totals = self._energy_totals_locked()

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
            "retention_years": 3,
            "points": points,
            "totals": totals,
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
                        AVG(load_power_w) AS load_power_w
                    FROM inverter_readings
                    WHERE {time_filter}
                      AND (
                          grid_power_w IS NOT NULL
                          OR solar_power_w IS NOT NULL
                          OR load_power_w IS NOT NULL
                      )
                    GROUP BY bucket_unix, inverter_id
                ),
                inverter_by_bucket AS (
                    SELECT
                        bucket_unix,
                        SUM(grid_power_w) AS grid_power_w,
                        SUM(solar_power_w) AS solar_power_w,
                        SUM(load_power_w) AS load_power_w
                    FROM inverter_by_device
                    GROUP BY bucket_unix
                ),
                battery_by_pack AS (
                    SELECT
                        CAST(captured_at_unix / ? AS INTEGER) * ? AS bucket_unix,
                        battery_id,
                        AVG(power_w) AS battery_power_w
                    FROM readings
                    WHERE {time_filter}
                      AND status = 'ok'
                      AND power_w IS NOT NULL
                    GROUP BY bucket_unix, battery_id
                ),
                battery_by_bucket AS (
                    SELECT
                        bucket_unix,
                        SUM(battery_power_w) AS battery_power_w
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
                    inverter_by_bucket.solar_power_w,
                    inverter_by_bucket.load_power_w
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
                "solar_power_w": _rounded_power(row["solar_power_w"]),
                "load_power_w": _rounded_power(row["load_power_w"]),
            }
            for row in rows
        ]

    def _hourly_energy_history(
        self, energy_date: str | None = None, energy_timezone: str = "UTC"
    ) -> dict[str, Any]:
        if energy_date is None:
            time_filter = "captured_at_unix >= strftime('%s', 'now', '-7 days')"
            params: tuple[object, ...] = ()
            window_start_unix = int(time.time()) - 7 * 24 * 60 * 60
            window_end_unix = int(time.time())
            window_partition = "inverter_id, date(bucket_unix, 'unixepoch')"
            bucket_expression = (
                "CAST(captured_at_unix / 3600 AS INTEGER) * 3600"
            )
            first_bucket_condition = """
                previous_bucket_unix IS NULL
                AND strftime('%H', bucket_unix, 'unixepoch') = '00'
            """
        else:
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
                CAST((captured_at_unix - {window_start_unix}) / 3600 AS INTEGER)
                    * 3600 + {window_start_unix}
            """
            first_bucket_condition = f"""
                previous_bucket_unix IS NULL
                AND bucket_unix - {window_start_unix} < 3600
            """

        with self._lock:
            rows = self.connection.execute(
                f"""
                WITH hourly AS (
                    SELECT
                        {bucket_expression} AS bucket_unix,
                        inverter_id,
                        MAX(consumption_meter_kwh) AS consumption_meter_kwh,
                        MAX(solar_generation_meter_kwh)
                            AS solar_generation_meter_kwh,
                        MAX(grid_import_meter_kwh) AS grid_import_meter_kwh
                    FROM inverter_readings
                    WHERE {time_filter}
                    GROUP BY bucket_unix, inverter_id
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
                    FROM hourly
                    WINDOW day_window AS (
                        PARTITION BY {window_partition}
                        ORDER BY bucket_unix
                    )
                )
                SELECT
                    bucket_unix,
                    SUM(
                        CASE
                            WHEN {first_bucket_condition}
                            THEN consumption_meter_kwh
                            WHEN bucket_unix - previous_bucket_unix = 3600
                                 AND consumption_meter_kwh >= previous_consumption_kwh
                            THEN consumption_meter_kwh - previous_consumption_kwh
                        END
                    ) AS consumption_kwh,
                    SUM(
                        CASE
                            WHEN {first_bucket_condition}
                            THEN solar_generation_meter_kwh
                            WHEN bucket_unix - previous_bucket_unix = 3600
                                 AND solar_generation_meter_kwh >= previous_solar_kwh
                            THEN solar_generation_meter_kwh - previous_solar_kwh
                        END
                    ) AS solar_generation_kwh,
                    SUM(
                        CASE
                            WHEN {first_bucket_condition}
                            THEN grid_import_meter_kwh
                            WHEN bucket_unix - previous_bucket_unix = 3600
                                 AND grid_import_meter_kwh >= previous_grid_kwh
                            THEN grid_import_meter_kwh - previous_grid_kwh
                        END
                    ) AS grid_import_kwh
                FROM deltas
                GROUP BY bucket_unix
                HAVING consumption_kwh IS NOT NULL
                    OR solar_generation_kwh IS NOT NULL
                    OR grid_import_kwh IS NOT NULL
                ORDER BY bucket_unix ASC
                """,
                params,
            ).fetchall()
            totals = (
                self._energy_totals_for_window_locked(
                    window_start_unix, window_end_unix
                )
                if energy_date is not None
                else self._energy_totals_locked()
            )

        return {
            "view": "date" if energy_date is not None else "hour",
            "retention_years": 3,
            "window_days": 1 if energy_date is not None else 7,
            "selected_date": energy_date,
            "timezone": energy_timezone if energy_date is not None else "UTC",
            "window_start": _iso_from_unix(window_start_unix),
            "window_start_unix": window_start_unix,
            "window_end": _iso_from_unix(window_end_unix),
            "window_end_unix": window_end_unix,
            "points": [
                {
                    "period": _iso_from_unix(int(row["bucket_unix"]))[:13],
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

    def _energy_totals_for_window_locked(
        self, window_start_unix: int, window_end_unix: int
    ) -> dict[str, float | None]:
        row = self.connection.execute(
            """
            SELECT
                SUM(consumption_kwh) AS consumption_kwh,
                SUM(solar_generation_kwh) AS solar_generation_kwh,
                SUM(grid_import_kwh) AS grid_import_kwh
            FROM (
                SELECT
                    inverter_id,
                    MAX(consumption_meter_kwh) AS consumption_kwh,
                    MAX(solar_generation_meter_kwh) AS solar_generation_kwh,
                    MAX(grid_import_meter_kwh) AS grid_import_kwh
                FROM inverter_readings
                WHERE captured_at_unix >= ? AND captured_at_unix < ?
                GROUP BY inverter_id
            )
            """,
            (window_start_unix, window_end_unix),
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

    def _ensure_column(self, name: str, declaration: str) -> None:
        columns = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(readings)").fetchall()
        }
        if name not in columns:
            self.connection.execute(
                f"ALTER TABLE readings ADD COLUMN {name} {declaration}"
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


def _energy_period_time(period: str, view: EnergyView) -> tuple[str, int]:
    if view == "date":
        value = f"{period}T12:00:00Z"
    elif view == "month":
        value = f"{period}-15T12:00:00Z"
    else:
        value = f"{period}-07-01T12:00:00Z"
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
