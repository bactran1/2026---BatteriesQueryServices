from __future__ import annotations

import unittest

from batteries_query_service.ecoworthy import append_crc
from batteries_query_service.inverter_probe import parse_ranges, register_views
from batteries_query_service.renogy_x import (
    RenogyXProtocolError,
    RegisterDefinition,
    assess_common_profile,
    build_read_holding_request,
    chunk_register_range,
    decode_registers,
    describe_modbus_frame,
    parse_read_holding_response,
    signed_16,
)


class RenogyXProtocolTests(unittest.TestCase):
    def test_builds_standard_read_holding_register_request(self) -> None:
        request = build_read_holding_request(1, 4000, 2)

        self.assertEqual(request[:6], bytes.fromhex("01 03 0f a0 00 02"))
        self.assertEqual(request.hex(), "01030fa00002c73d")

    def test_parses_holding_register_response(self) -> None:
        response = append_crc(bytes.fromhex("01 03 04 04 b0 ff 9c"))

        values = parse_read_holding_response(
            response,
            expected_address=1,
            expected_count=2,
        )

        self.assertEqual(values, [1200, 0xFF9C])

    def test_rejects_modbus_exception_response(self) -> None:
        response = append_crc(bytes.fromhex("01 83 02"))

        with self.assertRaisesRegex(RenogyXProtocolError, "exception 2"):
            parse_read_holding_response(response, expected_address=1)

    def test_rejects_bad_crc(self) -> None:
        response = bytearray(append_crc(bytes.fromhex("01 03 02 04 b0")))
        response[-1] ^= 0xFF

        with self.assertRaisesRegex(RenogyXProtocolError, "CRC mismatch"):
            parse_read_holding_response(bytes(response), expected_address=1)

    def test_decodes_signed_scaled_and_undefined_registers(self) -> None:
        definitions = (
            RegisterDefinition("voltage", 4000, "V", 0.1),
            RegisterDefinition("current", 4001, "A", 0.01, signed=True),
            RegisterDefinition("missing", 4002),
        )

        decoded = decode_registers(
            {4000: 543, 4001: 0xFF9C, 4002: 0xFFFF}, definitions
        )

        self.assertEqual(decoded["voltage"]["value"], 54.3)
        self.assertEqual(decoded["current"]["value"], -1.0)
        self.assertIsNone(decoded["missing"])

    def test_assessment_does_not_claim_renogy_x_compatibility(self) -> None:
        fields = {
            "battery_voltage_v": {
                "address": 4005,
                "raw": 543,
                "value": 54.3,
                "unit": "V",
            },
            "grid_l1_voltage_v": {
                "address": 4010,
                "raw": 1201,
                "value": 120.1,
                "unit": "V",
            },
        }

        assessment = assess_common_profile(fields)

        self.assertEqual(assessment["status"], "common_registers_responded")
        self.assertIn("no Renogy X-specific", assessment["notes"][0])

    def test_describes_captured_read_request(self) -> None:
        request = build_read_holding_request(1, 4000, 13)

        description = describe_modbus_frame(request)

        self.assertTrue(description["crc_valid"])
        self.assertEqual(description["kind"], "read_request")
        self.assertEqual(description["start"], 4000)
        self.assertEqual(description["count"], 13)

    def test_chunks_large_register_ranges(self) -> None:
        self.assertEqual(
            list(chunk_register_range(4300, 126, 60)),
            [(4300, 60), (4360, 60), (4420, 6)],
        )

    def test_signed_16(self) -> None:
        self.assertEqual(signed_16(0x7FFF), 32767)
        self.assertEqual(signed_16(0xFFFF), -1)
        self.assertEqual(signed_16(0x8000), -32768)


class RenogyXProbeCliTests(unittest.TestCase):
    def test_parses_inclusive_decimal_and_hex_ranges(self) -> None:
        self.assertEqual(
            parse_ranges(["4000:4002", "0x1000:0x1001"]),
            [(4000, 3), (0x1000, 2)],
        )

    def test_register_views_include_signed_and_scaled_values(self) -> None:
        self.assertEqual(
            register_views(0xFF9C),
            {
                "hex": "0xFF9C",
                "unsigned": 65436,
                "signed": -100,
                "tenths": -10.0,
                "hundredths": -1.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
