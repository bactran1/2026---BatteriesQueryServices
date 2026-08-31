from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Iterator, Protocol

from .ecoworthy import append_crc, crc16_modbus

READ_HOLDING_REGISTERS = 0x03
MAX_READ_REGISTERS = 125
UNDEFINED_REGISTER = 0xFFFF


class RenogyXProtocolError(Exception):
    """Raised when a Renogy inverter Modbus frame is invalid or rejected."""


@dataclass(frozen=True)
class RenogyXSerialSettings:
    port: str
    baudrate: int = 9600
    timeout_seconds: float = 2.0
    parity: str = "N"


class ModbusRegisterClient(Protocol):
    @property
    def connection_description(self) -> str: ...

    @property
    def troubleshooting_hint(self) -> str: ...

    def read_holding_registers(
        self, address: int, start: int, count: int
    ) -> list[int]: ...

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
    ) -> tuple[dict[int, int], list[dict[str, object]]]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class RegisterDefinition:
    name: str
    address: int
    unit: str | None = None
    scale: float = 1.0
    signed: bool = False


# Renogy's public Inverter Modbus Protocol V1.0 defines these common fields.
# It does not claim that this is the complete Renogy X hybrid-inverter map.
COMMON_REGISTER_DEFINITIONS = (
    RegisterDefinition("ac_input_voltage_v", 4000, "V", 0.1),
    RegisterDefinition("ac_input_current_a", 4001, "A", 0.01),
    RegisterDefinition("ac_output_voltage_v", 4002, "V", 0.1),
    RegisterDefinition("ac_output_current_a", 4003, "A", 0.01, signed=True),
    RegisterDefinition("ac_output_frequency_hz", 4004, "Hz", 0.01),
    RegisterDefinition("battery_voltage_v", 4005, "V", 0.1),
    RegisterDefinition("inverter_temperature_c", 4006, "C"),
    RegisterDefinition("ac_input_frequency_hz", 4009, "Hz", 0.01),
    RegisterDefinition("grid_l1_voltage_v", 4010, "V", 0.1),
    RegisterDefinition("grid_l2_voltage_v", 4012, "V", 0.1),
    RegisterDefinition("battery_current_a", 4328, "A", 0.1, signed=True),
    RegisterDefinition("pv_voltage_v", 4329, "V", 0.1),
    RegisterDefinition("pv_current_a", 4330, "A", 0.1),
    RegisterDefinition("pv_charger_power_w", 4331, "W"),
    RegisterDefinition("charge_state_code", 4332),
    RegisterDefinition("battery_charge_power_w", 4333, "W"),
    RegisterDefinition("warning_status", 4393),
    RegisterDefinition("fault_code_1", 4398),
    RegisterDefinition("fault_code_2", 4399),
    RegisterDefinition("fault_code_3", 4400),
    RegisterDefinition("fault_code_4", 4401),
    RegisterDefinition("machine_state_code", 4405),
    RegisterDefinition("load_current_a", 4408, "A", 0.1),
    RegisterDefinition("load_active_power_w", 4409, "W"),
    RegisterDefinition("load_apparent_power_va", 4410, "VA"),
)

COMMON_PROFILE_BLOCKS = (
    (4000, 13),
    (4328, 6),
    (4393, 1),
    (4398, 4),
    (4405, 1),
    (4408, 3),
)


class RenogyXModbusClient:
    def __init__(self, settings: RenogyXSerialSettings):
        self.settings = settings

    @property
    def connection_description(self) -> str:
        return (
            f"serial {self.settings.port} at {self.settings.baudrate} "
            f"8{self.settings.parity.upper()}1"
        )

    @property
    def troubleshooting_hint(self) -> str:
        return (
            "Verify the external COM/logger RS485 pair is connected, the Wi-Fi "
            "logger is disconnected, and the meter/BMS ports are not being used "
            "for telemetry"
        )

    def close(self) -> None:
        # Serial connections are scoped to individual read operations.
        return None

    def read_holding_registers(
        self, address: int, start: int, count: int
    ) -> list[int]:
        with self._open_serial() as connection:
            return self._read(connection, address, start, count)

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
        with self._open_serial() as connection:
            return collect_register_ranges(
                lambda start, count: self._read(connection, address, start, count),
                ranges,
                chunk_size=chunk_size,
                continue_on_error=continue_on_error,
                retries=retries,
                retry_delay_seconds=retry_delay_seconds,
                inter_request_delay_seconds=inter_request_delay_seconds,
            )

    def read_common_profile(self, address: int) -> dict[str, object]:
        registers, errors = self.read_ranges(
            address,
            COMMON_PROFILE_BLOCKS,
            continue_on_error=True,
        )
        fields = decode_registers(registers, COMMON_REGISTER_DEFINITIONS)
        return {
            "captured_at": utc_now(),
            "profile": "renogy-inverter-modbus-v1-common",
            "renogy_x_compatibility": "unverified",
            "address": address,
            "serial_port": self.settings.port,
            "baudrate": self.settings.baudrate,
            "fields": fields,
            "assessment": assess_common_profile(fields),
            "read_errors": errors,
        }

    def _read(self, connection, address: int, start: int, count: int) -> list[int]:
        request = build_read_holding_request(address, start, count)
        connection.reset_input_buffer()
        connection.write(request)
        connection.flush()

        header = connection.read(3)
        if len(header) != 3:
            raise TimeoutError(
                f"Timed out waiting for a Modbus response on {self.settings.port}"
            )

        function = header[1]
        if function == (READ_HOLDING_REGISTERS | 0x80):
            trailer = connection.read(2)
            frame = header + trailer
        else:
            byte_count = header[2]
            trailer = connection.read(byte_count + 2)
            frame = header + trailer

        return parse_read_holding_response(
            frame,
            expected_address=address,
            expected_count=count,
        )

    def _open_serial(self):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is required to communicate with the inverter"
            ) from exc

        parity = self.settings.parity.upper()
        if parity not in {"N", "E", "O"}:
            raise ValueError("Serial parity must be N, E, or O")
        return serial.Serial(
            port=self.settings.port,
            baudrate=self.settings.baudrate,
            bytesize=8,
            parity=parity,
            stopbits=1,
            timeout=self.settings.timeout_seconds,
            write_timeout=self.settings.timeout_seconds,
        )


def build_read_holding_request(address: int, start: int, count: int) -> bytes:
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

    frame = bytes([address, READ_HOLDING_REGISTERS])
    frame += start.to_bytes(2, byteorder="big")
    frame += count.to_bytes(2, byteorder="big")
    return append_crc(frame)


def parse_read_holding_response(
    frame: bytes,
    *,
    expected_address: int | None = None,
    expected_count: int | None = None,
) -> list[int]:
    validate_crc(frame)
    if len(frame) < 5:
        raise RenogyXProtocolError("Modbus response is too short")

    address = frame[0]
    function = frame[1]
    if expected_address is not None and address != expected_address:
        raise RenogyXProtocolError(
            f"Unexpected Modbus address {address}; expected {expected_address}"
        )
    if function == (READ_HOLDING_REGISTERS | 0x80):
        if len(frame) != 5:
            raise RenogyXProtocolError("Malformed Modbus exception response")
        raise RenogyXProtocolError(
            f"Inverter rejected the read with Modbus exception {frame[2]}"
        )
    if function != READ_HOLDING_REGISTERS:
        raise RenogyXProtocolError(
            f"Unexpected Modbus function code 0x{function:02x}"
        )

    byte_count = frame[2]
    if byte_count % 2:
        raise RenogyXProtocolError("Holding-register response has an odd byte count")
    if len(frame) != byte_count + 5:
        raise RenogyXProtocolError(
            f"Modbus response length mismatch: got {len(frame)}, "
            f"expected {byte_count + 5}"
        )
    count = byte_count // 2
    if expected_count is not None and count != expected_count:
        raise RenogyXProtocolError(
            f"Inverter returned {count} registers; expected {expected_count}"
        )

    data = frame[3 : 3 + byte_count]
    return [
        int.from_bytes(data[index : index + 2], byteorder="big")
        for index in range(0, len(data), 2)
    ]


def validate_crc(frame: bytes) -> None:
    if len(frame) < 4:
        raise RenogyXProtocolError("Modbus frame is too short for a CRC")
    expected = int.from_bytes(frame[-2:], byteorder="little")
    actual = crc16_modbus(frame[:-2])
    if actual != expected:
        raise RenogyXProtocolError(
            f"CRC mismatch: got 0x{expected:04x}, expected 0x{actual:04x}"
        )


def chunk_register_range(
    start: int, count: int, chunk_size: int = 60
) -> Iterator[tuple[int, int]]:
    if not 0 <= start <= 0xFFFF:
        raise ValueError("Register start address must fit in 16 bits")
    if count < 1 or start + count > 0x10000:
        raise ValueError("Register range is invalid")
    if not 1 <= chunk_size <= MAX_READ_REGISTERS:
        raise ValueError(
            f"Chunk size must be between 1 and {MAX_READ_REGISTERS}"
        )

    current = start
    remaining = count
    while remaining:
        size = min(remaining, chunk_size)
        yield current, size
        current += size
        remaining -= size


def collect_register_ranges(
    read: Callable[[int, int], list[int]],
    ranges: Iterable[tuple[int, int]],
    *,
    chunk_size: int = 60,
    continue_on_error: bool = False,
    retries: int = 0,
    retry_delay_seconds: float = 0.15,
    inter_request_delay_seconds: float = 0.02,
) -> tuple[dict[int, int], list[dict[str, object]]]:
    if not 1 <= chunk_size <= MAX_READ_REGISTERS:
        raise ValueError(f"Chunk size must be between 1 and {MAX_READ_REGISTERS}")
    if retries < 0:
        raise ValueError("Retries cannot be negative")
    if retry_delay_seconds < 0 or inter_request_delay_seconds < 0:
        raise ValueError("Modbus delays cannot be negative")

    registers: dict[int, int] = {}
    errors: list[dict[str, object]] = []
    for range_start, range_count in ranges:
        for start, count in chunk_register_range(
            range_start, range_count, chunk_size
        ):
            values: list[int] | None = None
            last_error: Exception | None = None
            for attempt in range(retries + 1):
                try:
                    values = read(start, count)
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < retries and retry_delay_seconds:
                        time.sleep(retry_delay_seconds)
            if values is None:
                if not continue_on_error and last_error is not None:
                    raise last_error
                errors.append(
                    {
                        "start": start,
                        "count": count,
                        "attempts": retries + 1,
                        "error": str(last_error),
                    }
                )
                continue
            if len(values) != count:
                raise RenogyXProtocolError(
                    f"Read {start}+{count} returned {len(values)} registers"
                )
            registers.update(
                {start + index: value for index, value in enumerate(values)}
            )
            if inter_request_delay_seconds:
                time.sleep(inter_request_delay_seconds)
    return registers, errors


def decode_registers(
    registers: dict[int, int], definitions: Iterable[RegisterDefinition]
) -> dict[str, dict[str, object] | None]:
    decoded: dict[str, dict[str, object] | None] = {}
    for definition in definitions:
        raw = registers.get(definition.address)
        if raw is None or raw == UNDEFINED_REGISTER:
            decoded[definition.name] = None
            continue
        numeric = signed_16(raw) if definition.signed else raw
        value: int | float = numeric * definition.scale
        if definition.scale != 1.0:
            value = round(float(value), 4)
        decoded[definition.name] = {
            "address": definition.address,
            "raw": raw,
            "value": value,
            "unit": definition.unit,
        }
    return decoded


def assess_common_profile(
    fields: dict[str, dict[str, object] | None]
) -> dict[str, object]:
    populated = sum(value is not None for value in fields.values())
    reasons: list[str] = []
    plausible = True

    checks = (
        ("battery_voltage_v", 20.0, 70.0),
        ("ac_input_voltage_v", 0.0, 300.0),
        ("ac_output_voltage_v", 0.0, 300.0),
        ("grid_l1_voltage_v", 0.0, 160.0),
        ("grid_l2_voltage_v", 0.0, 160.0),
        ("ac_input_frequency_hz", 0.0, 70.0),
        ("ac_output_frequency_hz", 0.0, 70.0),
    )
    for name, minimum, maximum in checks:
        field = fields.get(name)
        if not field:
            continue
        value = field.get("value")
        if isinstance(value, (int, float)) and not minimum <= value <= maximum:
            plausible = False
            reasons.append(f"{name}={value} is outside {minimum}..{maximum}")

    if populated == 0:
        status = "no_common_registers"
    elif not plausible:
        status = "implausible_values"
    else:
        status = "common_registers_responded"
        reasons.append(
            "Response is plausible, but this profile has no Renogy X-specific "
            "signed grid-power or per-MPPT register definitions."
        )
    return {"status": status, "populated_field_count": populated, "notes": reasons}


def signed_16(value: int) -> int:
    if not 0 <= value <= 0xFFFF:
        raise ValueError("Value must fit in 16 bits")
    return value - 0x10000 if value & 0x8000 else value


def describe_modbus_frame(frame: bytes) -> dict[str, object]:
    result: dict[str, object] = {
        "captured_at": utc_now(),
        "hex": frame.hex(" "),
        "length": len(frame),
        "crc_valid": False,
        "kind": "unknown",
    }
    try:
        validate_crc(frame)
    except RenogyXProtocolError as exc:
        result["error"] = str(exc)
        return result

    result["crc_valid"] = True
    if len(frame) < 2:
        return result
    result["address"] = frame[0]
    result["function"] = frame[1]

    if len(frame) == 8 and frame[1] == READ_HOLDING_REGISTERS:
        result.update(
            {
                "kind": "read_request",
                "start": int.from_bytes(frame[2:4], "big"),
                "count": int.from_bytes(frame[4:6], "big"),
            }
        )
    elif len(frame) >= 5 and frame[1] == READ_HOLDING_REGISTERS:
        byte_count = frame[2]
        if len(frame) == byte_count + 5 and byte_count % 2 == 0:
            result["kind"] = "read_response"
            result["register_count"] = byte_count // 2
            result["values"] = [
                int.from_bytes(frame[index : index + 2], "big")
                for index in range(3, 3 + byte_count, 2)
            ]
    elif len(frame) == 5 and frame[1] & 0x80:
        result["kind"] = "exception_response"
        result["exception_code"] = frame[2]
    return result


def capture_modbus_frames(
    settings: RenogyXSerialSettings,
    *,
    duration_seconds: float,
    silence_seconds: float | None = None,
) -> Iterator[bytes]:
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required to capture inverter traffic") from exc

    parity = settings.parity.upper()
    if parity not in {"N", "E", "O"}:
        raise ValueError("Serial parity must be N, E, or O")

    # Modbus RTU frames are separated by at least 3.5 character times. Use a
    # wider floor for USB serial buffering while keeping individual frames apart.
    frame_silence = silence_seconds or max(0.012, 44.0 / settings.baudrate)
    deadline = time.monotonic() + duration_seconds
    buffer = bytearray()
    last_byte_at: float | None = None

    with serial.Serial(
        port=settings.port,
        baudrate=settings.baudrate,
        bytesize=8,
        parity=parity,
        stopbits=1,
        timeout=min(frame_silence / 2, 0.02),
    ) as connection:
        while time.monotonic() < deadline:
            waiting = connection.in_waiting
            chunk = connection.read(waiting or 1)
            now = time.monotonic()
            if chunk:
                buffer.extend(chunk)
                last_byte_at = now
                continue
            if buffer and last_byte_at is not None and now - last_byte_at >= frame_silence:
                yield bytes(buffer)
                buffer.clear()
                last_byte_at = None

    if buffer:
        yield bytes(buffer)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
