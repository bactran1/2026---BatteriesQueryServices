from __future__ import annotations

from dataclasses import asdict, dataclass


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
