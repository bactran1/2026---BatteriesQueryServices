from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
                CREATE INDEX IF NOT EXISTS idx_readings_time
                    ON readings (captured_at_unix);
                CREATE INDEX IF NOT EXISTS idx_readings_battery_time
                    ON readings (battery_id, captured_at_unix);
                CREATE INDEX IF NOT EXISTS idx_readings_events
                    ON readings (captured_at_unix, alarm_count, fault_count, status);
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
            self.connection.commit()
            return inserted

    def insert_snapshots(self, snapshots: list[dict[str, Any]]) -> int:
        with self._lock:
            inserted = sum(
                self._insert_snapshot_locked(snapshot)
                for snapshot in snapshots
                if isinstance(snapshot, dict)
            )
            self.connection.commit()
            return inserted

    def prune_older_than_days(self, days: int) -> int:
        cutoff = int(time.time()) - days * 24 * 60 * 60
        with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM readings WHERE captured_at_unix < ?", (cutoff,)
            )
            self.connection.commit()
            return int(cursor.rowcount or 0)

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
        return {
            "database_path": str(self.database_path),
            "database_size_bytes": self._database_size_bytes(),
            "row_count": int(row["row_count"] or 0),
            "battery_count": int(row["battery_count"] or 0),
            "oldest_reading_at": row["oldest_reading_at"],
            "newest_reading_at": row["newest_reading_at"],
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


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


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
