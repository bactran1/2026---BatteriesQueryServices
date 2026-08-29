from __future__ import annotations

import unittest

from batteries_query_service.megarevo import parse_r8klna_registers
from batteries_query_service.renogy_x import RenogyXProtocolError


class MegarevoR8KLNATests(unittest.TestCase):
    def test_decodes_split_phase_power_flow_and_energy(self) -> None:
        registers = _sample_registers()

        reading = parse_r8klna_registers(
            registers,
            inverter_id="renogy-x-8k",
            address=1,
            model="Renogy X 8K",
        )

        self.assertEqual(reading.serial_number, "R8TEST000001")
        self.assertEqual(reading.protocol_version, "2.00.12")
        self.assertEqual(reading.system_state, "battery_grid")
        self.assertEqual(reading.inverter_state, "standby")
        self.assertEqual(reading.dcdc_state, "standby")
        self.assertEqual(reading.grid_l1_voltage_v, 120.0)
        self.assertEqual(reading.grid_l2_voltage_v, 120.5)
        self.assertEqual(reading.grid_l1_current_a, -1.0)
        self.assertEqual(reading.grid_l2_current_a, -2.0)
        self.assertEqual(reading.grid_total_power_w, -1500.0)
        self.assertEqual(reading.grid_import_power_w, 1500.0)
        self.assertEqual(reading.grid_export_power_w, 0.0)
        self.assertEqual(reading.load_total_power_w, 1000.0)
        self.assertEqual(reading.home_load_total_power_w, 1500.0)
        self.assertEqual(reading.pv_total_power_w, 2300.0)
        self.assertEqual(reading.pv_inputs[0].voltage_v, 300.0)
        self.assertEqual(reading.pv_inputs[1].current_a, 2.5)
        self.assertEqual(reading.battery_voltage_v, 54.3)
        self.assertEqual(reading.battery_current_a, 2.5)
        self.assertEqual(reading.battery_soc_percent, 98.1)
        self.assertEqual(reading.inverter_total_power_w, 1500.0)
        self.assertEqual(reading.pv_energy_today_kwh, 12.345)
        self.assertEqual(reading.grid_import_energy_total_kwh, 987.654)
        self.assertEqual(reading.to_dict()["pv_inputs"][0]["channel"], 1)

    def test_decodes_signed_ffff_as_negative_one(self) -> None:
        reading = parse_r8klna_registers(
            {
                0x3110: 1200,
                0x3112: 0xFFFF,
                0x3115: 0,
            },
            inverter_id="renogy-x-8k",
            address=1,
            model="Renogy X 8K",
        )

        self.assertEqual(reading.grid_l1_power_w, -1.0)
        self.assertEqual(reading.grid_total_power_w, -1.0)
        self.assertEqual(reading.grid_import_power_w, 1.0)

    def test_decodes_state_alarm_and_fault_words(self) -> None:
        registers = _sample_registers()
        registers[0x3100] = (1 << 2) | (1 << 12)
        registers[0x3101] = 1 << 11
        registers[0x3102] = (1 << 4) | (1 << 7)
        registers[0x3103] = 1
        registers[0x3104] = 4 | (2 << 5) | (1 << 8) | (1 << 12) | (1 << 13)

        reading = parse_r8klna_registers(
            registers,
            inverter_id="renogy-x-8k",
            address=1,
            model="Renogy X 8K",
        )

        self.assertEqual(reading.system_state, "hybrid_power")
        self.assertEqual(reading.inverter_state, "grid_connected")
        self.assertEqual(reading.dcdc_state, "charging")
        self.assertTrue(reading.battery_charge_enabled)
        self.assertTrue(reading.battery_discharge_enabled)
        self.assertIn("battery_disconnected", reading.active_alarms)
        self.assertIn("bms_communication_failure", reading.active_alarms)
        self.assertIn("fan_fault", reading.active_faults)
        self.assertIn("grid_relay_fault", reading.active_faults)
        self.assertIn("mcu_self_test_failed", reading.active_faults)

    def test_preserves_optional_read_errors_as_degraded_evidence(self) -> None:
        reading = parse_r8klna_registers(
            _sample_registers(),
            inverter_id="renogy-x-8k",
            address=1,
            model="Renogy X 8K",
            read_errors=[{"start": 0x3190, "count": 14, "error": "timeout"}],
        )

        self.assertEqual(len(reading.read_errors), 1)
        self.assertEqual(reading.read_errors[0]["start"], 0x3190)

    def test_rejects_a_response_without_core_telemetry(self) -> None:
        with self.assertRaisesRegex(RenogyXProtocolError, "no usable"):
            parse_r8klna_registers(
                {0x1219: 20012},
                inverter_id="renogy-x-8k",
                address=1,
                model="Renogy X 8K",
            )

    def test_rejects_implausible_values_from_the_wrong_register_map(self) -> None:
        with self.assertRaisesRegex(RenogyXProtocolError, "battery_soc_percent"):
            parse_r8klna_registers(
                {0x3145: 5000},
                inverter_id="renogy-x-8k",
                address=1,
                model="Renogy X 8K",
            )


def _sample_registers() -> dict[int, int]:
    registers = {
        0x1219: 20012,
        0x3100: 0,
        0x3101: 0,
        0x3102: 0,
        0x3103: 0,
        0x3104: 3,
        0x3110: 1200,
        0x3111: _s16(-10),
        0x3112: _s16(-1000),
        0x3113: 1205,
        0x3114: _s16(-20),
        0x3115: _s16(-500),
        0x3119: 6000,
        0x311A: 32,
        0x311B: 35,
        0x3120: 1201,
        0x3121: 50,
        0x3122: 600,
        0x3124: 1200,
        0x3125: 35,
        0x3126: 400,
        0x3130: 3000,
        0x3131: 55,
        0x3132: 1650,
        0x3133: 2600,
        0x3134: 25,
        0x3135: 650,
        0x3136: 0,
        0x3137: 0,
        0x3138: 0,
        0x3139: 0,
        0x313A: 0,
        0x313B: 0,
        0x313C: 31,
        0x3140: 543,
        0x3141: 25,
        0x3145: 981,
        0x3146: 253,
        0x3147: 584,
        0x3148: 1000,
        0x3149: 1000,
        0x314A: 136,
        0x314B: 3405,
        0x314C: 3391,
        0x3152: 33,
        0x3190: 1201,
        0x3191: 75,
        0x3192: 900,
        0x3193: 1200,
        0x3194: 50,
        0x3195: 600,
        0x319C: 2,
        0x319D: 3800,
        0x31A6: 800,
        0x31A7: 700,
        0x31A9: 1500,
    }
    _set_ascii(registers, 0x1234, "R8TEST000001")
    _set_u32_cd_ab(registers, 0x3153, 12345)
    _set_u32_cd_ab(registers, 0x317D, 987654)
    return registers


def _s16(value: int) -> int:
    return value & 0xFFFF


def _set_ascii(registers: dict[int, int], start: int, value: str) -> None:
    payload = value.encode("ascii")
    for offset in range(0, len(payload), 2):
        registers[start + offset // 2] = int.from_bytes(payload[offset : offset + 2], "big")


def _set_u32_cd_ab(registers: dict[int, int], start: int, value: int) -> None:
    registers[start] = value & 0xFFFF
    registers[start + 1] = value >> 16


if __name__ == "__main__":
    unittest.main()
