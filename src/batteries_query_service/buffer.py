from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class SnapshotBuffer:
    """Short-lived collector snapshots used to repair monitor log gaps."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._stream_id: str | None = None

    def initialize(self) -> None:
        with self._lock:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self.connection
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    captured_at_unix INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at_unix
                    ON snapshots (captured_at_unix);
                CREATE TABLE IF NOT EXISTS buffer_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            row = connection.execute(
                "SELECT value FROM buffer_metadata WHERE key = 'stream_id'"
            ).fetchone()
            if row is None:
                self._stream_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO buffer_metadata (key, value) VALUES ('stream_id', ?)",
                    (self._stream_id,),
                )
            else:
                self._stream_id = str(row["value"])
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

    def append(self, snapshot: dict[str, Any]) -> int:
        captured_at = str(snapshot.get("service", {}).get("captured_at") or _utc_now())
        payload = json.dumps(snapshot, separators=(",", ":"), sort_keys=True)
        with self._lock:
            cursor = self.connection.execute(
                """
                INSERT INTO snapshots (captured_at, captured_at_unix, snapshot_json)
                VALUES (?, ?, ?)
                """,
                (captured_at, int(time.time()), payload),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    @property
    def stream_id(self) -> str | None:
        return self._stream_id

    def read_after(self, sequence: int, limit: int = 500) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit), 2000))
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT sequence, captured_at, snapshot_json
                FROM snapshots
                WHERE sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (max(0, int(sequence)), safe_limit + 1),
            ).fetchall()
            latest_sequence = self.latest_sequence()

        has_more = len(rows) > safe_limit
        snapshots = []
        for row in rows[:safe_limit]:
            try:
                snapshot = json.loads(row["snapshot_json"])
            except json.JSONDecodeError:
                continue
            if not isinstance(snapshot, dict):
                continue
            service = snapshot.setdefault("service", {})
            if isinstance(service, dict):
                service["sequence"] = int(row["sequence"])
                service["buffer_stream_id"] = self._stream_id
                service.setdefault("captured_at", row["captured_at"])
            snapshots.append(snapshot)

        return {
            "after_sequence": max(0, int(sequence)),
            "latest_sequence": latest_sequence,
            "has_more": has_more,
            "snapshots": snapshots,
        }

    def prune_older_than_hours(self, hours: int) -> int:
        cutoff = int(time.time()) - max(1, int(hours)) * 60 * 60
        with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM snapshots WHERE captured_at_unix < ?", (cutoff,)
            )
            self.connection.commit()
            return int(cursor.rowcount or 0)

    def latest_sequence(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM snapshots"
            ).fetchone()
            return int(row["sequence"] or 0)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS snapshot_count,
                       COALESCE(MAX(sequence), 0) AS latest_sequence,
                       MIN(captured_at) AS oldest_snapshot_at,
                       MAX(captured_at) AS newest_snapshot_at
                FROM snapshots
                """
            ).fetchone()
        return {
            "status": "ok",
            "database_path": str(self.database_path),
            "stream_id": self._stream_id,
            "snapshot_count": int(row["snapshot_count"] or 0),
            "latest_sequence": int(row["latest_sequence"] or 0),
            "oldest_snapshot_at": row["oldest_snapshot_at"],
            "newest_snapshot_at": row["newest_snapshot_at"],
        }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
