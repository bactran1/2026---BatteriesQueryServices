from __future__ import annotations

import unittest

from batteries_query_service import pylontech_probe as probe


class PylontechFrameTests(unittest.TestCase):
    def test_builds_the_canonical_analog_request(self) -> None:
        # The textbook "get analog values of pack 2" frame from the Pylontech
        # RS485 protocol document, version 0x20.
        self.assertEqual(
            probe.build_request(0x20, 2, 0x42, True),
            b"~20024642E00202FD33\r",
        )

    def test_length_field_checks_its_own_nibbles(self) -> None:
        self.assertEqual(probe.length_field(""), "0000")
        self.assertEqual(probe.length_field("02"), "E002")
        # 0x123 characters: nibbles 1 + 2 + 3 = 6, two's complement in 4 bits is 0xA.
        self.assertEqual(probe.length_field("0" * 0x123), "A123")

    def test_commands_without_an_address_carry_no_info(self) -> None:
        frame = probe.build_request(0x20, 4, 0x51, False)
        self.assertEqual(frame, b"~200446510000FDAA\r")
        parsed = probe.parse_frame(frame)
        self.assertEqual(parsed.info_hex, "")
        self.assertTrue(parsed.checksum_ok)
        self.assertTrue(parsed.length_ok)

    def test_parses_a_reply_and_flags_a_bad_checksum(self) -> None:
        # A reply has the same shape as a request with the return code where
        # the command was; build one for pack 4 answering "ok" with four bytes.
        reply = probe.build_frame(0x25, 4, 0x00, "11223344")
        parsed = probe.parse_frame(reply)
        self.assertEqual(parsed.version, 0x25)
        self.assertEqual(parsed.address, 4)
        self.assertEqual(parsed.cid1, 0x46)
        self.assertEqual(parsed.return_code, "ok")
        self.assertEqual(parsed.info_hex, "11223344")
        self.assertTrue(parsed.checksum_ok)
        self.assertTrue(parsed.length_ok)

        damaged = reply[:-5] + b"0" + reply[-4:]
        self.assertFalse(probe.parse_frame(damaged).checksum_ok)
        self.assertEqual(probe.parse_frame(probe.build_frame(0x20, 4, 0x90)).return_code, "address error")

    def test_rejects_frames_that_are_not_frames(self) -> None:
        with self.assertRaises(probe.FrameError):
            probe.parse_frame(b"not a frame\r")
        with self.assertRaises(probe.FrameError):
            probe.parse_frame(b"~2004\r")

    def test_manufacturer_text_is_shown_when_the_info_is_text(self) -> None:
        info = "P16S200A-61056-1.10".encode("ascii").hex()
        self.assertEqual(probe.printable(info), "P16S200A-61056-1.10")
        self.assertEqual(probe.printable("0001"), "")

    def test_only_read_commands_are_ever_sent(self) -> None:
        # The PACE and Pylontech write and control commands live outside this
        # set; the probe must stay a reader.
        codes = {cid2 for _, cid2, _ in probe.COMMANDS}
        self.assertEqual(codes, {0x42, 0x44, 0x47, 0x4F, 0x51, 0x92, 0x93})

    def test_address_and_version_specs(self) -> None:
        self.assertEqual(probe.parse_addresses("0-3,0x10, 7"), [0, 1, 2, 3, 16, 7])
        self.assertEqual(probe.parse_versions("20,25"), [0x20, 0x25])
        with self.assertRaises(ValueError):
            probe.parse_addresses("300")


class ProbeRunTests(unittest.TestCase):
    def test_probe_runs_every_read_command_on_a_pack_that_answers(self) -> None:
        sent: list[bytes] = []

        class FakeLink:
            def transact(self, request: bytes) -> bytes:
                sent.append(request)
                parsed = probe.parse_frame(request)
                if parsed.address != 4 or parsed.version != 0x20:
                    return b""
                return probe.build_frame(0x20, 4, 0x00, "0A0B")

        found = probe.probe(FakeLink(), [0x20, 0x25], [3, 4], pause=0, verbose=False)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["address"], 4)
        self.assertEqual(found[0]["version"], 0x20)
        self.assertEqual(set(found[0]["replies"]), {name for name, _, _ in probe.COMMANDS})
        self.assertTrue(all(result["checksum_ok"] for result in found[0]["replies"].values()))
        # Silent addresses and versions get one analog request each and nothing more.
        self.assertEqual(len(sent), 3 + len(probe.COMMANDS))


if __name__ == "__main__":
    unittest.main()
