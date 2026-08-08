from __future__ import annotations

import unittest

from batteries_query_service.ecoworthy import (
    append_crc,
    build_read_request,
    crc16_modbus,
    parse_pack_status_response,
)


class EcoWorthyProtocolTests(unittest.TestCase):
    def test_crc_matches_known_pack_status_request(self) -> None:
        request_without_crc = bytes.fromhex("01 78 10 00 10 a0 00 00")
        self.assertEqual(crc16_modbus(request_without_crc), 0xB27F)

    def test_build_read_request(self) -> None:
        self.assertEqual(
            build_read_request(1, 0x1000, 0x10A0).hex(" "),
            "01 78 10 00 10 a0 00 00 7f b2",
        )

    def test_parse_pack_status_response(self) -> None:
        frame = _sample_status_frame()
        reading = parse_pack_status_response(frame, battery_id="rack-1")

        self.assertEqual(reading.id, "rack-1")
        self.assertEqual(reading.address, 1)
        self.assertEqual(reading.voltage_v, 52.63)
        self.assertEqual(reading.current_a, -12.34)
        self.assertEqual(reading.power_w, -649.45)
        self.assertEqual(reading.soc_percent, 73.2)
        self.assertEqual(reading.soh_percent, 100)
        self.assertEqual(reading.cycle_count, 2)
        self.assertEqual(reading.cell_count, 16)
        self.assertEqual(reading.cell_voltages_v[0], 3.289)
        self.assertEqual(reading.cell_voltages_v[-1], 3.304)
        self.assertEqual(reading.temperature_sensor_count, 4)
        self.assertEqual(reading.temperatures_c, [12.8, 12.9, 12.9, 13.0])
        self.assertEqual(reading.firmware_version, "13.2")
        self.assertEqual(reading.serial_number, "JBD48100000")
        self.assertEqual(reading.parallel_pack_count, 3)
        self.assertEqual(reading.available_pack_addresses, [1, 2, 3])
        self.assertEqual(reading.rs485_protocol, "pylon")


def _sample_status_frame() -> bytes:
    data = bytearray(162)

    def set_u16(full_offset: int, value: int) -> None:
        index = full_offset - 8
        data[index : index + 2] = value.to_bytes(2, "big")

    def set_u32(full_offset: int, value: int) -> None:
        index = full_offset - 8
        data[index : index + 4] = value.to_bytes(4, "big")

    set_u16(8, 5263)
    set_u32(12, 298766)
    set_u16(16, 7320)
    set_u16(18, 7320)
    set_u16(20, 10000)
    set_u16(22, 10000)
    set_u16(24, 632)
    set_u16(26, 642)
    set_u16(28, 2)
    set_u16(30, 100)
    set_u32(32, 0)
    set_u32(36, 0)
    set_u16(40, 3)
    set_u16(42, 4)
    set_u16(44, 2)
    set_u16(46, 16)
    set_u16(48, 3304)
    set_u16(50, 1)
    set_u16(52, 3289)
    set_u16(54, 3296)
    set_u16(56, 4)
    set_u16(58, 630)
    set_u16(60, 1)
    set_u16(62, 628)
    set_u16(64, 629)
    set_u16(66, 584)
    set_u16(68, 1000)
    set_u16(70, 448)
    set_u16(72, 1000)
    set_u16(74, 16)

    for index in range(16):
        set_u16(76 + index * 2, 3289 + index)

    temperatures_start = 76 + 16 * 2
    set_u16(temperatures_start, 4)
    for index, raw_temperature in enumerate([628, 629, 629, 630]):
        set_u16(temperatures_start + 2 + index * 2, raw_temperature)

    optional_start = temperatures_start + 2 + 4 * 2
    set_u16(optional_start, 0)
    set_u16(optional_start + 2, 0)
    set_u16(optional_start + 4, 0x0D02)

    serial = b"JBD48100000"
    serial_offset = optional_start + 6 - 8
    data[serial_offset : serial_offset + len(serial)] = serial

    set_u16(optional_start + 36, 3)
    set_u16(optional_start + 38, 0x0007)
    set_u16(optional_start + 40, 0x5AA6)
    set_u16(optional_start + 42, 0)
    set_u16(optional_start + 44, 0)
    set_u16(optional_start + 46, 0)

    header = bytes.fromhex("01 78 10 00 10 a0") + len(data).to_bytes(2, "big")
    return append_crc(header + bytes(data))


if __name__ == "__main__":
    unittest.main()
