from __future__ import annotations

import unittest

from batteries_query_service import pylontech
from batteries_query_service.ecoworthy import SerialConnectionSettings

# Replies captured from the Eco-worthy 51.2 V 314 Ah floor-standing unit (PACE
# BMS in Pylontech mode) at address 2 on 2026-11-01, as the probe printed them.
ANALOG = b"~2002460070720002100D0B0D0B0D0C0D110D0E0D0B0D0C0D120D090D0E0D0D0D120D120D0D0D0C0D0C050B810B600B5B0B5E0B5B0182D0E72C61027AA80001E4D6\r"
ALARMS = b"~2002460060460002100000000000000000000000000000000005000000000000060000000006800000F066\r"
MANUFACTURER = b"~20024600C04034383130302D3935333801005368656E5A68656E205041434520202020202020F093\r"
MANAGEMENT = b"~20024600B01402E2F4AF000622079EC0F93F\r"
SERIAL = b"~20024600C0220220202020202020202020202020202020F719\r"
SYSTEM_PARAMETERS = b"~20024600B032000E420AF00A8C0D020AAA0834E420AF00A8C00D3409E2F7CCF289\r"
PROTOCOL_VERSION = b"~200246000000FDB2\r"

REPLIES = {
    pylontech.CMD_ANALOG_VALUES: ANALOG,
    pylontech.CMD_ALARM_INFO: ALARMS,
    pylontech.CMD_MANUFACTURER_INFO: MANUFACTURER,
    pylontech.CMD_MANAGEMENT_INFO: MANAGEMENT,
    pylontech.CMD_SERIAL_NUMBER: SERIAL,
    pylontech.CMD_SYSTEM_PARAMETERS: SYSTEM_PARAMETERS,
    pylontech.CMD_PROTOCOL_VERSION: PROTOCOL_VERSION,
}


def info(raw: bytes) -> bytes:
    frame = pylontech.parse_frame(raw)
    assert frame.checksum_ok and frame.length_ok
    return frame.info


class PylontechParsingTests(unittest.TestCase):
    def test_every_captured_reply_passes_both_checksums(self) -> None:
        for raw in REPLIES.values():
            frame = pylontech.parse_frame(raw)
            self.assertTrue(frame.checksum_ok, raw)
            self.assertTrue(frame.length_ok, raw)
            self.assertEqual(frame.address, 2)
            self.assertEqual(frame.code, 0)

    def test_analog_values_decode_to_the_unit_as_installed(self) -> None:
        analog = pylontech.parse_analog_values(info(ANALOG))
        self.assertEqual(analog.pack, 2)
        self.assertEqual(len(analog.cell_voltages_v), 16)
        self.assertEqual(analog.cell_voltages_v[0], 3.339)
        self.assertEqual(analog.cell_voltages_v[7], 3.346)
        self.assertEqual(analog.cell_voltages_v[8], 3.337)
        # Five sensors in 0.1 K: the warm one is the BMS board, the rest the cells.
        self.assertEqual(analog.temperatures_c, [21.4, 18.1, 17.6, 17.9, 17.6])
        self.assertEqual(analog.voltage_v, 53.479)
        # 0x0182 = 386 in 0.1 A, charging (positive).
        self.assertEqual(analog.current_a, 38.6)
        # Capacities arrive in 10 mAh: 31400 is the 314 Ah pack.
        self.assertEqual(analog.remaining_capacity_ah, 113.61)
        self.assertEqual(analog.full_capacity_ah, 314.0)
        self.assertEqual(analog.cycle_count, 1)

    def test_alarm_info_keeps_item_statuses_and_raw_status_words(self) -> None:
        alarms = pylontech.parse_alarm_info(info(ALARMS))
        self.assertEqual(alarms.cell_status, [0] * 16)
        self.assertEqual(alarms.temperature_status, [0] * 5)
        self.assertEqual(
            (alarms.charge_current_status, alarms.voltage_status, alarms.discharge_current_status),
            (0, 0, 0),
        )
        self.assertEqual(alarms.alarms, [])
        # Ten bytes follow the temperatures where Pylontech documents eight; all
        # ten are kept raw, the item statuses come from the first run of three
        # valid codes (bytes 3-5 here, since the 06 in byte 2 is no code), and
        # the last five are the status words: no protection, both MOSFETs on,
        # charge current effective.
        self.assertEqual(alarms.status_bytes.hex(), "00060000000006800000")
        self.assertEqual(alarms.status_words.hex(), "0006800000")
        self.assertEqual(alarms.faults, [])
        self.assertEqual(alarms.mosfet_state, ["discharge", "charge"])

    def test_status_words_follow_the_pylontech_layout_when_there_are_eight_trailing_bytes(self) -> None:
        trailing = bytes([0x00, 0x02, 0x00, 0x81, 0x06, 0x40, 0x00, 0x00])
        alarms = pylontech.parse_alarm_info(bytes([0x00, 0x02, 0x02, 0, 0, 0x01, 0]) + trailing)
        self.assertEqual(alarms.cell_status, [0, 0])
        self.assertEqual(alarms.temperature_status, [0])
        self.assertEqual((alarms.charge_current_status, alarms.voltage_status, alarms.discharge_current_status), (0, 2, 0))
        self.assertEqual(alarms.alarms, ["pack_over_voltage"])
        self.assertEqual(alarms.faults, ["pack_under_voltage", "pack_over_voltage"])
        self.assertEqual(alarms.mosfet_state, ["discharge", "charge"])
        # A byte that is no status code never becomes an alarm.
        odd = pylontech.AlarmInfo(2, [], [], 0x06, 0x00, 0x00, b"")
        self.assertEqual(odd.alarms, [])
        self.assertIsNone(odd.mosfet_state)

    def test_item_statuses_become_named_alarms(self) -> None:
        alarms = pylontech.AlarmInfo(
            pack=2,
            cell_status=[0, 2, 0, 1] + [0] * 12,
            temperature_status=[0, 0xF0, 2, 0, 0],
            charge_current_status=2,
            voltage_status=1,
            discharge_current_status=0,
            status_bytes=b"",
        )
        self.assertEqual(
            alarms.alarms,
            [
                "cell_2_over_voltage",
                "cell_4_under_voltage",
                "temperature_2_sensor_failure",
                "temperature_3_high",
                "charge_over_current",
                "pack_under_voltage",
            ],
        )

    def test_management_info_gives_limits_and_enables(self) -> None:
        management = pylontech.parse_management_info(info(MANAGEMENT))
        self.assertEqual(management.charge_voltage_limit_v, 58.1)
        self.assertEqual(management.discharge_voltage_limit_v, 44.8)
        self.assertEqual(management.charge_current_limit_a, 157.0)
        self.assertEqual(management.discharge_current_limit_a, 195.0)
        self.assertTrue(management.charge_enabled)
        self.assertTrue(management.discharge_enabled)
        self.assertFalse(management.charge_immediately)
        self.assertFalse(management.full_charge_requested)

    def test_manufacturer_and_serial_replies(self) -> None:
        manufacturer = pylontech.parse_manufacturer_info(info(MANUFACTURER))
        self.assertEqual(manufacturer.device_name, "48100-9538")
        self.assertEqual(manufacturer.software_version, "1.0")
        self.assertEqual(manufacturer.manufacturer, "ShenZhen PACE")
        self.assertIsNone(pylontech.parse_serial_number(info(SERIAL)))

    def test_short_replies_are_protocol_errors_not_crashes(self) -> None:
        with self.assertRaises(pylontech.ProtocolError):
            pylontech.parse_analog_values(info(ANALOG)[:20])
        with self.assertRaises(pylontech.ProtocolError):
            pylontech.parse_management_info(b"\x02\xe2")

    def test_reading_carries_the_pack_into_the_collector_model(self) -> None:
        reading = pylontech.build_reading(
            "rack-4",
            2,
            pylontech.parse_analog_values(info(ANALOG)),
            pylontech.parse_alarm_info(info(ALARMS)),
            pylontech.parse_management_info(info(MANAGEMENT)),
            pylontech.parse_manufacturer_info(info(MANUFACTURER)),
            None,
        )
        self.assertEqual(reading.id, "rack-4")
        self.assertEqual(reading.address, 2)
        self.assertEqual(reading.voltage_v, 53.479)
        self.assertEqual(reading.current_a, 38.6)
        self.assertEqual(reading.power_w, 2064.29)
        self.assertEqual(reading.soc_percent, 36.2)
        self.assertEqual(reading.remaining_capacity_ah, 113.61)
        self.assertEqual(reading.full_capacity_ah, 314.0)
        self.assertIsNone(reading.rated_capacity_ah)
        self.assertEqual(reading.cycle_count, 1)
        self.assertEqual(reading.operation_status, "charging")
        self.assertEqual(reading.operation_status_code, 1)
        self.assertEqual(reading.mosfet_state, ["discharge", "charge"])
        self.assertEqual(reading.alarms, [])
        self.assertEqual(reading.alarm_code, 0)
        self.assertEqual(reading.faults, [])
        self.assertEqual(reading.fault_code, 0)
        self.assertEqual(reading.mosfet_temperature_c, 21.4)
        self.assertIsNone(reading.ambient_temperature_c)
        self.assertEqual(reading.cell_count, 16)
        self.assertEqual((reading.high_cell_number, reading.high_cell_voltage_v), (8, 3.346))
        self.assertEqual((reading.low_cell_number, reading.low_cell_voltage_v), (9, 3.337))
        self.assertEqual(reading.average_cell_voltage_v, 3.341)
        self.assertEqual(reading.cell_voltage_delta_v, 0.009)
        # Cell sensors are numbered 2-5 so they line up with temperatures_c.
        self.assertEqual((reading.high_temperature_sensor_number, reading.high_temperature_c), (2, 18.1))
        self.assertEqual((reading.low_temperature_sensor_number, reading.low_temperature_c), (3, 17.6))
        self.assertEqual(reading.average_temperature_c, 17.8)
        self.assertEqual(reading.temperature_sensor_count, 5)
        self.assertEqual(reading.charge_voltage_limit_v, 58.1)
        self.assertEqual(reading.discharge_current_limit_a, 195.0)
        self.assertEqual(reading.firmware_version, "1.0")
        self.assertEqual(reading.bms_model, "48100-9538")
        self.assertEqual(reading.bms_vendor, "ShenZhen PACE")
        self.assertEqual(reading.rs485_protocol, "pylontech")
        self.assertEqual(reading.status_bytes_hex, "00060000000006800000")
        self.assertIsNone(reading.serial_number)
        # The monitor stores readings as dictionaries; the new fields ride along.
        self.assertEqual(reading.to_dict()["bms_vendor"], "ShenZhen PACE")

    def test_operation_status_follows_the_current_sign(self) -> None:
        base = pylontech.parse_analog_values(info(ANALOG))
        for current, expected in ((-12.0, "discharging"), (0.05, "idle"), (0.3, "charging")):
            analog = pylontech.AnalogValues(
                pack=base.pack,
                cell_voltages_v=base.cell_voltages_v,
                temperatures_c=base.temperatures_c,
                current_a=current,
                voltage_v=base.voltage_v,
                remaining_capacity_ah=base.remaining_capacity_ah,
                full_capacity_ah=base.full_capacity_ah,
                cycle_count=base.cycle_count,
            )
            self.assertEqual(pylontech.build_reading("rack-4", 2, analog).operation_status, expected)


class FakeConnection:
    """A serial port that answers like the unit, with a few failure modes."""

    def __init__(self, replies: dict[int, bytes], address: int = 2) -> None:
        self.replies = replies
        self.address = address
        self.requests: list[bytes] = []

    def reset_input_buffer(self) -> None:
        pass

    def write(self, request: bytes) -> None:
        self.requests.append(request)

    def flush(self) -> None:
        pass

    def read_until(self, terminator: bytes, size: int) -> bytes:
        frame = pylontech.parse_frame(self.requests[-1])
        if frame.address != self.address:
            return b""
        return self.replies.get(frame.code, b"")

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *exc_info) -> None:
        pass


class PylontechClientTests(unittest.TestCase):
    def _client(self, connection: FakeConnection) -> pylontech.PylontechClient:
        client = pylontech.PylontechClient(SerialConnectionSettings(port="/dev/ttyUSB2"))

        class FakeSerialModule:
            @staticmethod
            def Serial(**kwargs):
                connection.kwargs = kwargs
                return connection

        import sys

        sys.modules["serial"] = FakeSerialModule  # type: ignore[assignment]
        self.addCleanup(sys.modules.pop, "serial", None)
        return client

    def test_reads_the_pack_with_read_commands_only(self) -> None:
        connection = FakeConnection(REPLIES)
        reading = self._client(connection).read_pack_status(2, "rack-4")
        self.assertEqual(reading.soc_percent, 36.2)
        self.assertEqual(reading.bms_vendor, "ShenZhen PACE")
        sent = [pylontech.parse_frame(request) for request in connection.requests]
        self.assertEqual(
            [frame.code for frame in sent],
            [
                pylontech.CMD_ANALOG_VALUES,
                pylontech.CMD_ALARM_INFO,
                pylontech.CMD_MANAGEMENT_INFO,
                pylontech.CMD_MANUFACTURER_INFO,
                pylontech.CMD_SERIAL_NUMBER,
            ],
        )
        self.assertTrue(all(frame.address == 2 and frame.version == 0x20 for frame in sent))
        self.assertEqual(connection.kwargs["port"], "/dev/ttyUSB2")
        self.assertEqual(connection.kwargs["baudrate"], 9600)

    def test_a_silent_pack_times_out(self) -> None:
        connection = FakeConnection(REPLIES, address=5)
        with self.assertRaises(TimeoutError):
            self._client(connection).read_pack_status(2, "rack-4")

    def test_missing_detail_replies_still_give_a_reading(self) -> None:
        connection = FakeConnection({pylontech.CMD_ANALOG_VALUES: ANALOG})
        reading = self._client(connection).read_pack_status(2, "rack-4")
        self.assertEqual(reading.voltage_v, 53.479)
        self.assertEqual(reading.mosfet_state, [])
        self.assertIsNone(reading.fault_code)
        self.assertIsNone(reading.charge_voltage_limit_v)
        self.assertIsNone(reading.firmware_version)
        self.assertIsNone(reading.alarm_code)
        # With only the management reply, the enables stand in for the switches.
        connection = FakeConnection({pylontech.CMD_ANALOG_VALUES: ANALOG, pylontech.CMD_MANAGEMENT_INFO: MANAGEMENT})
        reading = self._client(connection).read_pack_status(2, "rack-4")
        self.assertEqual(reading.mosfet_state, ["charge", "discharge"])
        self.assertEqual(reading.charge_voltage_limit_v, 58.1)

    def test_a_refused_or_corrupt_analog_reply_is_an_error(self) -> None:
        refused = pylontech.build_frame(0x20, 2, 0x04)
        with self.assertRaises(pylontech.ProtocolError):
            self._client(FakeConnection({pylontech.CMD_ANALOG_VALUES: refused})).read_pack_status(2, "rack-4")
        corrupt = ANALOG[:-5] + b"0" + ANALOG[-4:]
        with self.assertRaises(pylontech.ProtocolError):
            self._client(FakeConnection({pylontech.CMD_ANALOG_VALUES: corrupt})).read_pack_status(2, "rack-4")


if __name__ == "__main__":
    unittest.main()
