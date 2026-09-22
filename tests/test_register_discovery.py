from __future__ import annotations

import unittest

from batteries_query_service.register_discovery import (
    READ_FAILED,
    READ_REFUSED,
    UNDEFINED_REGISTER,
    classify_read_failure,
    classify_samples,
    compare_snapshots,
    format_range,
    map_readable_blocks,
    parse_ranges,
    register_views,
)


class IllegalDataAddressError(Exception):
    """umodbus raises this class, carrying its own docstring, through pysolarmanv5.

    The data address received in the request is not an allowable address for
    the server.
    """


class FakeInverter:
    """An inverter that exposes islands and refuses any read touching a gap.

    This is the behaviour that defeats a fixed-chunk sweep: the refusal is about
    the whole request, so one undefined address hides every readable register
    beside it.
    """

    def __init__(self, islands, values=None, flaky=()):
        self.defined = {
            address
            for start, count in islands
            for address in range(start, start + count)
        }
        self.values = values or {}
        # Any read touching one of these times out: a link that drops the
        # frame every time a particular register is asked for.
        self.flaky = set(flaky)
        self.reads = []

    def read(self, start, count):
        self.reads.append((start, count))
        if any(a in self.flaky for a in range(start, start + count)):
            raise TimeoutError("no response")
        if any(a not in self.defined for a in range(start, start + count)):
            raise IllegalDataAddressError()
        return [self.values.get(a, 0) for a in range(start, start + count)]


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


class ReadFailureTests(unittest.TestCase):
    def test_a_refusal_is_told_apart_from_a_link_problem(self) -> None:
        # Both stacks' wording for Modbus exception 0x02.
        self.assertEqual(
            classify_read_failure(IllegalDataAddressError()), READ_REFUSED
        )
        self.assertEqual(
            classify_read_failure(
                RuntimeError("Inverter rejected the read with Modbus exception 2")
            ),
            READ_REFUSED,
        )
        # Anything else is the link, and must not be read as a gap: a timeout
        # that mapped to "refused" would carve a hole that is not in the
        # inverter, and the next snapshot would skip real registers.
        for other in (TimeoutError("timed out"), RuntimeError(""),
                      RuntimeError("V5 frame contains an invalid checksum")):
            with self.subTest(other=other):
                self.assertEqual(classify_read_failure(other), READ_FAILED)


class MapReadableBlocksTests(unittest.TestCase):
    def test_it_finds_an_island_a_fixed_chunk_sweep_reports_as_refused(self) -> None:
        # The shape a live run hit: the identity block is readable but sits
        # across the 60-register chunk grid, so no whole chunk answers and the
        # sweep concluded the whole 0x1000 range was unreadable.
        inverter = FakeInverter([(0x1219, 1), (0x1230, 40)])
        for offset in range(0, 0x400, 60):
            with self.assertRaises(IllegalDataAddressError):
                inverter.read(0x1000 + offset, min(60, 0x400 - offset))

        result = map_readable_blocks(
            inverter.read, [(0x1000, 0x400)], stride=8, max_reads=5000
        )
        # The wide block comes back with both edges exact; the single register
        # is narrower than the stride, so it is the documented blind spot.
        self.assertEqual(result["ranges"], ["0x1230:0x1257"])

        fine = map_readable_blocks(
            inverter.read, [(0x1000, 0x400)], stride=1, max_reads=5000
        )
        self.assertEqual(fine["ranges"], ["0x1219:0x1219", "0x1230:0x1257"])

    def test_every_block_at_least_a_stride_wide_is_found(self) -> None:
        # The guarantee the stride buys, checked at every offset a block of
        # exactly that width could sit at.
        for offset in range(0, 32):
            inverter = FakeInverter([(0x2000 + offset, 8)])
            result = map_readable_blocks(
                inverter.read, [(0x2000, 0x80)], stride=8, max_reads=5000
            )
            with self.subTest(offset=offset):
                self.assertEqual(
                    result["ranges"], [format_range(0x2000 + offset, 8)]
                )

    def test_walking_the_edges_costs_far_less_than_reading_every_register(self) -> None:
        inverter = FakeInverter([(0x3100, 0x53)])
        result = map_readable_blocks(
            inverter.read, [(0x3100, 0x100)], stride=8, max_reads=5000
        )
        self.assertEqual(result["ranges"], ["0x3100:0x3152"])
        # 256 registers scanned, a 83-register block resolved to both edges,
        # for a fraction of the reads a register-by-register walk would take.
        self.assertLess(result["reads"], 60)

    def test_a_probe_that_lands_mid_block_still_finds_both_edges(self) -> None:
        inverter = FakeInverter([(0x1207, 0x51)])  # 0x1207..0x1257
        result = map_readable_blocks(
            inverter.read, [(0x1200, 0x100)], stride=8, max_reads=5000
        )
        self.assertEqual(result["ranges"], ["0x1207:0x1257"])

    def test_an_answered_read_keeps_the_values_it_already_returned(self) -> None:
        inverter = FakeInverter(
            [(0x3100, 0x53)], values={0x3100: 7, 0x3152: UNDEFINED_REGISTER}
        )
        result = map_readable_blocks(
            inverter.read, [(0x3100, 0x53)], stride=8, max_reads=5000
        )
        self.assertEqual(result["values"][0x3100], 7)
        self.assertEqual(result["values"][0x3152], UNDEFINED_REGISTER)

    def test_touching_blocks_are_reported_as_one_island(self) -> None:
        inverter = FakeInverter([(0x2000, 0x40), (0x2040, 0x38)])
        result = map_readable_blocks(
            inverter.read, [(0x2000, 0x100)], stride=8, max_reads=5000
        )
        self.assertEqual(result["ranges"], ["0x2000:0x2077"])

    def test_a_link_failure_is_not_recorded_as_a_gap(self) -> None:
        def flaky(start, count):
            raise TimeoutError("no response")

        result = map_readable_blocks(
            flaky, [(0x1000, 32)], stride=8, retries=1, max_reads=5000
        )
        self.assertEqual(result["readable"], [])
        self.assertEqual(result["refused"], [])
        # The four probe addresses, each tried twice, reported as unproven
        # rather than as holes in the inverter's map.
        self.assertEqual(result["unverified"], [(0x1000, 1), (0x1008, 1),
                                                (0x1010, 1), (0x1018, 1)])
        self.assertEqual(result["reads"], 8)

    def test_a_link_failure_during_an_edge_walk_is_doubt_not_an_edge(self) -> None:
        # A 20-register block whose last register the link never delivers.
        # Every read that reaches 0x1013 times out; none is refused.
        inverter = FakeInverter([(0x1000, 20)], flaky={0x1013})
        result = map_readable_blocks(
            inverter.read, [(0x1000, 0x40)], stride=8, max_reads=5000
        )
        # Treating that timeout as a refusal would have placed the block's
        # edge one register short and said nothing -- the register is then
        # missing from every snapshot built on the map. Instead the walk stops
        # at the last address it proved and names what it could not settle.
        self.assertEqual(result["ranges"], ["0x1000:0x1010"])
        unverified = {
            a for s, c in result["unverified"] for a in range(s, s + c)
        }
        self.assertIn(0x1013, unverified)
        self.assertIn(0x1011, unverified)
        # The register the link kept dropping is never written down as a gap;
        # the only refusals are the probes past the block's true end.
        refused = {a for s, c in result["refused"] for a in range(s, s + c)}
        self.assertTrue(refused)
        self.assertTrue(all(address > 0x1013 for address in refused))

    def test_the_same_holds_walking_down_from_a_probe(self) -> None:
        inverter = FakeInverter([(0x1000, 20)], flaky={0x1000})
        result = map_readable_blocks(
            inverter.read, [(0x1000, 0x40)], stride=8, max_reads=5000
        )
        self.assertEqual(result["ranges"], ["0x1008:0x1013"])
        unverified = {
            a for s, c in result["unverified"] for a in range(s, s + c)
        }
        self.assertTrue({0x1000, 0x1007} <= unverified)
        refused = {a for s, c in result["refused"] for a in range(s, s + c)}
        self.assertTrue(refused)
        self.assertTrue(all(address > 0x1013 for address in refused))

    def test_a_doubt_a_later_probe_settles_is_dropped(self) -> None:
        # The link drops exactly one frame, on the first read past 0x1020, and
        # is fine afterwards. The next probe walks the whole block, so nothing
        # is left in doubt and the report says so.
        calls = {"n": 0}
        inverter = FakeInverter([(0x1000, 0x40)])

        def read(start, count):
            if 0x1020 in range(start, start + count) and calls["n"] < 2:
                calls["n"] += 1
                raise TimeoutError("dropped")
            return inverter.read(start, count)

        result = map_readable_blocks(read, [(0x1000, 0x40)], stride=8, max_reads=5000)
        self.assertEqual(result["ranges"], ["0x1000:0x103F"])
        self.assertEqual(result["unverified"], [])

    def test_the_budget_bounds_the_sweep_and_says_what_it_missed(self) -> None:
        inverter = FakeInverter([])
        result = map_readable_blocks(
            inverter.read, [(0x1000, 0x400)], stride=8, max_reads=10
        )
        self.assertTrue(result["budget_exhausted"])
        self.assertEqual(result["reads"], 10)
        self.assertLessEqual(len(inverter.reads), 10)
        # What it did not reach is named, not silently folded in with the gaps.
        self.assertTrue(result["unscanned"])
        self.assertGreater(sum(count for _, count in result["unscanned"]), 0)

    def test_a_later_range_is_reported_unscanned_once_the_budget_is_gone(self) -> None:
        inverter = FakeInverter([])
        result = map_readable_blocks(
            inverter.read, [(0x1000, 0x80), (0x2000, 0x80)], stride=8, max_reads=4
        )
        self.assertIn((0x2000, 0x80), result["unscanned"])

    def test_a_map_range_can_be_handed_straight_back_to_the_scanner(self) -> None:
        inverter = FakeInverter([(0x1234, 8)])
        result = map_readable_blocks(
            inverter.read, [(0x1200, 0x100)], stride=8, max_reads=5000
        )
        self.assertEqual(parse_ranges(result["ranges"], []), [(0x1234, 8)])

    def test_format_range_is_inclusive_on_both_ends(self) -> None:
        self.assertEqual(format_range(0x1234, 6), "0x1234:0x1239")
        self.assertEqual(format_range(0x1219, 1), "0x1219:0x1219")

    def test_it_refuses_a_nonsensical_sweep(self) -> None:
        inverter = FakeInverter([])
        for kwargs in ({"stride": 0}, {"max_reads": 0}, {"edge_read": 0},
                       {"edge_read": 126}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    map_readable_blocks(inverter.read, [(0, 8)], **kwargs)


if __name__ == "__main__":
    unittest.main()
