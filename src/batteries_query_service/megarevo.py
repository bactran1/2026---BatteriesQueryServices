from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import InverterReading, PvInputReading
from .renogy_x import (
    ModbusRegisterClient,
    UNDEFINED_REGISTER,
    RenogyXModbusClient,
    RenogyXProtocolError,
    RenogyXSerialSettings,
    signed_16,
    utc_now,
)

R8KLNA_PROFILE = "megarevo-r8klna-v2.12-read-only"

SYSTEM_STATES = {
    0: "initializing",
    1: "standby",
    2: "pv_grid",
    3: "battery_grid",
    4: "hybrid_power",
    5: "ac_battery_charging",
    6: "pv_battery_charging",
    7: "bypass",
    8: "fault",
    9: "self_check",
    10: "dsp_firmware_update",
    11: "arm_firmware_update",
    12: "service",
    13: "inverter_test",
    14: "pv_test",
    15: "dcdc_test",
    16: "test_mode",
    17: "undefined",
}

INVERTER_STATES = {
    0: "standby",
    1: "off_grid",
    2: "grid_connected",
    3: "off_grid_phase_locked",
    4: "service",
    5: "open_loop_test",
    6: "closed_loop_test",
    7: "inverter_to_pfc",
}

DCDC_STATES = {
    0: "standby",
    1: "charging",
    2: "discharging",
    3: "service",
    4: "test",
    5: "undefined",
    6: "undefined",
    7: "undefined",
}

DSP_ALARM_1 = (
    "discharge_over_current",
    "overload",
    "battery_disconnected",
    "battery_under_capacity",
    "battery_low_capacity",
    "battery_over_voltage",
    "grid_under_voltage",
    "grid_over_voltage",
    "grid_under_frequency",
    "grid_over_frequency",
    "ground_fault_current",
    "parallel_can_failure",
    "grid_ct_reversed",
    "bus_under_voltage",
    "bus_over_voltage",
    "inverter_over_current",
)

DSP_ALARM_2 = (
    "charge_over_current",
    "meter_communication_failure",
    "inverter_under_voltage",
    "inverter_over_voltage",
    "inverter_frequency_abnormal",
    "igbt_temperature_high",
    "bms_system_error",
    "battery_over_temperature",
    "battery_under_temperature",
    "battery_cell_unbalanced_or_relay_open",
    "battery_reversed",
    "bms_communication_failure",
    "battery_fault",
    "grid_overload",
    "grid_phase_or_line_neutral_reversed",
    "arc_fault",
)

DSP_FAULT_1 = (
    "bus_soft_start_timeout",
    "inverter_soft_start_timeout",
    "bus_short_circuit",
    "inverter_short_circuit",
    "fan_fault",
    "pv_insulation_low",
    "bus_relay_fault",
    "grid_relay_fault",
    "backup_relay_fault",
    "gfci_sensor_fault",
    "internal_sensor_fault",
    "pv_input_short_circuit",
    "bypass_relay_fault",
    "system_fault",
    "inverter_current_dc_component_high",
    "inverter_voltage_dc_component_high",
)

DSP_FAULT_2 = ("mcu_self_test_failed",)

# Megarevo Hybrid Inverter Modbus Protocol V2.12. Every request made by this
# driver is function 0x03 (read holding registers); no write path is provided.
R8KLNA_READ_BLOCKS = (
    (0x1219, 1),  # Protocol version.
    (0x1234, 6),  # Twelve-byte ASCII serial number.
    (0x3100, 0x53),  # Alarm/state, grid, load, PV, battery, and temperatures.
    (0x3153, 0x30),  # Daily and lifetime energy counters through 0x3182.
    (0x3190, 0x0E),  # Inverter-side electrical data through 0x319D.
    (0x31A0, 0x0E),  # Grid detail and external home-load data through 0x31AD.
)

CORE_TELEMETRY_ADDRESSES = (
    0x3110,
    0x3113,
    0x3122,
    0x3126,
    0x3130,
    0x3133,
    0x3136,
    0x3139,
    0x3140,
    0x3145,
)


class MegarevoR8KLNAClient:
    def __init__(
        self,
        settings: RenogyXSerialSettings | None = None,
        *,
        retries: int = 2,
        modbus_client: ModbusRegisterClient | None = None,
    ):
        if retries < 0:
            raise ValueError("Retries cannot be negative")
        if settings is None and modbus_client is None:
            raise ValueError("A serial configuration or Modbus client is required")
        if settings is not None and modbus_client is not None:
            raise ValueError("Specify either serial settings or a Modbus client")
        self.settings = settings
        self.retries = retries
        if settings is not None:
            self._modbus: ModbusRegisterClient = RenogyXModbusClient(settings)
            self.connection_description = (
                f"serial {settings.port} at {settings.baudrate} "
                f"8{settings.parity.upper()}1"
            )
            self.troubleshooting_hint = (
                "Verify the external COM/logger RS485 pair is connected, the "
                "Wi-Fi logger is disconnected, and the meter/BMS ports are not "
                "being used for telemetry"
            )
        else:
            assert modbus_client is not None
            self._modbus = modbus_client
            self.connection_description = modbus_client.connection_description
            self.troubleshooting_hint = modbus_client.troubleshooting_hint

    def close(self) -> None:
        self._modbus.close()

    def read_status(
        self,
        address: int,
        inverter_id: str,
        model: str,
    ) -> InverterReading:
        # V2.12 requires 0x3100-0x3104 to be read as one five-register block.
        # Using it as the probe also limits an unplugged adapter to one timeout.
        try:
            probe = self._modbus.read_holding_registers(address, 0x3100, 5)
        except Exception as exc:
            raise RenogyXProtocolError(
                "No Modbus response from inverter "
                f"address {address} through {self.connection_description} while "
                f"reading 0x3100-0x3104: {exc}. {self.troubleshooting_hint}"
            ) from exc
        registers, errors = self._modbus.read_ranges(
            address,
            R8KLNA_READ_BLOCKS,
            chunk_size=60,
            continue_on_error=True,
            retries=self.retries,
        )
        for offset, value in enumerate(probe):
            registers.setdefault(0x3100 + offset, value)
        return parse_r8klna_registers(
            registers,
            inverter_id=inverter_id,
            address=address,
            model=model,
            read_errors=errors,
        )


def parse_r8klna_registers(
    registers: Mapping[int, int],
    *,
    inverter_id: str,
    address: int,
    model: str,
    read_errors: Iterable[Mapping[str, object]] = (),
) -> InverterReading:
    if not any(_raw(registers, item) is not None for item in CORE_TELEMETRY_ADDRESSES):
        raise RenogyXProtocolError(
            "The inverter returned no usable R8KLNA core telemetry registers"
        )

    grid_l1_voltage = _scaled_u16(registers, 0x3110, 0.1)
    grid_l2_voltage = _scaled_u16(registers, 0x3113, 0.1)
    grid_l1_current = _scaled_s16(registers, 0x3111, 0.1)
    grid_l2_current = _scaled_s16(registers, 0x3114, 0.1)
    grid_l1_power = _scaled_s16(registers, 0x3112)
    grid_l2_power = _scaled_s16(registers, 0x3115)
    grid_total_power = _sum_present(grid_l1_power, grid_l2_power)

    load_l1_power = _scaled_s16(registers, 0x3122)
    load_l2_power = _scaled_s16(registers, 0x3126)
    load_total_power = _sum_present(load_l1_power, load_l2_power)

    home_load_l1_power = _scaled_s16(registers, 0x31A6)
    home_load_l2_power = _scaled_s16(registers, 0x31A7)
    home_load_total_power = _scaled_s16(registers, 0x31A9)
    if home_load_total_power is None:
        home_load_total_power = _sum_present(
            home_load_l1_power, home_load_l2_power
        )

    pv_inputs = [
        PvInputReading(
            channel=channel,
            voltage_v=_scaled_u16(registers, start, 0.1),
            current_a=_scaled_u16(registers, start + 1, 0.1),
            power_w=_scaled_s16(registers, start + 2),
        )
        for channel, start in enumerate((0x3130, 0x3133, 0x3136, 0x3139), start=1)
    ]
    pv_total_power = _sum_present(*(item.power_w for item in pv_inputs))

    battery_voltage = _scaled_s16(
        registers,
        0x3140,
        0.1,
        allow_ffff=False,
    )
    battery_current = _scaled_s16(registers, 0x3141, 0.1)
    battery_power = _scaled_s16(registers, 0x314A)
    if battery_power is None and battery_voltage is not None and battery_current is not None:
        battery_power = round(battery_voltage * battery_current, 1)

    inverter_l1_power = _scaled_s16(registers, 0x3192)
    inverter_l2_power = _scaled_s16(registers, 0x3195)
    dsp_state_word = _raw(registers, 0x3104)
    system_state_code = dsp_state_word & 0x1F if dsp_state_word is not None else None
    inverter_state_code = (
        (dsp_state_word >> 5) & 0x07 if dsp_state_word is not None else None
    )
    dcdc_state_code = (
        (dsp_state_word >> 8) & 0x07 if dsp_state_word is not None else None
    )
    dsp_alarm_words = _word_list(registers, 0x3100, 0x3101)
    dsp_fault_words = _word_list(registers, 0x3102, 0x3103)

    reading = InverterReading(
        id=inverter_id,
        address=address,
        timestamp=utc_now(),
        model=model,
        profile=R8KLNA_PROFILE,
        serial_number=_ascii_registers(registers, 0x1234, 6),
        protocol_version=_protocol_version(_raw(registers, 0x1219)),
        dsp_state_code=dsp_state_word,
        system_state_code=system_state_code,
        system_state=_state_name(SYSTEM_STATES, system_state_code),
        inverter_state_code=inverter_state_code,
        inverter_state=_state_name(INVERTER_STATES, inverter_state_code),
        dcdc_state_code=dcdc_state_code,
        dcdc_state=_state_name(DCDC_STATES, dcdc_state_code),
        battery_charge_enabled=(
            bool(dsp_state_word & (1 << 12))
            if dsp_state_word is not None
            else None
        ),
        battery_discharge_enabled=(
            bool(dsp_state_word & (1 << 13))
            if dsp_state_word is not None
            else None
        ),
        dsp_alarm_words=dsp_alarm_words,
        dsp_fault_words=dsp_fault_words,
        arm_alarm_words=_word_list(registers, 0x3105, 0x3106),
        arm_fault_words=_word_list(registers, 0x3107, 0x3108),
        active_alarms=_decode_register_words(
            registers,
            (0x3100, 0x3101),
            (DSP_ALARM_1, DSP_ALARM_2),
        ),
        active_faults=_decode_register_words(
            registers,
            (0x3102, 0x3103),
            (DSP_FAULT_1, DSP_FAULT_2),
        ),
        bms_alarm_word=_raw(registers, 0x3109),
        bms_protection_word=_raw(registers, 0x310A),
        bms_error_word=_raw(registers, 0x310B),
        grid_l1_voltage_v=grid_l1_voltage,
        grid_l2_voltage_v=grid_l2_voltage,
        grid_l1_current_a=grid_l1_current,
        grid_l2_current_a=grid_l2_current,
        grid_l1_power_w=grid_l1_power,
        grid_l2_power_w=grid_l2_power,
        grid_total_power_w=grid_total_power,
        grid_import_power_w=(
            max(-grid_total_power, 0.0) if grid_total_power is not None else None
        ),
        grid_export_power_w=(
            max(grid_total_power, 0.0) if grid_total_power is not None else None
        ),
        grid_frequency_hz=_scaled_u16(registers, 0x3119, 0.01),
        grid_port_l1_power_w=_scaled_s16(registers, 0x311C),
        grid_port_l2_power_w=_scaled_s16(registers, 0x311D),
        load_l1_voltage_v=_scaled_u16(registers, 0x3120, 0.1),
        load_l2_voltage_v=_scaled_u16(registers, 0x3124, 0.1),
        load_l1_current_a=_scaled_s16(registers, 0x3121, 0.1),
        load_l2_current_a=_scaled_s16(registers, 0x3125, 0.1),
        load_l1_power_w=load_l1_power,
        load_l2_power_w=load_l2_power,
        load_total_power_w=load_total_power,
        home_load_l1_power_w=home_load_l1_power,
        home_load_l2_power_w=home_load_l2_power,
        home_load_total_power_w=home_load_total_power,
        pv_inputs=pv_inputs,
        pv_total_power_w=pv_total_power,
        pv_temperature_c=_scaled_u16(registers, 0x313C),
        battery_voltage_v=battery_voltage,
        battery_current_a=battery_current,
        battery_power_w=battery_power,
        battery_soc_percent=_scaled_u16(registers, 0x3145, 0.1),
        battery_temperature_c=_scaled_s16(registers, 0x3146, 0.1),
        battery_charge_voltage_limit_v=_scaled_u16(registers, 0x3147, 0.1),
        battery_charge_current_limit_a=_scaled_u16(registers, 0x3148, 0.1),
        battery_discharge_current_limit_a=_scaled_u16(registers, 0x3149, 0.1),
        battery_cell_max_voltage_v=_scaled_u16(registers, 0x314B, 0.001),
        battery_cell_min_voltage_v=_scaled_u16(registers, 0x314C, 0.001),
        battery_cell_max_temperature_c=_scaled_s16(registers, 0x314D),
        battery_cell_min_temperature_c=_scaled_s16(registers, 0x314E),
        inverter_l1_voltage_v=_scaled_u16(registers, 0x3190, 0.1),
        inverter_l2_voltage_v=_scaled_u16(registers, 0x3193, 0.1),
        inverter_l1_current_a=_scaled_s16(registers, 0x3191, 0.1),
        inverter_l2_current_a=_scaled_s16(registers, 0x3194, 0.1),
        inverter_l1_power_w=inverter_l1_power,
        inverter_l2_power_w=inverter_l2_power,
        inverter_total_power_w=_sum_present(inverter_l1_power, inverter_l2_power),
        inverter_temperature_c=_scaled_s16(registers, 0x311A),
        internal_temperature_c=_scaled_s16(registers, 0x311B),
        dcdc_temperature_c=_scaled_s16(registers, 0x3152),
        bus_voltage_v=_scaled_u16(registers, 0x319D, 0.1),
        leakage_current_ma=_scaled_u16(registers, 0x319C),
        generator_frequency_hz=_scaled_u16(registers, 0x312C, 0.01),
        generator_l1_voltage_v=_scaled_u16(registers, 0x312D, 0.1),
        generator_l2_voltage_v=_scaled_u16(registers, 0x312E, 0.1),
        pv_energy_today_kwh=_energy_kwh(registers, 0x3153),
        pv_energy_total_kwh=_energy_kwh(registers, 0x3165),
        grid_export_energy_today_kwh=_energy_kwh(registers, 0x3155),
        grid_export_energy_total_kwh=_energy_kwh(registers, 0x3167),
        grid_import_energy_today_kwh=_energy_kwh(registers, 0x316B),
        grid_import_energy_total_kwh=_energy_kwh(registers, 0x317D),
        load_energy_today_kwh=_energy_kwh(registers, 0x3157, signed=True),
        load_energy_total_kwh=_energy_kwh(registers, 0x3169, signed=True),
        battery_charge_energy_today_kwh=_energy_kwh(registers, 0x316D),
        battery_charge_energy_total_kwh=_energy_kwh(registers, 0x317F),
        battery_discharge_energy_today_kwh=_energy_kwh(registers, 0x316F),
        battery_discharge_energy_total_kwh=_energy_kwh(registers, 0x3181),
        read_errors=[dict(error) for error in read_errors],
    )
    _validate_plausibility(reading)
    return reading


def _validate_plausibility(reading: InverterReading) -> None:
    checks = (
        ("grid_l1_voltage_v", reading.grid_l1_voltage_v, 0.0, 300.0),
        ("grid_l2_voltage_v", reading.grid_l2_voltage_v, 0.0, 300.0),
        ("battery_voltage_v", reading.battery_voltage_v, 0.0, 70.0),
        ("battery_soc_percent", reading.battery_soc_percent, 0.0, 100.0),
        ("grid_frequency_hz", reading.grid_frequency_hz, 0.0, 70.0),
    )
    for name, value, minimum, maximum in checks:
        if value is not None and not minimum <= value <= maximum:
            raise RenogyXProtocolError(
                f"Implausible R8KLNA {name}={value}; expected {minimum}..{maximum}"
            )
    for pv_input in reading.pv_inputs:
        if pv_input.voltage_v is not None and not 0.0 <= pv_input.voltage_v <= 600.0:
            raise RenogyXProtocolError(
                f"Implausible PV{pv_input.channel} voltage {pv_input.voltage_v} V"
            )


def _raw(
    registers: Mapping[int, int],
    address: int,
    *,
    allow_ffff: bool = False,
) -> int | None:
    value = registers.get(address)
    if value is None or (value == UNDEFINED_REGISTER and not allow_ffff):
        return None
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"Register 0x{address:04X} does not fit in 16 bits")
    return value


def _scaled_u16(
    registers: Mapping[int, int], address: int, scale: float = 1.0
) -> float | None:
    value = _raw(registers, address)
    return round(value * scale, 4) if value is not None else None


def _scaled_s16(
    registers: Mapping[int, int],
    address: int,
    scale: float = 1.0,
    *,
    allow_ffff: bool = True,
) -> float | None:
    value = _raw(registers, address, allow_ffff=allow_ffff)
    return round(signed_16(value) * scale, 4) if value is not None else None


def _sum_present(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return round(sum(present), 4) if present else None


def _word_list(registers: Mapping[int, int], *addresses: int) -> list[int]:
    return [value for address in addresses if (value := _raw(registers, address)) is not None]


def _u32_cd_ab(registers: Mapping[int, int], address: int) -> int | None:
    low_word = _raw(registers, address)
    high_word = _raw(registers, address + 1)
    if low_word is None or high_word is None:
        return None
    return (high_word << 16) | low_word


def _energy_kwh(
    registers: Mapping[int, int], address: int, *, signed: bool = False
) -> float | None:
    value = _u32_cd_ab(registers, address)
    if value is not None and signed and value & 0x80000000:
        value -= 0x100000000
    return round(value * 0.001, 3) if value is not None else None


def _state_name(states: Mapping[int, str], code: int | None) -> str | None:
    if code is None:
        return None
    return states.get(code, "unknown")


def _decode_register_words(
    registers: Mapping[int, int],
    addresses: tuple[int, ...],
    definitions: tuple[tuple[str, ...], ...],
) -> list[str]:
    active: list[str] = []
    for address, names in zip(addresses, definitions, strict=True):
        word = _raw(registers, address)
        if word is None:
            continue
        for bit, name in enumerate(names):
            if word & (1 << bit):
                active.append(name)
    return active


def _ascii_registers(
    registers: Mapping[int, int], start: int, count: int
) -> str | None:
    words = [_raw(registers, start + offset) for offset in range(count)]
    if any(word is None for word in words):
        return None
    payload = b"".join(int(word).to_bytes(2, "big") for word in words if word is not None)
    value = payload.decode("ascii", errors="ignore").strip("\x00 \xff")
    return value or None


def _protocol_version(value: int | None) -> str | None:
    if value is None or value <= 0:
        return None
    major = value // 10000
    minor = (value // 100) % 100
    patch = value % 100
    return f"{major}.{minor:02d}.{patch:02d}"
