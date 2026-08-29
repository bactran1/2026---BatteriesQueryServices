from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class BatteryReading:
    id: str
    address: int
    timestamp: str
    voltage_v: float | None
    current_a: float | None
    power_w: float | None
    soc_percent: float | None
    remaining_capacity_ah: float | None
    full_capacity_ah: float | None
    rated_capacity_ah: float | None
    soh_percent: int | None
    cycle_count: int | None
    operation_status_code: int | None
    operation_status: str
    mosfet_state: list[str]
    port_state: list[str]
    fault_code: int | None
    faults: list[str]
    alarm_code: int | None
    alarms: list[str]
    mosfet_temperature_c: float | None
    ambient_temperature_c: float | None
    high_cell_number: int | None
    high_cell_voltage_v: float | None
    low_cell_number: int | None
    low_cell_voltage_v: float | None
    average_cell_voltage_v: float | None
    cell_voltage_delta_v: float | None
    high_temperature_sensor_number: int | None
    high_temperature_c: float | None
    low_temperature_sensor_number: int | None
    low_temperature_c: float | None
    average_temperature_c: float | None
    charge_voltage_limit_v: float | None
    charge_current_limit_a: float | None
    discharge_voltage_limit_v: float | None
    discharge_current_limit_a: float | None
    cell_count: int
    cell_voltages_v: list[float]
    temperature_sensor_count: int
    temperatures_c: list[float]
    balance_status_mask: int | None
    firmware_version: str | None
    serial_number: str | None
    parallel_pack_count: int | None
    available_pack_addresses: list[int]
    can_protocol_code: int | None
    can_protocol: str | None
    rs485_protocol_code: int | None
    rs485_protocol: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PvInputReading:
    channel: int
    voltage_v: float | None
    current_a: float | None
    power_w: float | None


@dataclass(frozen=True)
class InverterReading:
    id: str
    address: int
    timestamp: str
    model: str
    profile: str
    serial_number: str | None = None
    protocol_version: str | None = None
    dsp_state_code: int | None = None
    system_state_code: int | None = None
    system_state: str | None = None
    inverter_state_code: int | None = None
    inverter_state: str | None = None
    dcdc_state_code: int | None = None
    dcdc_state: str | None = None
    battery_charge_enabled: bool | None = None
    battery_discharge_enabled: bool | None = None
    dsp_alarm_words: list[int] = field(default_factory=list)
    dsp_fault_words: list[int] = field(default_factory=list)
    arm_alarm_words: list[int] = field(default_factory=list)
    arm_fault_words: list[int] = field(default_factory=list)
    active_alarms: list[str] = field(default_factory=list)
    active_faults: list[str] = field(default_factory=list)
    bms_alarm_word: int | None = None
    bms_protection_word: int | None = None
    bms_error_word: int | None = None
    grid_l1_voltage_v: float | None = None
    grid_l2_voltage_v: float | None = None
    grid_l1_current_a: float | None = None
    grid_l2_current_a: float | None = None
    grid_l1_power_w: float | None = None
    grid_l2_power_w: float | None = None
    grid_total_power_w: float | None = None
    grid_import_power_w: float | None = None
    grid_export_power_w: float | None = None
    grid_frequency_hz: float | None = None
    grid_port_l1_power_w: float | None = None
    grid_port_l2_power_w: float | None = None
    load_l1_voltage_v: float | None = None
    load_l2_voltage_v: float | None = None
    load_l1_current_a: float | None = None
    load_l2_current_a: float | None = None
    load_l1_power_w: float | None = None
    load_l2_power_w: float | None = None
    load_total_power_w: float | None = None
    home_load_l1_power_w: float | None = None
    home_load_l2_power_w: float | None = None
    home_load_total_power_w: float | None = None
    pv_inputs: list[PvInputReading] = field(default_factory=list)
    pv_total_power_w: float | None = None
    pv_temperature_c: float | None = None
    battery_voltage_v: float | None = None
    battery_current_a: float | None = None
    battery_power_w: float | None = None
    battery_soc_percent: float | None = None
    battery_temperature_c: float | None = None
    battery_charge_voltage_limit_v: float | None = None
    battery_charge_current_limit_a: float | None = None
    battery_discharge_current_limit_a: float | None = None
    battery_cell_max_voltage_v: float | None = None
    battery_cell_min_voltage_v: float | None = None
    battery_cell_max_temperature_c: float | None = None
    battery_cell_min_temperature_c: float | None = None
    inverter_l1_voltage_v: float | None = None
    inverter_l2_voltage_v: float | None = None
    inverter_l1_current_a: float | None = None
    inverter_l2_current_a: float | None = None
    inverter_l1_power_w: float | None = None
    inverter_l2_power_w: float | None = None
    inverter_total_power_w: float | None = None
    inverter_temperature_c: float | None = None
    internal_temperature_c: float | None = None
    dcdc_temperature_c: float | None = None
    bus_voltage_v: float | None = None
    leakage_current_ma: float | None = None
    generator_frequency_hz: float | None = None
    generator_l1_voltage_v: float | None = None
    generator_l2_voltage_v: float | None = None
    pv_energy_today_kwh: float | None = None
    pv_energy_total_kwh: float | None = None
    grid_export_energy_today_kwh: float | None = None
    grid_export_energy_total_kwh: float | None = None
    grid_import_energy_today_kwh: float | None = None
    grid_import_energy_total_kwh: float | None = None
    load_energy_today_kwh: float | None = None
    load_energy_total_kwh: float | None = None
    battery_charge_energy_today_kwh: float | None = None
    battery_charge_energy_total_kwh: float | None = None
    battery_discharge_energy_today_kwh: float | None = None
    battery_discharge_energy_total_kwh: float | None = None
    read_errors: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
