from __future__ import annotations

import time

from prometheus_client import Gauge, CollectorRegistry

from .models import BatteryReading, InverterReading


class MetricsPublisher:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        labels = ["battery_id", "address"]

        self.poll_success = Gauge(
            "battery_poll_success",
            "Whether the most recent battery poll succeeded",
            labels,
            registry=self.registry,
        )
        self.last_poll_timestamp = Gauge(
            "battery_last_poll_timestamp_seconds",
            "Unix timestamp of the most recent battery poll attempt",
            labels,
            registry=self.registry,
        )
        self.voltage = Gauge(
            "battery_voltage_volts",
            "Battery pack voltage",
            labels,
            registry=self.registry,
        )
        self.current = Gauge(
            "battery_current_amps",
            "Battery pack current",
            labels,
            registry=self.registry,
        )
        self.power = Gauge(
            "battery_power_watts",
            "Battery pack power",
            labels,
            registry=self.registry,
        )
        self.soc = Gauge(
            "battery_soc_percent",
            "Battery state of charge",
            labels,
            registry=self.registry,
        )
        self.soh = Gauge(
            "battery_soh_percent",
            "Battery state of health",
            labels,
            registry=self.registry,
        )
        self.cycles = Gauge(
            "battery_cycle_count",
            "Battery charge cycle count",
            labels,
            registry=self.registry,
        )
        self.cell_voltage = Gauge(
            "battery_cell_voltage_volts",
            "Individual cell voltage",
            labels + ["cell"],
            registry=self.registry,
        )
        self.temperature = Gauge(
            "battery_temperature_celsius",
            "Battery temperature sensor reading",
            labels + ["sensor"],
            registry=self.registry,
        )
        self.alarm_count = Gauge(
            "battery_alarm_count",
            "Number of active level 1 alarms",
            labels,
            registry=self.registry,
        )
        self.fault_count = Gauge(
            "battery_fault_count",
            "Number of active level 2 faults",
            labels,
            registry=self.registry,
        )

        inverter_labels = ["inverter_id", "address"]
        self.inverter_poll_success = Gauge(
            "inverter_poll_success",
            "Whether the most recent inverter core-telemetry poll succeeded",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_last_poll_timestamp = Gauge(
            "inverter_last_poll_timestamp_seconds",
            "Unix timestamp of the most recent inverter poll attempt",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_read_error_count = Gauge(
            "inverter_read_error_count",
            "Number of optional Modbus ranges that failed in the latest inverter poll",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_pv_power = Gauge(
            "inverter_pv_power_watts",
            "Total photovoltaic input power reported by the inverter",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_grid_power = Gauge(
            "inverter_grid_power_watts",
            "Signed grid power; positive exports to grid and negative imports from grid",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_grid_import_power = Gauge(
            "inverter_grid_import_power_watts",
            "Power imported from the grid",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_grid_export_power = Gauge(
            "inverter_grid_export_power_watts",
            "Power exported to the grid",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_load_power = Gauge(
            "inverter_load_power_watts",
            "Total inverter backup-load output power",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_home_load_power = Gauge(
            "inverter_home_load_power_watts",
            "Total external home-load power measured by the inverter",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_battery_power = Gauge(
            "inverter_battery_power_watts",
            "Signed inverter battery power; positive is charging",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_battery_soc = Gauge(
            "inverter_battery_soc_percent",
            "Battery state of charge reported to the inverter",
            inverter_labels,
            registry=self.registry,
        )
        self.inverter_temperature = Gauge(
            "inverter_temperature_celsius",
            "Inverter temperature",
            inverter_labels + ["sensor"],
            registry=self.registry,
        )
        self.inverter_pv_input_voltage = Gauge(
            "inverter_pv_input_voltage_volts",
            "PV input voltage by MPPT channel",
            inverter_labels + ["channel"],
            registry=self.registry,
        )
        self.inverter_pv_input_current = Gauge(
            "inverter_pv_input_current_amps",
            "PV input current by MPPT channel",
            inverter_labels + ["channel"],
            registry=self.registry,
        )
        self.inverter_pv_input_power = Gauge(
            "inverter_pv_input_power_watts",
            "PV input power by MPPT channel",
            inverter_labels + ["channel"],
            registry=self.registry,
        )

    def record_reading(self, reading: BatteryReading) -> None:
        labels = self._labels(reading.id, reading.address)
        self.poll_success.labels(**labels).set(1)
        self.last_poll_timestamp.labels(**labels).set(time.time())
        self._set_if_present(self.voltage, labels, reading.voltage_v)
        self._set_if_present(self.current, labels, reading.current_a)
        self._set_if_present(self.power, labels, reading.power_w)
        self._set_if_present(self.soc, labels, reading.soc_percent)
        self._set_if_present(self.soh, labels, reading.soh_percent)
        self._set_if_present(self.cycles, labels, reading.cycle_count)
        self.alarm_count.labels(**labels).set(len(reading.alarms))
        self.fault_count.labels(**labels).set(len(reading.faults))

        for index, voltage in enumerate(reading.cell_voltages_v, start=1):
            self.cell_voltage.labels(**labels, cell=str(index)).set(voltage)
        for index, temperature in enumerate(reading.temperatures_c, start=1):
            self.temperature.labels(**labels, sensor=str(index)).set(temperature)

    def record_error(self, battery_id: str, address: int) -> None:
        labels = self._labels(battery_id, address)
        self.poll_success.labels(**labels).set(0)
        self.last_poll_timestamp.labels(**labels).set(time.time())

    def record_inverter_reading(self, reading: InverterReading) -> None:
        labels = self._inverter_labels(reading.id, reading.address)
        self.inverter_poll_success.labels(**labels).set(1)
        self.inverter_last_poll_timestamp.labels(**labels).set(time.time())
        self.inverter_read_error_count.labels(**labels).set(len(reading.read_errors))
        self._set_if_present(self.inverter_pv_power, labels, reading.pv_total_power_w)
        self._set_if_present(
            self.inverter_grid_power, labels, reading.grid_total_power_w
        )
        self._set_if_present(
            self.inverter_grid_import_power, labels, reading.grid_import_power_w
        )
        self._set_if_present(
            self.inverter_grid_export_power, labels, reading.grid_export_power_w
        )
        self._set_if_present(
            self.inverter_load_power, labels, reading.load_total_power_w
        )
        self._set_if_present(
            self.inverter_home_load_power, labels, reading.home_load_total_power_w
        )
        self._set_if_present(
            self.inverter_battery_power, labels, reading.battery_power_w
        )
        self._set_if_present(
            self.inverter_battery_soc, labels, reading.battery_soc_percent
        )
        for sensor, value in (
            ("inverter", reading.inverter_temperature_c),
            ("internal", reading.internal_temperature_c),
            ("dcdc", reading.dcdc_temperature_c),
        ):
            self._set_if_present(
                self.inverter_temperature, {**labels, "sensor": sensor}, value
            )
        for pv_input in reading.pv_inputs:
            channel_labels = {**labels, "channel": str(pv_input.channel)}
            self._set_if_present(
                self.inverter_pv_input_voltage,
                channel_labels,
                pv_input.voltage_v,
            )
            self._set_if_present(
                self.inverter_pv_input_current,
                channel_labels,
                pv_input.current_a,
            )
            self._set_if_present(
                self.inverter_pv_input_power,
                channel_labels,
                pv_input.power_w,
            )

    def record_inverter_error(self, inverter_id: str, address: int) -> None:
        labels = self._inverter_labels(inverter_id, address)
        self.inverter_poll_success.labels(**labels).set(0)
        self.inverter_last_poll_timestamp.labels(**labels).set(time.time())

    def _set_if_present(
        self,
        gauge: Gauge,
        labels: dict[str, str],
        value: float | int | None,
    ) -> None:
        if value is not None:
            gauge.labels(**labels).set(value)

    def _labels(self, battery_id: str, address: int) -> dict[str, str]:
        return {"battery_id": battery_id, "address": str(address)}

    def _inverter_labels(self, inverter_id: str, address: int) -> dict[str, str]:
        return {"inverter_id": inverter_id, "address": str(address)}
