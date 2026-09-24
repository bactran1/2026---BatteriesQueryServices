"""What the collector's own computer is doing, read from the kernel's files.

The Raspberry Pi that runs the collector sits in a battery room, and the
one thing that quietly kills a Pi in a warm cupboard is heat: the SoC
throttles at 80 C and the SD card wears out long before anyone notices. So
each poll also samples the host -- CPU load, SoC temperature, memory, the
data disk, and the firmware's throttle flags -- and hands it along with the
readings, so the dashboard can show a small readout under the connection
status and an operator sees a Pi in trouble before the readings stop.

Everything here is a file read from procfs or sysfs, which Docker mounts
into the container by default, so no extra privileges or mounts are needed.
Every field is optional: a file that is missing (a thermal zone on a machine
that has none, the firmware node on a non-Pi host) makes that one field
``None`` and nothing else. Sampling never raises.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROC_STAT = Path("/proc/stat")
PROC_MEMINFO = Path("/proc/meminfo")
PROC_LOADAVG = Path("/proc/loadavg")
PROC_UPTIME = Path("/proc/uptime")
THERMAL_ROOT = Path("/sys/class/thermal")
# The VideoCore firmware's throttle status, exposed by the kernel on Pi 4/5.
THROTTLED_FILE = Path("/sys/devices/platform/soc/soc:firmware/get_throttled")

# get_throttled bit layout: bits 0-3 are conditions active right now, bits
# 16-19 the same conditions having occurred since boot.
THROTTLE_FLAGS: tuple[tuple[int, str], ...] = (
    (0, "under_voltage"),
    (1, "frequency_capped"),
    (2, "throttled"),
    (3, "soft_temperature_limit"),
)
OCCURRED_SHIFT = 16


class HostStats:
    """Sample the host once per call; CPU load is the change since last time."""

    def __init__(
        self,
        data_path: Path | str | None = None,
        *,
        read_text: Callable[[Path], str] | None = None,
        thermal_zones: Callable[[], list[Path]] | None = None,
        statvfs: Callable[[str], Any] | None = None,
    ) -> None:
        self.data_path = str(data_path) if data_path else None
        self._read_text = read_text or _read_file
        self._thermal_zones = thermal_zones or _thermal_zones
        self._statvfs = statvfs or os.statvfs
        self._last_cpu: tuple[int, int] | None = None

    def sample(self) -> dict[str, Any]:
        load = self._load()
        memory = self._memory()
        disk = self._disk()
        return {
            "sampled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cpu_percent": self._cpu_percent(),
            "cpu_temperature_c": self._temperature(),
            "load_1m": load[0],
            "load_5m": load[1],
            "load_15m": load[2],
            "uptime_seconds": self._uptime(),
            **memory,
            **disk,
            "throttled": self._throttled(),
        }

    # -- each reader answers None for anything it cannot read -----------------

    def _cpu_percent(self) -> float | None:
        try:
            first_line = self._read_text(PROC_STAT).splitlines()[0]
            fields = [int(value) for value in first_line.split()[1:9]]
        except (OSError, ValueError, IndexError):
            return None
        if len(fields) < 5:
            return None
        total = sum(fields)
        idle = fields[3] + fields[4]  # idle + iowait
        busy = total - idle
        previous, self._last_cpu = self._last_cpu, (busy, total)
        if previous is None:
            return None
        delta_total = total - previous[1]
        if delta_total <= 0:
            return None
        return round(100.0 * (busy - previous[0]) / delta_total, 1)

    def _temperature(self) -> float | None:
        # Prefer the SoC's own zone (the Pi names it cpu-thermal); otherwise
        # the first zone that answers, which on a Pi is the same one.
        zones = []
        try:
            zones = list(self._thermal_zones())
        except OSError:
            return None
        preferred = None
        fallback = None
        for zone in zones:
            try:
                millidegrees = int(self._read_text(zone / "temp").strip())
            except (OSError, ValueError):
                continue
            try:
                kind = self._read_text(zone / "type").strip().lower()
            except OSError:
                kind = ""
            if "cpu" in kind and preferred is None:
                preferred = millidegrees
            elif fallback is None:
                fallback = millidegrees
        chosen = preferred if preferred is not None else fallback
        return None if chosen is None else round(chosen / 1000.0, 1)

    def _memory(self) -> dict[str, float | None]:
        empty = {"memory_percent": None, "memory_used_mb": None, "memory_total_mb": None}
        try:
            values: dict[str, int] = {}
            for line in self._read_text(PROC_MEMINFO).splitlines():
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    values[key] = int(rest.split()[0])  # kB
            total = values["MemTotal"]
            available = values["MemAvailable"]
        except (OSError, ValueError, KeyError, IndexError):
            return empty
        if total <= 0:
            return empty
        used = max(0, total - available)
        return {
            "memory_percent": round(100.0 * used / total, 1),
            "memory_used_mb": round(used / 1024.0),
            "memory_total_mb": round(total / 1024.0),
        }

    def _load(self) -> tuple[float | None, float | None, float | None]:
        try:
            parts = self._read_text(PROC_LOADAVG).split()
            return float(parts[0]), float(parts[1]), float(parts[2])
        except (OSError, ValueError, IndexError):
            return None, None, None

    def _uptime(self) -> int | None:
        try:
            return int(float(self._read_text(PROC_UPTIME).split()[0]))
        except (OSError, ValueError, IndexError):
            return None

    def _disk(self) -> dict[str, float | None]:
        empty = {"disk_percent": None, "disk_free_gb": None, "disk_total_gb": None}
        if not self.data_path:
            return empty
        try:
            stat = self._statvfs(self.data_path)
            block = int(stat.f_frsize)
            total = int(stat.f_blocks) * block
            free = int(stat.f_bavail) * block
        except (OSError, AttributeError, TypeError, ValueError):
            return empty
        if total <= 0:
            return empty
        used = max(0, total - free)
        return {
            "disk_percent": round(100.0 * used / total, 1),
            "disk_free_gb": round(free / 1e9, 2),
            "disk_total_gb": round(total / 1e9, 2),
        }

    def _throttled(self) -> dict[str, Any] | None:
        try:
            raw = int(self._read_text(THROTTLED_FILE).strip(), 16)
        except (OSError, ValueError):
            return None
        return decode_throttle_flags(raw)


def decode_throttle_flags(raw: int) -> dict[str, Any]:
    """Name the bits of the firmware's get_throttled word."""
    active = [name for bit, name in THROTTLE_FLAGS if raw & (1 << bit)]
    occurred = [
        name for bit, name in THROTTLE_FLAGS if raw & (1 << (bit + OCCURRED_SHIFT))
    ]
    return {"raw": f"0x{raw:X}", "active": active, "occurred": occurred}


def _read_file(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _thermal_zones() -> list[Path]:
    if not THERMAL_ROOT.is_dir():
        return []
    return sorted(THERMAL_ROOT.glob("thermal_zone*"))
