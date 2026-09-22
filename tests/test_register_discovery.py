from __future__ import annotations

import unittest

from batteries_query_service.register_discovery import (
    UNDEFINED_REGISTER,
    classify_samples,
    compare_snapshots,
    parse_ranges,
    register_views,
)


def snapshot(label, stable, volatile=(), captured_at="2026-09-21T00:00:00Z"):
    return {
        "label": label,
        "captured_at": captured_at,
        "stable": {str(k): v for k, v in stable.items()},
        "volatile": list(volatile),
    }


class ClassifySamplesTests(unittest.TestCase):
    def test_a_register_that_moves_on_its_own_is_telemetry_not_a_setting(self) -> None:
        # Live power wanders between reads; the work mode does not.
        samples = [
            {0x1200: 3, 0x3110: 1450},
            {0x1200: 3, 0x3110: 1502},
            {0x1200: 3, 0x3110: 1388},
        ]
        result = classify_samples(samples)
        self.assertEqual(result["stable"], {0x1200: 3})
        self.assertEqual(result["volatile"], [0x3110])
        self.assertEqual(result["samples"], 3)

    def test_unmapped_registers_are_dropped_rather_than_called_stable(self) -> None:
        samples = [{0x1200: UNDEFINED_REGISTER}, {0x1200: UNDEFINED_REGISTER}]
        result = classify_samples(samples)
        self.assertEqual(result["stable"], {})
        self.assertEqual(result["volatile"], [])

    def test_a_register_missing_from_one_sample_is_incomplete_not_stable(self) -> None:
        # A dropped read is not evidence of stability.
        samples = [{0x1200: 3, 0x1201: 7}, {0x1200: 3}, {0x1200: 3, 0x1201: 7}]
        result = classify_samples(samples)
        self.assertEqual(result["stable"], {0x1200: 3})
        self.assertEqual(result["incomplete"], [0x1201])

    def test_at_least_one_sample_is_required(self) -> None:
        with self.assertRaises(ValueError):
            classify_samples([])


class CompareSnapshotsTests(unittest.TestCase):
    def test_the_one_register_the_mode_change_moved_is_reported(self) -> None:
        before = snapshot("SELFCONSUME", {0x1200: 0, 0x1201: 55, 0x1202: 3})
        after = snapshot("BAT PRIORITY", {0x1200: 2, 0x1201: 55, 0x1202: 3})
        result = compare_snapshots(before, after)

        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["register"], 0x1200)
        self.assertEqual(candidate["before"]["unsigned"], 0)
        self.assertEqual(candidate["after"]["unsigned"], 2)
        self.assertEqual(result["baseline_label"], "SELFCONSUME")
        self.assertEqual(result["current_label"], "BAT PRIORITY")
        self.assertTrue(any("single candidate" in note for note in result["notes"]))

    def test_telemetry_that_moved_is_excluded_from_the_candidates(self) -> None:
        # The inverter kept running between the two snapshots; none of that
        # may reach the result.
        before = snapshot("SELFCONSUME", {0x1200: 0}, volatile=[0x3110, 0x3113])
        after = snapshot("BAT PRIORITY", {0x1200: 2}, volatile=[0x3110, 0x3120])
        result = compare_snapshots(before, after)

        self.assertEqual([c["register"] for c in result["candidates"]], [0x1200])
        self.assertEqual(result["ignored_volatile"], [0x3110, 0x3113, 0x3120])
        self.assertTrue(any("excluded as telemetry" in n for n in result["notes"]))

    def test_a_register_readable_on_only_one_side_is_never_a_candidate(self) -> None:
        before = snapshot("SELFCONSUME", {0x1200: 0, 0x1300: 9})
        after = snapshot("BAT PRIORITY", {0x1200: 0, 0x1400: 9})
        result = compare_snapshots(before, after)

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["unreadable_on_one_side"], [0x1300, 0x1400])

    def test_several_candidates_ask_for_a_switch_back_to_disambiguate(self) -> None:
        before = snapshot("SELFCONSUME", {0x1200: 0, 0x1201: 10, 0x1202: 5})
        after = snapshot("BAT PRIORITY", {0x1200: 2, 0x1201: 11, 0x1202: 5})
        result = compare_snapshots(before, after)

        self.assertEqual(len(result["candidates"]), 2)
        self.assertTrue(any("switching back" in note for note in result["notes"]))

    def test_no_change_says_so_instead_of_inventing_a_register(self) -> None:
        before = snapshot("SELFCONSUME", {0x1200: 0})
        after = snapshot("SELFCONSUME", {0x1200: 0})
        result = compare_snapshots(before, after)

        self.assertEqual(result["candidates"], [])
        self.assertTrue(
            any("No stable register changed" in note for note in result["notes"])
        )

    def test_an_empty_side_is_called_out_as_a_link_problem(self) -> None:
        result = compare_snapshots(snapshot("A", {}), snapshot("B", {0x1200: 1}))
        self.assertEqual(result["candidates"], [])
        self.assertTrue(any("no stable registers" in n for n in result["notes"]))

    def test_every_result_repeats_that_nothing_was_written(self) -> None:
        result = compare_snapshots(
            snapshot("A", {0x1200: 0}), snapshot("B", {0x1200: 1})
        )
        self.assertTrue(any("Nothing here writes" in n for n in result["notes"]))


class HelperTests(unittest.TestCase):
    def test_register_views_cover_the_ways_a_setting_might_be_encoded(self) -> None:
        self.assertEqual(register_views(2)["hex"], "0x0002")
        self.assertEqual(register_views(0xFFFE)["signed"], -2)
        self.assertEqual(register_views(255)["tenths"], 25.5)

    def test_ranges_accept_hex_and_decimal_and_reject_nonsense(self) -> None:
        self.assertEqual(parse_ranges(["0x1000:0x1003"], []), [(4096, 4)])
        self.assertEqual(parse_ranges(["10:12"], []), [(10, 3)])
        self.assertEqual(parse_ranges(None, ["0:1"]), [(0, 2)])
        for bad in ("5:1", "nonsense", "0:70000"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_ranges([bad], [])


if __name__ == "__main__":
    unittest.main()
