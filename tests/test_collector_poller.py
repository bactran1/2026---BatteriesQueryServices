from __future__ import annotations

import unittest
from unittest.mock import patch

from batteries_query_service.config import InverterSettings, Settings
from batteries_query_service.metrics import MetricsPublisher
from batteries_query_service.models import InverterReading
from batteries_query_service.poller import BatteryPoller


class CollectorPollerTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
