from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import BatteryReading

READ_FUNCTION = 0x78
PACK_STATUS_START = 0x1000
PACK_STATUS_END = 0x10A0
MAX_DATA_LENGTH = 512
MAX_CELL_COUNT = 64
MAX_TEMPERATURE_COUNT = 16

LEVEL2_FAULT_BITS = {
    0: "cell_over_voltage",
    1: "cell_under_voltage",
    2: "pack_over_voltage",
    3: "pack_under_voltage",
    4: "charge_over_current_slow",
    5: "charge_over_current_fast",
    6: "discharge_over_current_slow",
    7: "discharge_over_current_fast",
    8: "charge_high_temperature",
    9: "charge_low_temperature",
    10: "discharge_high_temperature",
    11: "discharge_low_temperature",
    12: "mos_high_temperature",
    13: "ambient_high_temperature",
    14: "ambient_low_temperature",
    15: "cell_voltage_delta_high",
    16: "temperature_delta_high",
    17: "soc_too_low",
    18: "short_circuit",
    19: "cell_offline",
    20: "temperature_sensor_failure",
    21: "charge_mos_fault",
    22: "discharge_mos_fault",
    23: "current_limiting_anomaly",
    24: "aerosol_fault",
    25: "full_charge_protection",
    26: "afe_communication_abnormal",
    27: "reverse_protection",
}

LEVEL1_ALARM_BITS = {
    0: "cell_over_voltage",
    1: "cell_under_voltage",
    2: "pack_over_voltage",
    3: "pack_under_voltage",
    4: "charge_over_current",
    5: "discharge_over_current",
    6: "charge_high_temperature",
    7: "charge_low_temperature",
    8: "discharge_high_temperature",
    9: "discharge_low_temperature",
    10: "mos_high_temperature",
    11: "ambient_high_temperature",
    12: "ambient_low_temperature",
    13: "cell_voltage_delta_high",
    14: "temperature_delta_high",
    15: "soc_too_low",
    16: "eeprom_fault",
    17: "rtc_abnormal",
    18: "full_charge_protection",
}

MOSFET_STATE_BITS = {
    0: "discharge",
    1: "charge",
    2: "precharge",
    3: "heat",
    4: "fan",
    5: "dry_contact_1",
    6: "dry_contact_2",
    7: "current_limiting",
}

PORT_STATE_BITS = {
    0: "charger_connected",
    1: "load_connected",
    2: "switch_on",
}

OPERATION_STATUS = {
    0: "idle",
    1: "charging",
    2: "discharging",
}

CAN_PROTOCOLS = {
    0: "pylon",
    1: "growatt",
    2: "goodwe",
    3: "sofar",
    4: "victron",
    5: "voltronic",
    6: "lxp",
    7: "deye",
    8: "ginlong",
    9: "sma",
    10: "vmii",
    11: "srne",
    12: "invt",
    13: "soroups",
    14: "must",
    15: "aiswei",
}

RS485_PROTOCOLS = {
    0: "pylon",
    1: "growatt",
    2: "voltronic",
    3: "lxp",
    4: "deye",
    5: "invt",
    6: "srne",
    7: "iy-power",
    8: "smk",
    9: "pace",
    10: "hnjd",
    11: "sako",
    12: "ext-06",
    13: "ext-07",
    14: "ext-08",
    15: "ext-09",
}


class ProtocolError(Exception):
    """Raised when a BMS frame is malformed or unexpected."""


@dataclass(frozen=True)
class SerialConnectionSettings:
    port: str
    baudrate: int = 9600
    timeout_seconds: float = 2.0


class EcoWorthyModbusClient:
    def __init__(self, settings: SerialConnectionSettings):
        self.settings = settings

    def read_pack_status(self, address: int, battery_id: str) -> BatteryReading:
        request = build_read_request(address, PACK_STATUS_START, PACK_STATUS_END)
        response = self._transact(request)
        return parse_pack_status_response(response, battery_id=battery_id)

    def _transact(self, request: bytes) -> bytes:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required to talk to the battery serial port") from exc

        with serial.Serial(
            port=self.settings.port,
            baudrate=self.settings.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self.settings.timeout_seconds,
            write_timeout=self.settings.timeout_seconds,
        ) as connection:
            connection.reset_input_buffer()
            connection.write(request)
            connection.flush()

            header = connection.read(8)
            if len(header) != 8:
                raise TimeoutError(
                    f"Timed out waiting for response header on {self.settings.port}"
                )

            data_length = int.from_bytes(header[6:8], byteorder="big")
            if data_length > MAX_DATA_LENGTH:
                raise ProtocolError(f"Response data length is too large: {data_length}")

            body = connection.read(data_length + 2)
            if len(body) != data_length + 2:
                raise TimeoutError(
                    f"Timed out waiting for {data_length + 2} response bytes "
                    f"on {self.settings.port}"
                )

            return header + body


def build_read_request(address: int, start: int, end: int) -> bytes:
    if not 0 <= address <= 0xFF:
        raise ValueError("Battery address must fit in one byte")
    frame = bytes([address, READ_FUNCTION])
    frame += start.to_bytes(2, byteorder="big")
    frame += end.to_bytes(2, byteorder="big")
    frame += (0).to_bytes(2, byteorder="big")
    return append_crc(frame)


def append_crc(frame: bytes) -> bytes:
    crc = crc16_modbus(frame)
    return frame + crc.to_bytes(2, byteorder="little")


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def parse_pack_status_response(frame: bytes, battery_id: str | None = None) -> BatteryReading:
    _validate_frame(frame)
    address = frame[0]
    function = frame[1]
    start = _u16_abs(frame, 2)
    end = _u16_abs(frame, 4)
    data_length = _u16_abs(frame, 6)

    if function != READ_FUNCTION:
        raise ProtocolError(f"Unexpected function code: 0x{function:02x}")
    if start != PACK_STATUS_START:
        raise ProtocolError(f"Unexpected start address: 0x{start:04x}")
    if end != PACK_STATUS_END:
        raise ProtocolError(f"Unexpected end address: 0x{end:04x}")

    data = frame[8 : 8 + data_length]
    view = _StatusView(data)

    cell_count = view.u16(74) or 0
    cell_voltages = []
    for index in range(min(cell_count, MAX_CELL_COUNT)):
        value = view.u16(76 + index * 2)
        if value is None:
            break
        cell_voltages.append(round(value / 1000, 3))

    temperatures_start = 76 + len(cell_voltages) * 2
    temperature_count = view.u16(temperatures_start) or 0
    temperatures = []
    for index in range(min(temperature_count, MAX_TEMPERATURE_COUNT)):
        value = view.u16(temperatures_start + 2 + index * 2)
        if value is None:
            break
        temperatures.append(_temperature_c(value))

    optional_start = temperatures_start + 2 + len(temperatures) * 2
    firmware_raw = view.u16(optional_start + 4)
    pack_bitmask_low = view.u16(optional_start + 38)
    pack_bitmask_high = view.u16(optional_start + 46)
    can_protocol_code = view.u16(optional_start + 42)
    rs485_protocol_code = view.u16(optional_start + 44)

    voltage = _scale(view.u16(8), 100)
    current = _current_a(view.u32(12))
    power = round(voltage * current, 2) if voltage is not None and current is not None else None
    fault_mask = view.u32(32)
    alarm_mask = view.u32(36)
    mosfet_mask = view.u16(40)
    port_state_mask = view.u16(42)
    operation_status_code = view.u16(28)
    high_cell_voltage = _scale(view.u16(48), 1000)
    low_cell_voltage = _scale(view.u16(52), 1000)
    average_cell_voltage = _scale(view.u16(54), 1000)
    cell_delta = (
        round(high_cell_voltage - low_cell_voltage, 3)
        if high_cell_voltage is not None and low_cell_voltage is not None
        else None
    )

    return BatteryReading(
        id=battery_id or f"battery-{address}",
        address=address,
        timestamp=_utc_now(),
        voltage_v=voltage,
        current_a=current,
        power_w=power,
        soc_percent=_scale(view.u16(16), 100),
        remaining_capacity_ah=_scale(view.u16(18), 100),
        full_capacity_ah=_scale(view.u16(20), 100),
        rated_capacity_ah=_scale(view.u16(22), 100),
        soh_percent=view.u16(30),
        cycle_count=view.u16(44),
        operation_status_code=operation_status_code,
        operation_status=OPERATION_STATUS.get(operation_status_code, "unknown"),
        mosfet_state=_bit_names(mosfet_mask, MOSFET_STATE_BITS),
        port_state=_bit_names(port_state_mask, PORT_STATE_BITS),
        fault_code=fault_mask,
        faults=_bit_names(fault_mask, LEVEL2_FAULT_BITS),
        alarm_code=alarm_mask,
        alarms=_bit_names(alarm_mask, LEVEL1_ALARM_BITS),
        mosfet_temperature_c=_temperature_c_optional(view.u16(24)),
        ambient_temperature_c=_temperature_c_optional(view.u16(26)),
        high_cell_number=view.u16(46),
        high_cell_voltage_v=high_cell_voltage,
        low_cell_number=view.u16(50),
        low_cell_voltage_v=low_cell_voltage,
        average_cell_voltage_v=average_cell_voltage,
        cell_voltage_delta_v=cell_delta,
        high_temperature_sensor_number=view.u16(56),
        high_temperature_c=_temperature_c_optional(view.u16(58)),
        low_temperature_sensor_number=view.u16(60),
        low_temperature_c=_temperature_c_optional(view.u16(62)),
        average_temperature_c=_temperature_c_optional(view.u16(64)),
        charge_voltage_limit_v=_scale(view.u16(66), 10),
        charge_current_limit_a=_scale(view.u16(68), 10),
        discharge_voltage_limit_v=_scale(view.u16(70), 10),
        discharge_current_limit_a=_scale(view.u16(72), 10),
        cell_count=cell_count,
        cell_voltages_v=cell_voltages,
        temperature_sensor_count=temperature_count,
        temperatures_c=temperatures,
        balance_status_mask=view.u16(optional_start + 2),
        firmware_version=_firmware_version(firmware_raw),
        serial_number=view.ascii_field(optional_start + 6, 30),
        parallel_pack_count=view.u16(optional_start + 36),
        available_pack_addresses=_pack_addresses(pack_bitmask_low, pack_bitmask_high),
        can_protocol_code=can_protocol_code,
        can_protocol=CAN_PROTOCOLS.get(can_protocol_code),
        rs485_protocol_code=rs485_protocol_code,
        rs485_protocol=RS485_PROTOCOLS.get(rs485_protocol_code),
    )


def _validate_frame(frame: bytes) -> None:
    if len(frame) < 10:
        raise ProtocolError("Response frame is too short")
    data_length = _u16_abs(frame, 6)
    expected_length = 8 + data_length + 2
    if len(frame) != expected_length:
        raise ProtocolError(
            f"Response frame length mismatch: got {len(frame)}, expected {expected_length}"
        )
    expected_crc = int.from_bytes(frame[-2:], byteorder="little")
    actual_crc = crc16_modbus(frame[:-2])
    if actual_crc != expected_crc:
        raise ProtocolError(
            f"CRC mismatch: got 0x{expected_crc:04x}, expected 0x{actual_crc:04x}"
        )


def _u16_abs(frame: bytes, offset: int) -> int:
    return int.from_bytes(frame[offset : offset + 2], byteorder="big")


class _StatusView:
    def __init__(self, data: bytes):
        self.data = data

    def u16(self, full_frame_offset: int) -> int | None:
        offset = full_frame_offset - 8
        if offset < 0 or offset + 2 > len(self.data):
            return None
        return int.from_bytes(self.data[offset : offset + 2], byteorder="big")

    def u32(self, full_frame_offset: int) -> int | None:
        offset = full_frame_offset - 8
        if offset < 0 or offset + 4 > len(self.data):
            return None
        return int.from_bytes(self.data[offset : offset + 4], byteorder="big")

    def ascii_field(self, full_frame_offset: int, length: int) -> str | None:
        offset = full_frame_offset - 8
        if offset < 0 or offset + length > len(self.data):
            return None
        value = self.data[offset : offset + length]
        decoded = value.decode("ascii", errors="ignore").strip("\x00 ")
        return decoded or None


def _scale(value: int | None, divisor: int) -> float | None:
    return round(value / divisor, 3) if value is not None else None


def _current_a(value: int | None) -> float | None:
    return round((value - 300000) / 100, 3) if value is not None else None


def _temperature_c(value: int) -> float:
    return round((value - 500) / 10, 1)


def _temperature_c_optional(value: int | None) -> float | None:
    return _temperature_c(value) if value is not None else None


def _bit_names(mask: int | None, names: dict[int, str]) -> list[str]:
    if mask is None:
        return []
    return [name for bit, name in names.items() if mask & (1 << bit)]


def _firmware_version(value: int | None) -> str | None:
    if value is None:
        return None
    return f"{value >> 8}.{value & 0xFF}"


def _pack_addresses(low: int | None, high: int | None) -> list[int]:
    if low is None and high is None:
        return []
    mask = (low or 0) | ((high or 0) << 16)
    return [index + 1 for index in range(32) if mask & (1 << index)]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
