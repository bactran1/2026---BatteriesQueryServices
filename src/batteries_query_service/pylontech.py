"""Read-only driver for a battery that answers the Pylontech RS485 protocol.

The first-generation Eco-worthy 51.2 V 314 Ah floor-standing unit carries a
PACE BMS whose RS485 port is set to the Pylontech protocol. Every frame and
field offset here was checked against that unit's own replies (address 2,
protocol version 0x20) rather than against documentation alone; the probe in
``pylontech_probe`` is how those replies were collected.

Frames are ASCII: ``~ VER ADR CID1 CID2 LENGTH INFO CHKSUM \\r``. VER is the
protocol version byte, ADR the pack address, CID1 0x46 for a battery, CID2 the
command, LENGTH a 4-bit checksum over the 12-bit INFO length, and CHKSUM the
two's complement of the ASCII sum of everything between ``~`` and itself. A
reply has the same shape with a return code where the command was.

Only read commands are issued: analog values (0x42), alarm status (0x44),
charge and discharge management (0x92), manufacturer info (0x51) and serial
number (0x93). There is no write path.

Units, as this firmware reports them: cell voltages in mV, pack voltage in mV,
temperatures in 0.1 K, capacities in 10 mAh (the 314 Ah total arrives as
31400), current in 0.1 A with charge positive. The current unit follows the
charge and discharge limits the same firmware reports in 0x47 and 0x92 (210 A
and 195 A), which only make sense in 0.1 A.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import BatteryReading

SOI = b"~"
EOI = b"\r"
CID1_BATTERY = 0x46
PROTOCOL_VERSION = 0x20
MAX_FRAME_BYTES = 4096

CMD_ANALOG_VALUES = 0x42
CMD_ALARM_INFO = 0x44
CMD_SYSTEM_PARAMETERS = 0x47
CMD_PROTOCOL_VERSION = 0x4F
CMD_MANUFACTURER_INFO = 0x51
CMD_MANAGEMENT_INFO = 0x92
CMD_SERIAL_NUMBER = 0x93

RETURN_CODES = {
    0x00: "ok",
    0x01: "version error",
    0x02: "checksum error",
    0x03: "length checksum error",
    0x04: "invalid command",
    0x05: "command format error",
    0x06: "invalid data",
    0x90: "address error",
    0x91: "communication error",
}

CURRENT_UNIT_A = 0.1
CAPACITY_UNIT_AH = 0.01
VOLTAGE_UNIT_V = 0.001
IDLE_CURRENT_A = 0.1

# Per-item status codes in the alarm reply.
STATUS_NORMAL = 0x00
STATUS_BELOW_LOWER_LIMIT = 0x01
STATUS_ABOVE_UPPER_LIMIT = 0x02
STATUS_OTHER_ERROR = 0xF0
STATUS_CODES = {STATUS_NORMAL, STATUS_BELOW_LOWER_LIMIT, STATUS_ABOVE_UPPER_LIMIT, STATUS_OTHER_ERROR}

# Pylontech status words 1 and 2, as read from the last five status bytes of
# this unit's alarm reply: on the captured sample they said no protection, both
# MOSFETs on and an effective charge current while the pack charged at 38.6 A.
# Provisional until a sample under discharge confirms the layout.
STATUS1_PROTECTION_BITS = {
    0: "pack_under_voltage",
    1: "charge_high_temperature",
    2: "discharge_high_temperature",
    3: "discharge_over_current",
    5: "charge_over_current",
    6: "cell_under_voltage",
    7: "pack_over_voltage",
}
STATUS2_MOSFET_BITS = {
    0: "battery_module_power",
    1: "discharge",
    2: "charge",
    3: "precharge",
}
STATUS3_CHARGING_EFFECTIVE = 0x80
STATUS3_DISCHARGING_EFFECTIVE = 0x40
STATUS3_FULLY_CHARGED = 0x08

OPERATION_STATUS = {
    0: "idle",
    1: "charging",
    2: "discharging",
}

# Management status byte (0x92): bit 7 charge enabled, bit 6 discharge enabled,
# bits 5 and 4 charge-immediately requests, bit 3 full-charge request.
MANAGEMENT_CHARGE_ENABLED = 0x80
MANAGEMENT_DISCHARGE_ENABLED = 0x40
MANAGEMENT_CHARGE_IMMEDIATELY = 0x20
MANAGEMENT_CHARGE_IMMEDIATELY_2 = 0x10
MANAGEMENT_FULL_CHARGE_REQUEST = 0x08


class ProtocolError(Exception):
    """Raised when a frame is malformed, unexpected or carries an error code."""


class FrameError(ProtocolError):
    """A frame that does not follow the protocol's shape."""


# --- frame primitives ---------------------------------------------------------


def length_field(info_hex: str) -> str:
    """LENGTH: a 4-bit checksum over the three nibbles of the 12-bit INFO length."""
    length = len(info_hex)
    if length > 0xFFF:
        raise ValueError("INFO is too long for a 12-bit length")
    nibble_sum = (length & 0xF) + ((length >> 4) & 0xF) + ((length >> 8) & 0xF)
    check = (~nibble_sum + 1) & 0xF
    return f"{check:X}{length:03X}"


def checksum(body: str) -> str:
    """CHKSUM: two's complement of the ASCII sum of everything between ~ and itself."""
    total = sum(body.encode("ascii"))
    return f"{(~total + 1) & 0xFFFF:04X}"


def build_frame(version: int, address: int, cid2: int, info_hex: str = "") -> bytes:
    """A request frame; the same shape serves a reply when cid2 is its return code."""
    for name, value in (("version", version), ("address", address), ("cid2", cid2)):
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{name} must fit in one byte")
    info_hex = info_hex.upper()
    if len(info_hex) % 2 or any(char not in "0123456789ABCDEF" for char in info_hex):
        raise ValueError("INFO must be an even number of hex characters")
    body = f"{version:02X}{address:02X}{CID1_BATTERY:02X}{cid2:02X}{length_field(info_hex)}{info_hex}"
    return SOI + body.encode("ascii") + checksum(body).encode("ascii") + EOI


def build_request(version: int, address: int, cid2: int, carries_address: bool) -> bytes:
    return build_frame(version, address, cid2, f"{address:02X}" if carries_address else "")


@dataclass(frozen=True)
class Frame:
    version: int
    address: int
    cid1: int
    code: int
    info_hex: str
    checksum_ok: bool
    length_ok: bool

    @property
    def return_code(self) -> str:
        return RETURN_CODES.get(self.code, f"unknown 0x{self.code:02X}")

    @property
    def info(self) -> bytes:
        return bytes.fromhex(self.info_hex)


def parse_frame(raw: bytes) -> Frame:
    """Split a reply into its fields, checking both checksums but keeping the data."""
    if not raw.startswith(SOI) or not raw.endswith(EOI):
        raise FrameError("frame must start with ~ and end with CR")
    try:
        text = raw[1:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise FrameError("frame is not ASCII") from exc
    if len(text) < 16:
        raise FrameError("frame is too short for its header")
    body, received = text[:-4], text[-4:]
    try:
        version = int(body[0:2], 16)
        address = int(body[2:4], 16)
        cid1 = int(body[4:6], 16)
        code = int(body[6:8], 16)
        length = int(body[8:12], 16)
    except ValueError as exc:
        raise FrameError("frame header is not hex") from exc
    info_hex = body[12:]
    if len(info_hex) % 2 or any(char not in "0123456789abcdefABCDEF" for char in info_hex):
        raise FrameError("frame INFO is not hex")
    declared = length & 0xFFF
    return Frame(
        version=version,
        address=address,
        cid1=cid1,
        code=code,
        info_hex=info_hex,
        checksum_ok=checksum(body) == received.upper(),
        length_ok=declared == len(info_hex) and length_field(info_hex) == body[8:12].upper(),
    )


# --- reply layouts --------------------------------------------------------------


class _Cursor:
    """Sequential big-endian reads over an INFO payload with bounds checking."""

    def __init__(self, data: bytes, what: str) -> None:
        self.data = data
        self.offset = 0
        self.what = what

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.take(2), byteorder="big")

    def s16(self) -> int:
        return int.from_bytes(self.take(2), byteorder="big", signed=True)

    def take(self, count: int) -> bytes:
        if self.offset + count > len(self.data):
            raise ProtocolError(
                f"{self.what} reply is too short: needed {self.offset + count} bytes, "
                f"got {len(self.data)}"
            )
        chunk = self.data[self.offset : self.offset + count]
        self.offset += count
        return chunk

    @property
    def remaining(self) -> bytes:
        return self.data[self.offset :]


@dataclass(frozen=True)
class AnalogValues:
    pack: int
    cell_voltages_v: list[float]
    temperatures_c: list[float]
    current_a: float
    voltage_v: float
    remaining_capacity_ah: float
    full_capacity_ah: float | None
    cycle_count: int | None


def parse_analog_values(info: bytes) -> AnalogValues:
    """0x42: INFOFLAG, pack, M cells (mV), N temperatures (0.1 K), current, voltage,
    remaining capacity, then a user-defined count followed by total capacity and
    cycle count when it is 2 or more."""
    cursor = _Cursor(info, "analog values")
    cursor.u8()  # INFOFLAG
    pack = cursor.u8()
    cell_count = cursor.u8()
    cells = [round(cursor.u16() * VOLTAGE_UNIT_V, 3) for _ in range(cell_count)]
    temperature_count = cursor.u8()
    temperatures = [_kelvin_tenths_to_c(cursor.u16()) for _ in range(temperature_count)]
    current = round(cursor.s16() * CURRENT_UNIT_A, 1)
    voltage = round(cursor.u16() * VOLTAGE_UNIT_V, 3)
    remaining = round(cursor.u16() * CAPACITY_UNIT_AH, 2)
    user_defined = cursor.u8()
    total = round(cursor.u16() * CAPACITY_UNIT_AH, 2) if user_defined >= 1 else None
    cycles = cursor.u16() if user_defined >= 2 else None
    return AnalogValues(
        pack=pack,
        cell_voltages_v=cells,
        temperatures_c=temperatures,
        current_a=current,
        voltage_v=voltage,
        remaining_capacity_ah=remaining,
        full_capacity_ah=total,
        cycle_count=cycles,
    )


@dataclass(frozen=True)
class AlarmInfo:
    pack: int
    cell_status: list[int]
    temperature_status: list[int]
    charge_current_status: int
    voltage_status: int
    discharge_current_status: int
    status_bytes: bytes

    @property
    def status_words(self) -> bytes:
        """Pylontech status words 1 to 5, the last five status bytes."""
        return self.status_bytes[-5:] if len(self.status_bytes) >= 5 else b""

    @property
    def faults(self) -> list[str]:
        words = self.status_words
        return _bit_names(words[0], STATUS1_PROTECTION_BITS) if words else []

    @property
    def mosfet_state(self) -> list[str] | None:
        words = self.status_words
        return _bit_names(words[1], STATUS2_MOSFET_BITS) if len(words) > 1 else None

    @property
    def alarms(self) -> list[str]:
        names: list[str] = []
        for index, code in enumerate(self.cell_status, start=1):
            if code == STATUS_BELOW_LOWER_LIMIT:
                names.append(f"cell_{index}_under_voltage")
            elif code == STATUS_ABOVE_UPPER_LIMIT:
                names.append(f"cell_{index}_over_voltage")
            elif code == STATUS_OTHER_ERROR:
                names.append(f"cell_{index}_fault")
        for index, code in enumerate(self.temperature_status, start=1):
            if code == STATUS_BELOW_LOWER_LIMIT:
                names.append(f"temperature_{index}_low")
            elif code == STATUS_ABOVE_UPPER_LIMIT:
                names.append(f"temperature_{index}_high")
            elif code == STATUS_OTHER_ERROR:
                names.append(f"temperature_{index}_sensor_failure")
        if self.charge_current_status == STATUS_ABOVE_UPPER_LIMIT:
            names.append("charge_over_current")
        elif self.charge_current_status == STATUS_OTHER_ERROR:
            names.append("charge_current_fault")
        if self.voltage_status == STATUS_BELOW_LOWER_LIMIT:
            names.append("pack_under_voltage")
        elif self.voltage_status == STATUS_ABOVE_UPPER_LIMIT:
            names.append("pack_over_voltage")
        elif self.voltage_status == STATUS_OTHER_ERROR:
            names.append("pack_voltage_fault")
        if self.discharge_current_status == STATUS_ABOVE_UPPER_LIMIT:
            names.append("discharge_over_current")
        elif self.discharge_current_status == STATUS_OTHER_ERROR:
            names.append("discharge_current_fault")
        return names


def parse_alarm_info(info: bytes) -> AlarmInfo:
    """0x44: INFOFLAG, pack, M cell statuses, N temperature statuses, then the
    charge current, pack voltage and discharge current statuses and the status
    words.

    Pylontech documents three item statuses followed by five status words. This
    unit sends ten bytes there (00 06 00 00 00 00 06 80 00 00 on the captured
    sample), and the 06 in the second place is no status code, so the three
    item statuses are taken from the first run of three valid codes in the
    first five bytes and the last five bytes are read as the status words. All
    ten are kept raw in ``status_bytes`` either way.
    """
    cursor = _Cursor(info, "alarm info")
    cursor.u8()  # INFOFLAG
    pack = cursor.u8()
    cell_count = cursor.u8()
    cells = [cursor.u8() for _ in range(cell_count)]
    temperature_count = cursor.u8()
    temperatures = [cursor.u8() for _ in range(temperature_count)]
    trailing = bytes(cursor.remaining)
    if len(trailing) < 3:
        raise ProtocolError("alarm info reply is too short for its item statuses")
    items: tuple[int, int, int] | None = None
    for start in range(0, min(3, len(trailing) - 2)):
        window = trailing[start : start + 3]
        if all(code in STATUS_CODES for code in window):
            items = (window[0], window[1], window[2])
            break
    if items is None:
        items = (trailing[0], trailing[1], trailing[2])
    return AlarmInfo(
        pack=pack,
        cell_status=cells,
        temperature_status=temperatures,
        charge_current_status=items[0],
        voltage_status=items[1],
        discharge_current_status=items[2],
        status_bytes=trailing,
    )


@dataclass(frozen=True)
class ManagementInfo:
    pack: int
    charge_voltage_limit_v: float
    discharge_voltage_limit_v: float
    charge_current_limit_a: float
    discharge_current_limit_a: float
    status: int

    @property
    def charge_enabled(self) -> bool:
        return bool(self.status & MANAGEMENT_CHARGE_ENABLED)

    @property
    def discharge_enabled(self) -> bool:
        return bool(self.status & MANAGEMENT_DISCHARGE_ENABLED)

    @property
    def charge_immediately(self) -> bool:
        return bool(self.status & (MANAGEMENT_CHARGE_IMMEDIATELY | MANAGEMENT_CHARGE_IMMEDIATELY_2))

    @property
    def full_charge_requested(self) -> bool:
        return bool(self.status & MANAGEMENT_FULL_CHARGE_REQUEST)


def parse_management_info(info: bytes) -> ManagementInfo:
    """0x92: pack, charge voltage limit (mV), discharge voltage limit (mV), charge
    current limit (0.1 A), discharge current limit (0.1 A), status byte."""
    cursor = _Cursor(info, "management info")
    pack = cursor.u8()
    charge_voltage = round(cursor.u16() * VOLTAGE_UNIT_V, 3)
    discharge_voltage = round(cursor.u16() * VOLTAGE_UNIT_V, 3)
    charge_current = round(cursor.u16() * CURRENT_UNIT_A, 1)
    discharge_current = round(cursor.u16() * CURRENT_UNIT_A, 1)
    status = cursor.u8()
    return ManagementInfo(
        pack=pack,
        charge_voltage_limit_v=charge_voltage,
        discharge_voltage_limit_v=discharge_voltage,
        charge_current_limit_a=charge_current,
        discharge_current_limit_a=discharge_current,
        status=status,
    )


@dataclass(frozen=True)
class ManufacturerInfo:
    device_name: str | None
    software_version: str | None
    manufacturer: str | None


def parse_manufacturer_info(info: bytes) -> ManufacturerInfo:
    """0x51: device name (10 ASCII bytes), software version (2 bytes), manufacturer
    (20 ASCII bytes). This unit answers "48100-9538", 1.0 and "ShenZhen PACE"."""
    cursor = _Cursor(info, "manufacturer info")
    device_name = _ascii(cursor.take(10))
    major, minor = cursor.take(2)
    manufacturer = _ascii(cursor.take(20)) if len(cursor.remaining) >= 20 else _ascii(cursor.remaining)
    return ManufacturerInfo(
        device_name=device_name,
        software_version=f"{major}.{minor}",
        manufacturer=manufacturer,
    )


def parse_serial_number(info: bytes) -> str | None:
    """0x93: pack, then the serial number as ASCII; blank on this unit."""
    cursor = _Cursor(info, "serial number")
    cursor.u8()
    return _ascii(cursor.remaining)


# --- reading assembly -------------------------------------------------------------


def build_reading(
    battery_id: str,
    address: int,
    analog: AnalogValues,
    alarms: AlarmInfo | None = None,
    management: ManagementInfo | None = None,
    manufacturer: ManufacturerInfo | None = None,
    serial_number: str | None = None,
) -> BatteryReading:
    """Fold the replies into the collector's common battery reading.

    The first temperature is the BMS board's (the warm one), the rest sit on the
    cells, so the board reading becomes the MOSFET temperature and the cell
    sensors drive the high, low and average figures. Operation status follows the
    sign of the current. MOSFET state is what the management reply says is
    enabled, which is as close as this protocol gets to the switch positions.
    """
    cells = analog.cell_voltages_v
    high_cell = max(range(len(cells)), key=cells.__getitem__) if cells else None
    low_cell = min(range(len(cells)), key=cells.__getitem__) if cells else None
    cell_temperatures = analog.temperatures_c[1:] if len(analog.temperatures_c) > 1 else analog.temperatures_c
    high_temperature = max(range(len(cell_temperatures)), key=cell_temperatures.__getitem__) if cell_temperatures else None
    low_temperature = min(range(len(cell_temperatures)), key=cell_temperatures.__getitem__) if cell_temperatures else None
    sensor_offset = 2 if len(analog.temperatures_c) > 1 else 1

    current = analog.current_a
    if current > IDLE_CURRENT_A:
        operation_code = 1
    elif current < -IDLE_CURRENT_A:
        operation_code = 2
    else:
        operation_code = 0

    full = analog.full_capacity_ah
    soc = round(100 * analog.remaining_capacity_ah / full, 1) if full else None
    mosfet_state = alarms.mosfet_state if alarms is not None else None
    if mosfet_state is None:
        mosfet_state = []
        if management is not None:
            if management.charge_enabled:
                mosfet_state.append("charge")
            if management.discharge_enabled:
                mosfet_state.append("discharge")
    alarm_names = alarms.alarms if alarms is not None else []
    fault_names = alarms.faults if alarms is not None else []

    return BatteryReading(
        id=battery_id,
        address=address,
        timestamp=_utc_now(),
        voltage_v=analog.voltage_v,
        current_a=current,
        power_w=round(analog.voltage_v * current, 2),
        soc_percent=soc,
        remaining_capacity_ah=analog.remaining_capacity_ah,
        full_capacity_ah=full,
        rated_capacity_ah=None,
        soh_percent=None,
        cycle_count=analog.cycle_count,
        operation_status_code=operation_code,
        operation_status=OPERATION_STATUS[operation_code],
        mosfet_state=mosfet_state,
        port_state=[],
        fault_code=alarms.status_words[0] if alarms is not None and alarms.status_words else None,
        faults=fault_names,
        alarm_code=len(alarm_names) if alarms is not None else None,
        alarms=alarm_names,
        mosfet_temperature_c=analog.temperatures_c[0] if len(analog.temperatures_c) > 1 else None,
        ambient_temperature_c=None,
        high_cell_number=high_cell + 1 if high_cell is not None else None,
        high_cell_voltage_v=cells[high_cell] if high_cell is not None else None,
        low_cell_number=low_cell + 1 if low_cell is not None else None,
        low_cell_voltage_v=cells[low_cell] if low_cell is not None else None,
        average_cell_voltage_v=round(sum(cells) / len(cells), 3) if cells else None,
        cell_voltage_delta_v=round(cells[high_cell] - cells[low_cell], 3) if high_cell is not None else None,
        high_temperature_sensor_number=high_temperature + sensor_offset if high_temperature is not None else None,
        high_temperature_c=cell_temperatures[high_temperature] if high_temperature is not None else None,
        low_temperature_sensor_number=low_temperature + sensor_offset if low_temperature is not None else None,
        low_temperature_c=cell_temperatures[low_temperature] if low_temperature is not None else None,
        average_temperature_c=round(sum(cell_temperatures) / len(cell_temperatures), 1) if cell_temperatures else None,
        charge_voltage_limit_v=management.charge_voltage_limit_v if management else None,
        charge_current_limit_a=management.charge_current_limit_a if management else None,
        discharge_voltage_limit_v=management.discharge_voltage_limit_v if management else None,
        discharge_current_limit_a=management.discharge_current_limit_a if management else None,
        cell_count=len(cells),
        cell_voltages_v=cells,
        temperature_sensor_count=len(analog.temperatures_c),
        temperatures_c=analog.temperatures_c,
        balance_status_mask=None,
        firmware_version=manufacturer.software_version if manufacturer else None,
        serial_number=serial_number,
        parallel_pack_count=None,
        available_pack_addresses=[],
        can_protocol_code=None,
        can_protocol=None,
        rs485_protocol_code=None,
        rs485_protocol="pylontech",
        bms_model=manufacturer.device_name if manufacturer else None,
        bms_vendor=manufacturer.manufacturer if manufacturer else None,
        status_bytes_hex=alarms.status_bytes.hex() if alarms is not None else None,
    )


# --- serial client ------------------------------------------------------------------


class PylontechClient:
    """Reads one pack on a serial port with the read commands above.

    The port is opened per read, like the JBD driver, so a stuck adapter never
    pins the collector, and every reply is checked for both checksums, the
    expected address and a zero return code before it is trusted.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    def read_pack_status(self, address: int, battery_id: str) -> BatteryReading:
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
            analog = parse_analog_values(self._query(connection, address, CMD_ANALOG_VALUES, True))
            alarms = _optional(parse_alarm_info, self._query_optional(connection, address, CMD_ALARM_INFO, True))
            management = _optional(
                parse_management_info, self._query_optional(connection, address, CMD_MANAGEMENT_INFO, True)
            )
            manufacturer = _optional(
                parse_manufacturer_info, self._query_optional(connection, address, CMD_MANUFACTURER_INFO, False)
            )
            serial_info = self._query_optional(connection, address, CMD_SERIAL_NUMBER, True)
            serial_number = parse_serial_number(serial_info) if serial_info is not None else None
        return build_reading(battery_id, address, analog, alarms, management, manufacturer, serial_number)

    def _query(self, connection, address: int, cid2: int, carries_address: bool) -> bytes:
        request = build_request(PROTOCOL_VERSION, address, cid2, carries_address)
        raw = self._transact(connection, request)
        if not raw:
            raise TimeoutError(
                f"Timed out waiting for the 0x{cid2:02X} reply from address {address} "
                f"on {self.settings.port}"
            )
        frame = parse_frame(raw)
        if not frame.checksum_ok or not frame.length_ok:
            raise ProtocolError(f"0x{cid2:02X} reply from address {address} failed its checksum")
        if frame.address != address:
            raise ProtocolError(
                f"0x{cid2:02X} reply came from address {frame.address}, expected {address}"
            )
        if frame.code != 0:
            raise ProtocolError(f"0x{cid2:02X} request refused: {frame.return_code}")
        return frame.info

    def _query_optional(self, connection, address: int, cid2: int, carries_address: bool) -> bytes | None:
        """The analog values are the reading; everything else is extra detail that
        must not take the pack offline when a firmware leaves it out."""
        try:
            return self._query(connection, address, cid2, carries_address)
        except (TimeoutError, ProtocolError):
            return None

    @staticmethod
    def _transact(connection, request: bytes) -> bytes:
        connection.reset_input_buffer()
        connection.write(request)
        connection.flush()
        reply = connection.read_until(EOI, MAX_FRAME_BYTES)
        start = reply.find(SOI)
        return reply[start:] if start > 0 else reply


def _optional(parser, info: bytes | None):
    if info is None:
        return None
    try:
        return parser(info)
    except ProtocolError:
        return None


def _kelvin_tenths_to_c(value: int) -> float:
    return round(value / 10 - 273.15, 1)


def _bit_names(mask: int, names: dict[int, str]) -> list[str]:
    return [name for bit, name in names.items() if mask & (1 << bit)]


def _ascii(data: bytes) -> str | None:
    text = data.decode("ascii", errors="ignore").strip("\x00 ")
    return text or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
