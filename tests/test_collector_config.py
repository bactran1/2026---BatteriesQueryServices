from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from batteries_query_service.config import load_settings


class CollectorConfigTests(unittest.TestCase):
    def test_build_commit_is_loaded_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "missing.toml"
            environment = {
                "BQS_CONFIG": str(config_path),
                "BQS_BUILD_COMMIT": "abc123",
                "BQS_BUFFER_PATH": "/tmp/replay.sqlite3",
                "BQS_BUFFER_RETENTION_HOURS": "48",
                "BQS_BUFFER_SAMPLE_INTERVAL": "60",
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = load_settings()

        self.assertEqual(settings.build_commit, "abc123")
        self.assertEqual(settings.buffer.path, "/tmp/replay.sqlite3")
        self.assertEqual(settings.buffer.retention_hours, 48)
        self.assertEqual(settings.buffer.sample_interval_seconds, 60.0)
        self.assertEqual([battery.address for battery in settings.batteries], [1, 2, 3])
        self.assertFalse(settings.inverter.enabled)

    def test_inverter_settings_support_toml_and_environment_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "collector.toml"
            config_path.write_text(
                """
[inverter]
enabled = true
id = "renogy"
serial_port = "/dev/ttyUSB1"
address = 1
baudrate = 9600
parity = "N"
retries = 1
""",
                encoding="utf-8",
            )
            environment = {
                "BQS_CONFIG": str(config_path),
                "BQS_INVERTER_SERIAL_PORT": "/dev/serial/by-id/inverter",
                "BQS_INVERTER_RETRIES": "3",
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = load_settings()

        self.assertTrue(settings.inverter.enabled)
        self.assertEqual(settings.inverter.id, "renogy")
        self.assertEqual(
            settings.inverter.serial_port, "/dev/serial/by-id/inverter"
        )
        self.assertEqual(settings.inverter.transport, "serial")
        self.assertEqual(settings.inverter.retries, 3)

    def test_solarman_v5_settings_load_from_toml_with_blank_env_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "collector.toml"
            config_path.write_text(
                """
[inverter]
enabled = true
transport = "solarman_v5"
host = "192.168.10.50"
tcp_port = 8899
logger_serial = 2345678901
address = 1
v5_error_correction = true
""",
                encoding="utf-8",
            )
            environment = {
                "BQS_CONFIG": str(config_path),
                "BQS_INVERTER_TRANSPORT": "",
                "BQS_INVERTER_HOST": "",
                "BQS_INVERTER_TCP_PORT": "",
                "BQS_INVERTER_LOGGER_SERIAL": "",
                "BQS_INVERTER_V5_ERROR_CORRECTION": "",
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = load_settings()

        self.assertEqual(settings.inverter.transport, "solarman_v5")
        self.assertEqual(settings.inverter.host, "192.168.10.50")
        self.assertEqual(settings.inverter.tcp_port, 8899)
        self.assertEqual(settings.inverter.logger_serial, 2345678901)
        self.assertTrue(settings.inverter.v5_error_correction)

    def test_enabled_solarman_transport_requires_logger_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "collector.toml"
            config_path.write_text(
                """
[inverter]
enabled = true
transport = "solarman_v5"
host = "192.168.10.50"
""",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ, {"BQS_CONFIG": str(config_path)}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "logger serial is required"):
                    load_settings()


if __name__ == "__main__":
    unittest.main()
