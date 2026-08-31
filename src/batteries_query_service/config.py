from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServerSettings:
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass(frozen=True)
class SerialSettings:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 9600
    timeout_seconds: float = 2.0


@dataclass(frozen=True)
class PollingSettings:
    interval_seconds: float = 10.0


@dataclass(frozen=True)
class BufferSettings:
    enabled: bool = True
    path: str = "/data/collector-buffer.sqlite3"
    retention_hours: int = 24
    sample_interval_seconds: float = 60.0


@dataclass(frozen=True)
class BatterySettings:
    id: str
    address: int
    serial_port: str | None = None
    enabled: bool = True

    def resolved_serial_port(self, default_port: str) -> str:
        return self.serial_port or default_port


@dataclass(frozen=True)
class InverterSettings:
    enabled: bool = False
    id: str = "renogy-x-8k"
    model: str = "Renogy X 8K (Megarevo R8KLNA-compatible)"
    transport: str = "serial"
    serial_port: str = "/dev/ttyUSB1"
    host: str = ""
    tcp_port: int = 8899
    logger_serial: int | None = None
    v5_error_correction: bool = False
    address: int = 1
    baudrate: int = 9600
    timeout_seconds: float = 2.0
    parity: str = "N"
    retries: int = 2


@dataclass(frozen=True)
class Settings:
    server: ServerSettings = field(default_factory=ServerSettings)
    serial: SerialSettings = field(default_factory=SerialSettings)
    polling: PollingSettings = field(default_factory=PollingSettings)
    buffer: BufferSettings = field(default_factory=BufferSettings)
    inverter: InverterSettings = field(default_factory=InverterSettings)
    batteries: list[BatterySettings] = field(default_factory=list)
    log_level: str = "INFO"
    build_commit: str = "unknown"

    def safe_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_settings(config_path: str | None = None) -> Settings:
    path = Path(os.getenv("BQS_CONFIG", config_path or "config.toml"))
    raw = _read_toml(path)

    server_raw = raw.get("server", {})
    serial_raw = raw.get("serial", {})
    polling_raw = raw.get("polling", {})
    buffer_raw = raw.get("buffer", {})
    inverter_raw = raw.get("inverter", {})

    server = ServerSettings(
        host=os.getenv("BQS_HOST", str(server_raw.get("host", "0.0.0.0"))),
        port=_env_int("BQS_PORT", server_raw.get("port", 8000)),
    )
    serial = SerialSettings(
        port=os.getenv("BQS_SERIAL_PORT", str(serial_raw.get("port", "/dev/ttyUSB0"))),
        baudrate=int(serial_raw.get("baudrate", 9600)),
        timeout_seconds=float(serial_raw.get("timeout_seconds", 2.0)),
    )
    polling = PollingSettings(
        interval_seconds=max(
            0.5,
            _env_float(
                "BQS_POLL_INTERVAL", polling_raw.get("interval_seconds", 10.0)
            ),
        )
    )
    buffer = BufferSettings(
        enabled=_env_bool("BQS_BUFFER_ENABLED", buffer_raw.get("enabled", True)),
        path=os.getenv(
            "BQS_BUFFER_PATH",
            str(buffer_raw.get("path", "/data/collector-buffer.sqlite3")),
        ),
        retention_hours=max(
            1,
            _env_int(
                "BQS_BUFFER_RETENTION_HOURS", buffer_raw.get("retention_hours", 24)
            ),
        ),
        sample_interval_seconds=max(
            polling.interval_seconds,
            _env_float(
                "BQS_BUFFER_SAMPLE_INTERVAL",
                buffer_raw.get("sample_interval_seconds", 60.0),
            ),
        ),
    )
    inverter = _load_inverter(inverter_raw)
    batteries = _load_batteries(raw.get("batteries", []))

    return Settings(
        server=server,
        serial=serial,
        polling=polling,
        buffer=buffer,
        inverter=inverter,
        batteries=batteries,
        log_level=os.getenv("BQS_LOG_LEVEL", str(raw.get("log_level", "INFO"))),
        build_commit=os.getenv("BQS_BUILD_COMMIT", "unknown"),
    )


def _load_inverter(raw_inverter: Any) -> InverterSettings:
    if raw_inverter and not isinstance(raw_inverter, dict):
        raise ValueError("[inverter] must be a table")
    raw = raw_inverter or {}
    enabled = _env_bool("BQS_INVERTER_ENABLED", raw.get("enabled", False))
    transport = _env_text(
        "BQS_INVERTER_TRANSPORT", raw.get("transport", "serial")
    ).lower().replace("-", "_")
    transport = {
        "lsw5": "solarman_v5",
        "lsw_5": "solarman_v5",
        "solarman": "solarman_v5",
    }.get(transport, transport)
    if transport not in {"serial", "solarman_v5"}:
        raise ValueError("Inverter transport must be serial or solarman_v5")

    parity = _env_text(
        "BQS_INVERTER_PARITY", raw.get("parity", "N")
    ).upper()
    if parity not in {"N", "E", "O"}:
        raise ValueError("Inverter parity must be N, E, or O")

    address = _env_int("BQS_INVERTER_ADDRESS", raw.get("address", 1))
    if not 1 <= address <= 247:
        raise ValueError("Inverter Modbus address must be between 1 and 247")

    baudrate = _env_int("BQS_INVERTER_BAUDRATE", raw.get("baudrate", 9600))
    if baudrate <= 0:
        raise ValueError("Inverter baudrate must be greater than zero")

    host = _env_text("BQS_INVERTER_HOST", raw.get("host", "")).strip()
    if "://" in host:
        raise ValueError("Inverter logger host must not include a URL scheme")
    tcp_port = _env_int_allow_blank(
        "BQS_INVERTER_TCP_PORT", raw.get("tcp_port", 8899)
    )
    if not 1 <= tcp_port <= 65535:
        raise ValueError("Inverter logger TCP port must be between 1 and 65535")
    logger_serial = _env_optional_int(
        "BQS_INVERTER_LOGGER_SERIAL", raw.get("logger_serial")
    )
    if logger_serial is not None and not 1 <= logger_serial <= 0xFFFFFFFF:
        raise ValueError(
            "Inverter logger serial must be between 1 and 4294967295"
        )
    if enabled and transport == "solarman_v5":
        if not host:
            raise ValueError(
                "Inverter logger host is required for solarman_v5 transport"
            )
        if logger_serial is None:
            raise ValueError(
                "Inverter logger serial is required for solarman_v5 transport"
            )

    return InverterSettings(
        enabled=enabled,
        id=os.getenv("BQS_INVERTER_ID", str(raw.get("id", "renogy-x-8k"))),
        model=os.getenv(
            "BQS_INVERTER_MODEL",
            str(
                raw.get(
                    "model",
                    "Renogy X 8K (Megarevo R8KLNA-compatible)",
                )
            ),
        ),
        transport=transport,
        serial_port=os.getenv(
            "BQS_INVERTER_SERIAL_PORT",
            str(raw.get("serial_port", "/dev/ttyUSB1")),
        ),
        host=host,
        tcp_port=tcp_port,
        logger_serial=logger_serial,
        v5_error_correction=_env_bool(
            "BQS_INVERTER_V5_ERROR_CORRECTION",
            raw.get("v5_error_correction", False),
        ),
        address=address,
        baudrate=baudrate,
        timeout_seconds=max(
            0.1,
            _env_float(
                "BQS_INVERTER_TIMEOUT_SECONDS", raw.get("timeout_seconds", 2.0)
            ),
        ),
        parity=parity,
        retries=max(0, min(5, _env_int("BQS_INVERTER_RETRIES", raw.get("retries", 2)))),
    )


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as file:
        return tomllib.load(file)


def _load_batteries(raw_batteries: Any) -> list[BatterySettings]:
    env_addresses = os.getenv("BQS_BATTERY_ADDRESSES")
    if env_addresses:
        addresses = _csv_ints(env_addresses)
        ids = _csv_strings(os.getenv("BQS_BATTERY_IDS", ""))
        return [
            BatterySettings(
                id=ids[index] if index < len(ids) else f"rack-{address}",
                address=address,
            )
            for index, address in enumerate(addresses)
        ]

    if not raw_batteries:
        return [
            BatterySettings(id="rack-1", address=1),
            BatterySettings(id="rack-2", address=2),
            BatterySettings(id="rack-3", address=3),
        ]

    batteries = []
    for index, item in enumerate(raw_batteries, start=1):
        if not isinstance(item, dict):
            raise ValueError("Each [[batteries]] entry must be a table")
        address = int(item.get("address", index))
        batteries.append(
            BatterySettings(
                id=str(item.get("id", f"rack-{address}")),
                address=address,
                serial_port=item.get("serial_port"),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return batteries


def _csv_ints(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def _csv_strings(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _env_int(name: str, default: Any) -> int:
    return int(os.getenv(name, default))


def _env_int_allow_blank(name: str, default: Any) -> int:
    value = os.getenv(name)
    return int(default if value is None or not value.strip() else value)


def _env_optional_int(name: str, default: Any) -> int | None:
    value = os.getenv(name)
    selected = default if value is None or not value.strip() else value
    if selected is None or str(selected).strip() == "":
        return None
    return int(selected)


def _env_text(name: str, default: Any) -> str:
    value = os.getenv(name)
    return str(default if value is None or not value.strip() else value)


def _env_float(name: str, default: Any) -> float:
    return float(os.getenv(name, default))


def _env_bool(name: str, default: Any) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return bool(default)
    return value.strip().lower() in {"1", "true", "yes", "on"}
