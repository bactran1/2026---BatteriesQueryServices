from __future__ import annotations

import unittest
from unittest.mock import patch

from batteries_query_service.config import InverterSettings, Settings
from batteries_query_service.metrics import MetricsPublisher
from batteries_query_service.models import InverterReading
from batteries_query_service.poller import BatteryPoller


class CollectorPollerTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_battery_is_read_with_the_driver_its_protocol_names(self) -> None:
        from batteries_query_service.config import BatterySettings

        settings = Settings(
            batteries=[
                BatterySettings(id="rack-1", address=1),
                BatterySettings(id="rack-4", address=2, serial_port="/dev/ttyUSB2", protocol="pylontech"),
            ],
        )
        poller = BatteryPoller(settings, MetricsPublisher())

        def reading(battery_id: str):
            from batteries_query_service.pylontech import build_reading, parse_analog_values, parse_frame
            from tests.test_pylontech import ANALOG

            return build_reading(battery_id, 2, parse_analog_values(parse_frame(ANALOG).info))

        with patch("batteries_query_service.poller.EcoWorthyModbusClient") as jbd, patch(
            "batteries_query_service.poller.PylontechClient"
        ) as pylontech:
            jbd.return_value.read_pack_status.side_effect = lambda address, battery_id: reading(battery_id)
            pylontech.return_value.read_pack_status.side_effect = lambda address, battery_id: reading(battery_id)
            await poller.poll_once()

        jbd.return_value.read_pack_status.assert_called_once_with(1, "rack-1")
        pylontech.return_value.read_pack_status.assert_called_once_with(2, "rack-4")
        self.assertEqual(pylontech.call_args.args[0].port, "/dev/ttyUSB2")
        self.assertEqual(jbd.call_args.args[0].port, settings.serial.port)
        snapshot = await poller.snapshot()
        by_id = {battery["id"]: battery for battery in snapshot["batteries"]}
        self.assertEqual(by_id["rack-1"]["protocol"], "ecoworthy")
        self.assertEqual(by_id["rack-4"]["protocol"], "pylontech")
        self.assertEqual(by_id["rack-4"]["status"], "ok")
        self.assertEqual(by_id["rack-4"]["last_reading"]["full_capacity_ah"], 314.0)

    async def test_exposes_successful_inverter_reading(self) -> None:
        settings = Settings(
            inverter=InverterSettings(enabled=True),
            batteries=[],
        )
        reading = InverterReading(
            id="renogy-x-8k",
            address=1,
            timestamp="2026-08-29T12:00:00Z",
            model="Renogy X 8K",
            profile="megarevo-r8klna-v2.12-read-only",
            pv_total_power_w=3200.0,
        )
        poller = BatteryPoller(settings, MetricsPublisher())

        with patch(
            "batteries_query_service.poller.MegarevoR8KLNAClient"
        ) as client_type:
            client_type.return_value.read_status.return_value = reading
            await poller.poll_once()

        snapshot = await poller.snapshot()
        self.assertEqual(snapshot["inverter"]["status"], "ok")
        self.assertEqual(
            snapshot["inverter"]["last_reading"]["pv_total_power_w"], 3200.0
        )
        self.assertEqual(snapshot["batteries"], [])

    async def test_the_snapshot_carries_the_host_readout(self) -> None:
        settings = Settings(inverter=InverterSettings(enabled=False), batteries=[])
        poller = BatteryPoller(settings, MetricsPublisher())
        poller.host_stats.sample = lambda: {"cpu_temperature_c": 46.1, "cpu_percent": 4.0}
        self.assertIsNone((await poller.snapshot())["host"])

        await poller.poll_once()
        self.assertEqual(
            (await poller.snapshot())["host"],
            {"cpu_temperature_c": 46.1, "cpu_percent": 4.0},
        )

    async def test_a_failing_host_sampler_cannot_break_the_poll(self) -> None:
        settings = Settings(inverter=InverterSettings(enabled=False), batteries=[])
        poller = BatteryPoller(settings, MetricsPublisher())

        def explode():
            raise RuntimeError("sysfs went away")

        poller.host_stats.sample = explode
        await poller.poll_once()
        snapshot = await poller.snapshot()
        self.assertIsNone(snapshot["host"])
        self.assertEqual(snapshot["service"]["poll_count"], 1)

    async def test_inverter_failure_does_not_abort_the_collector_snapshot(self) -> None:
        settings = Settings(
            inverter=InverterSettings(enabled=True),
            batteries=[],
        )
        poller = BatteryPoller(settings, MetricsPublisher())

        with patch(
            "batteries_query_service.poller.MegarevoR8KLNAClient"
        ) as client_type:
            client_type.return_value.read_status.side_effect = TimeoutError("unplugged")
            await poller.poll_once()

        snapshot = await poller.snapshot()
        health = await poller.health()
        self.assertEqual(snapshot["inverter"]["status"], "error")
        self.assertIn("unplugged", snapshot["inverter"]["last_error"])
        self.assertEqual(snapshot["batteries"], [])
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["inverter_status"], "error")

    async def test_optional_range_failure_marks_inverter_degraded(self) -> None:
        settings = Settings(
            inverter=InverterSettings(enabled=True),
            batteries=[],
        )
        reading = InverterReading(
            id="renogy-x-8k",
            address=1,
            timestamp="2026-08-29T12:00:00Z",
            model="Renogy X 8K",
            profile="megarevo-r8klna-v2.12-read-only",
            read_errors=[{"start": 0x3190, "count": 14, "error": "timeout"}],
        )
        poller = BatteryPoller(settings, MetricsPublisher())

        with patch(
            "batteries_query_service.poller.MegarevoR8KLNAClient"
        ) as client_type:
            client_type.return_value.read_status.return_value = reading
            await poller.poll_once()

        self.assertEqual((await poller.snapshot())["inverter"]["status"], "degraded")

    async def test_uses_solarman_logger_transport_and_exposes_connection(self) -> None:
        settings = Settings(
            inverter=InverterSettings(
                enabled=True,
                transport="solarman_v5",
                host="192.168.10.50",
                tcp_port=8899,
                logger_serial=2345678901,
            ),
            batteries=[],
        )
        reading = InverterReading(
            id="renogy-x-8k",
            address=1,
            timestamp="2026-08-29T12:00:00Z",
            model="Renogy X 8K",
            profile="megarevo-r8klna-v2.12-read-only",
            grid_total_power_w=-1200.0,
        )
        poller = BatteryPoller(settings, MetricsPublisher())

        with patch(
            "batteries_query_service.poller.SolarmanV5ModbusClient"
        ) as transport_type, patch(
            "batteries_query_service.poller.MegarevoR8KLNAClient"
        ) as client_type:
            client_type.return_value.read_status.return_value = reading
            await poller.poll_once()

        transport_settings = transport_type.call_args.args[0]
        self.assertEqual(transport_settings.host, "192.168.10.50")
        self.assertEqual(transport_settings.logger_serial, 2345678901)
        self.assertIs(
            client_type.call_args.kwargs["modbus_client"],
            transport_type.return_value,
        )
        client_type.return_value.close.assert_called_once_with()
        inverter = (await poller.snapshot())["inverter"]
        self.assertEqual(inverter["transport"], "solarman_v5")
        self.assertEqual(inverter["connection"], "192.168.10.50:8899 via SOLARMAN V5")
        self.assertIsNone(inverter["serial_port"])
        self.assertEqual(inverter["logger_serial"], 2345678901)


if __name__ == "__main__":
    unittest.main()
