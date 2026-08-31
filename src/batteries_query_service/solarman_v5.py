from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .renogy_x import (
    MAX_READ_REGISTERS,
    RenogyXProtocolError,
    collect_register_ranges,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SolarmanV5Settings:
    host: str
    logger_serial: int
    port: int = 8899
    timeout_seconds: float = 2.0
    error_correction: bool = False

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("SOLARMAN logger host is required")
        if "://" in self.host:
            raise ValueError("SOLARMAN logger host must not include a URL scheme")
        if not 1 <= self.port <= 65535:
            raise ValueError("SOLARMAN logger TCP port must be between 1 and 65535")
        if not 1 <= self.logger_serial <= 0xFFFFFFFF:
            raise ValueError(
                "SOLARMAN logger serial must be between 1 and 4294967295"
            )
        if self.timeout_seconds <= 0:
            raise ValueError("SOLARMAN timeout must be greater than zero")


class SolarmanV5ModbusClient:
    """Read-only Modbus register client tunneled through a SOLARMAN logger."""

    def __init__(
        self,
        settings: SolarmanV5Settings,
        *,
        client_factory: Callable[..., Any] | None = None,
    ):
        self.settings = settings
        self._client_factory = client_factory
        self._client: Any | None = None
        self._connected_address: int | None = None

    @property
    def connection_description(self) -> str:
        return (
            f"SOLARMAN V5 logger {self.settings.host}:{self.settings.port} "
            f"(serial {self.settings.logger_serial})"
        )

    @property
    def troubleshooting_hint(self) -> str:
        return (
            "Verify the LSW-5 IP and port 8899 are reachable from the container, "
            "logger_serial is the number printed on the logger rather than the "
            "inverter serial, and the inverter Modbus address is correct"
        )

    def read_holding_registers(
        self, address: int, start: int, count: int
    ) -> list[int]:
        if not 1 <= address <= 247:
            raise ValueError("Modbus address must be between 1 and 247")
        if not 0 <= start <= 0xFFFF:
            raise ValueError("Register start address must fit in 16 bits")
        if not 1 <= count <= MAX_READ_REGISTERS:
            raise ValueError(
                f"Register count must be between 1 and {MAX_READ_REGISTERS}"
            )
        if start + count > 0x10000:
            raise ValueError("Register range exceeds address 65535")

        values = self._connection(address).read_holding_registers(
            register_addr=start,
            quantity=count,
        )
        result = [int(value) for value in values]
        if len(result) != count:
            raise RenogyXProtocolError(
                f"SOLARMAN read {start}+{count} returned {len(result)} registers"
            )
        if any(not 0 <= value <= 0xFFFF for value in result):
            raise RenogyXProtocolError("SOLARMAN returned an invalid register value")
        return result

    def read_ranges(
        self,
        address: int,
        ranges: Iterable[tuple[int, int]],
        *,
        chunk_size: int = 60,
        continue_on_error: bool = False,
        retries: int = 0,
        retry_delay_seconds: float = 0.15,
        inter_request_delay_seconds: float = 0.02,
    ) -> tuple[dict[int, int], list[dict[str, object]]]:
        return collect_register_ranges(
            lambda start, count: self.read_holding_registers(
                address, start, count
            ),
            ranges,
            chunk_size=chunk_size,
            continue_on_error=continue_on_error,
            retries=retries,
            retry_delay_seconds=retry_delay_seconds,
            inter_request_delay_seconds=inter_request_delay_seconds,
        )

    def close(self) -> None:
        client = self._client
        self._client = None
        self._connected_address = None
        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            logger.debug("Failed to close SOLARMAN logger connection", exc_info=True)

    def _connection(self, address: int):
        if self._client is not None:
            if self._connected_address != address:
                raise ValueError(
                    "One SOLARMAN connection cannot use multiple Modbus addresses"
                )
            return self._client

        factory = self._client_factory
        if factory is None:
            try:
                from pysolarmanv5 import PySolarmanV5
            except ImportError as exc:
                raise RuntimeError(
                    "pysolarmanv5 is required for the SOLARMAN V5 transport"
                ) from exc
            factory = PySolarmanV5

        self._client = factory(
            self.settings.host,
            self.settings.logger_serial,
            port=self.settings.port,
            mb_slave_id=address,
            socket_timeout=self.settings.timeout_seconds,
            v5_error_correction=self.settings.error_correction,
            auto_reconnect=True,
        )
        self._connected_address = address
        return self._client
