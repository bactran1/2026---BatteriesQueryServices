from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BatteryProfile:
    id: str
    name: str
    address: int
    ip_address: str | None
    model: str


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
    build_commit: str
    rack_name: str
    rack_builder: str
    rack_location: str
    collector_name: str
    battery_profiles: tuple[BatteryProfile, ...]


def load_settings() -> Settings:
    data_dir = Path(os.getenv("BQM_DATA_DIR", "/data"))
    battery_profiles = _load_battery_profiles()
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
        build_commit=os.getenv("BQM_BUILD_COMMIT", "unknown"),
        rack_name=os.getenv("BQM_RACK_NAME", "Eco-worthy Rack"),
        rack_builder=os.getenv("BQM_RACK_BUILDER", "Tran Thanh Tuan"),
        rack_location=os.getenv("BQM_RACK_LOCATION", "Battery room"),
        collector_name=os.getenv("BQM_COLLECTOR_NAME", "Raspberry Pi collector"),
        battery_profiles=battery_profiles,
    )


def rack_details(
    settings: Settings,
    batteries: list[dict[str, Any]],
    collector_online: bool = True,
) -> dict[str, Any]:
    by_id = {str(battery.get("id")): battery for battery in batteries}
    by_address = {
        battery.get("address"): battery
        for battery in batteries
        if battery.get("address") is not None
    }
    inventory = []
    matched_ids: set[str] = set()

    for profile in settings.battery_profiles:
        battery = by_id.get(profile.id) or by_address.get(profile.address)
        if battery:
            matched_ids.add(str(battery.get("id")))
        inventory.append(_inventory_item(profile, battery, collector_online))

    for battery in batteries:
        battery_id = str(battery.get("id", "unknown"))
        if battery_id in matched_ids:
            continue
        address = _optional_int(battery.get("address"))
        inventory.append(
            _inventory_item(
                BatteryProfile(
                    id=battery_id,
                    name=battery_id,
                    address=address if address is not None else len(inventory) + 1,
                    ip_address=None,
                    model="Eco-worthy server rack battery",
                ),
                battery,
                collector_online,
            )
        )

    return {
        "name": settings.rack_name,
        "builder": settings.rack_builder,
        "location": settings.rack_location,
        "expected_battery_count": len(settings.battery_profiles),
        "observed_battery_count": len(batteries),
        "online_battery_count": (
            sum(1 for battery in batteries if battery.get("status") == "ok")
            if collector_online
            else 0
        ),
        "collector": {
            "name": settings.collector_name,
            "url": settings.collector_url,
        },
        "connection": "Modbus RTU over RS485",
        "retention_days": settings.retention_days,
        "batteries": inventory,
    }


def _load_battery_profiles() -> tuple[BatteryProfile, ...]:
    ids = _csv_values(os.getenv("BQM_BATTERY_IDS", "rack-1,rack-2,rack-3"))
    addresses = _csv_ints(os.getenv("BQM_BATTERY_ADDRESSES", "1,2,3"))
    names = _csv_values(
        os.getenv("BQM_BATTERY_NAMES", "Rack Battery 1,Rack Battery 2,Rack Battery 3"),
        preserve_empty=True,
    )
    ip_addresses = _csv_values(
        os.getenv("BQM_BATTERY_IPS", ",,"), preserve_empty=True
    )
    models = _csv_values(
        os.getenv(
            "BQM_BATTERY_MODELS",
            "Eco-worthy server rack battery,Eco-worthy server rack battery,Eco-worthy server rack battery",
        ),
        preserve_empty=True,
    )

    return tuple(
        BatteryProfile(
            id=battery_id,
            name=_value_at(names, index) or f"Rack Battery {index + 1}",
            address=addresses[index] if index < len(addresses) else index + 1,
            ip_address=_value_at(ip_addresses, index) or None,
            model=_value_at(models, index) or "Eco-worthy server rack battery",
        )
        for index, battery_id in enumerate(ids)
    )


def _inventory_item(
    profile: BatteryProfile,
    battery: dict[str, Any] | None,
    collector_online: bool,
) -> dict[str, Any]:
    battery = battery or {}
    reading = battery.get("last_reading")
    reading = reading if isinstance(reading, dict) else {}
    return {
        "id": str(battery.get("id") or profile.id),
        "name": profile.name,
        "address": battery.get("address", profile.address),
        "ip_address": profile.ip_address,
        "model": profile.model,
        "status": (
            battery.get("status", "not_seen") if collector_online else "stale"
        ),
        "last_error": battery.get("last_error"),
        "last_polled_at": battery.get("last_polled_at") or reading.get("timestamp"),
        "serial_number": reading.get("serial_number"),
        "firmware_version": reading.get("firmware_version"),
        "rs485_protocol": reading.get("rs485_protocol"),
    }


def _csv_values(value: str, preserve_empty: bool = False) -> list[str]:
    values = [part.strip() for part in value.split(",")]
    return values if preserve_empty else [part for part in values if part]


def _csv_ints(value: str) -> list[int]:
    return [int(part) for part in _csv_values(value)]


def _value_at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
