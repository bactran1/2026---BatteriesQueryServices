from __future__ import annotations

import time

from prometheus_client import Gauge, CollectorRegistry

from .models import BatteryReading


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

    def _set_if_present(self, gauge: Gauge, labels: dict[str, str], value: float | int | None) -> None:
        if value is not None:
            gauge.labels(**labels).set(value)

    def _labels(self, battery_id: str, address: int) -> dict[str, str]:
        return {"battery_id": battery_id, "address": str(address)}
