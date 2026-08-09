from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    collector_url: str
    collector_timeout_seconds: float
    data_dir: Path
    database_path: Path
    log_interval_seconds: float
    retention_days: int
    log_level: str


def load_settings() -> Settings:
    data_dir = Path(os.getenv("BQM_DATA_DIR", "/data"))
    return Settings(
        host=os.getenv("BQM_HOST", "0.0.0.0"),
        port=int(os.getenv("BQM_PORT", "8080")),
        collector_url=os.getenv(
            "BQM_COLLECTOR_URL", "http://batteries-query-service:8000"
        ),
        collector_timeout_seconds=float(os.getenv("BQM_COLLECTOR_TIMEOUT_SECONDS", "5")),
        data_dir=data_dir,
        database_path=Path(
            os.getenv("BQM_DATABASE_PATH", str(data_dir / "battery-monitor.sqlite3"))
        ),
        log_interval_seconds=float(os.getenv("BQM_LOG_INTERVAL_SECONDS", "60")),
        retention_days=int(os.getenv("BQM_RETENTION_DAYS", "1095")),
        log_level=os.getenv("BQM_LOG_LEVEL", "INFO"),
    )
