from __future__ import annotations

import unittest

from battery_monitor.rack_state import rack_state_of_charge


def pack(soc, remaining=None, full=None, rated=None):
    reading = {"soc_percent": soc}
    if remaining is not None:
        reading["remaining_capacity_ah"] = remaining
    if full is not None:
        reading["full_capacity_ah"] = full
    if rated is not None:
        reading["rated_capacity_ah"] = rated
    return reading


class RackStateOfChargeTests(unittest.TestCase):
    def test_packs_of_different_sizes_count_for_their_capacity(self) -> None:
        # Three 100 Ah packs at 20% and a 314 Ah pack at 80%: the rack holds
        # 311.2 Ah of 614 Ah, 50.7%, not the 35% an equal-weight mean gives.
        readings = [pack(20, 20, 100)] * 3 + [pack(80, 251.2, 314)]
        self.assertEqual(rack_state_of_charge(readings), (50.7, "capacity"))

    def test_identical_packs_get_the_same_figure_either_way(self) -> None:
        readings = [pack(20, 20, 100), pack(80, 80, 100)]
        self.assertEqual(rack_state_of_charge(readings), (50.0, "capacity"))

    def test_a_pack_without_capacity_falls_back_to_the_plain_mean(self) -> None:
        readings = [pack(20, 20, 100), pack(80)]
        self.assertEqual(rack_state_of_charge(readings), (50.0, "equal"))

    def test_rated_capacity_stands_in_for_a_missing_full_charge_figure(self) -> None:
        readings = [pack(50, 157, rated=314), pack(100, 100, 100)]
        self.assertEqual(rack_state_of_charge(readings), (62.1, "capacity"))

    def test_packs_without_a_state_of_charge_are_left_out(self) -> None:
        readings = [pack(40, 40, 100), {"remaining_capacity_ah": 50, "full_capacity_ah": 100}, {}]
        self.assertEqual(rack_state_of_charge(readings), (40.0, "capacity"))
        self.assertEqual(rack_state_of_charge([{}, {"soc_percent": "n/a"}]), (None, None))
        self.assertEqual(rack_state_of_charge([]), (None, None))


if __name__ == "__main__":
    unittest.main()
