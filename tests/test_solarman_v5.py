from __future__ import annotations

import unittest
from unittest.mock import Mock

from batteries_query_service.renogy_x import RenogyXProtocolError
from batteries_query_service.solarman_v5 import (
    SolarmanV5ModbusClient,
    SolarmanV5Settings,
)


class SolarmanV5ModbusClientTests(unittest.TestCase):
    def test_reuses_one_connection_for_a_poll_and_disconnects_cleanly(self) -> None:
        connection = Mock()
        connection.read_holding_registers.side_effect = (
            lambda *, register_addr, quantity: list(
                range(register_addr, register_addr + quantity)
            )
        )
        factory = Mock(return_value=connection)
        settings = SolarmanV5Settings(
            host="192.168.10.50",
            logger_serial=2345678901,
            timeout_seconds=2.5,
        )
        client = SolarmanV5ModbusClient(settings, client_factory=factory)

        first = client.read_holding_registers(1, 0x3100, 5)
        registers, errors = client.read_ranges(
            1,
            [(0x3110, 3), (0x3120, 2)],
            inter_request_delay_seconds=0,
        )
        client.close()

        self.assertEqual(first, list(range(0x3100, 0x3105)))
        self.assertEqual(registers[0x3112], 0x3112)
        self.assertEqual(registers[0x3121], 0x3121)
        self.assertEqual(errors, [])
        factory.assert_called_once_with(
            "192.168.10.50",
            2345678901,
            port=8899,
            mb_slave_id=1,
            socket_timeout=2.5,
            v5_error_correction=False,
            auto_reconnect=True,
        )
        connection.disconnect.assert_called_once_with()

    def test_range_reads_retry_transient_logger_errors(self) -> None:
        connection = Mock()
        connection.read_holding_registers.side_effect = [
            TimeoutError("logger busy"),
            [10, 11],
        ]
        client = SolarmanV5ModbusClient(
            SolarmanV5Settings(host="logger.local", logger_serial=1234567890),
            client_factory=Mock(return_value=connection),
        )

        registers, errors = client.read_ranges(
            1,
            [(100, 2)],
            retries=1,
            retry_delay_seconds=0,
            inter_request_delay_seconds=0,
        )

        self.assertEqual(registers, {100: 10, 101: 11})
        self.assertEqual(errors, [])
        self.assertEqual(connection.read_holding_registers.call_count, 2)
        client.close()

    def test_rejects_short_register_responses(self) -> None:
        connection = Mock()
        connection.read_holding_registers.return_value = [1]
        client = SolarmanV5ModbusClient(
            SolarmanV5Settings(host="logger.local", logger_serial=1234567890),
            client_factory=Mock(return_value=connection),
        )

        with self.assertRaisesRegex(RenogyXProtocolError, "returned 1 registers"):
            client.read_holding_registers(1, 0x3100, 5)

        client.close()

    def test_validates_the_unsigned_32_bit_logger_serial(self) -> None:
        with self.assertRaisesRegex(ValueError, "logger serial"):
            SolarmanV5Settings(host="logger.local", logger_serial=0)
        with self.assertRaisesRegex(ValueError, "logger serial"):
            SolarmanV5Settings(host="logger.local", logger_serial=0x100000000)


if __name__ == "__main__":
    unittest.main()
