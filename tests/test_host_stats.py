from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from batteries_query_service.host import (
    PROC_LOADAVG,
    PROC_MEMINFO,
    PROC_STAT,
    PROC_UPTIME,
    THROTTLED_FILE,
    HostStats,
    decode_throttle_flags,
)

ZONE0 = Path("/sys/class/thermal/thermal_zone0")
ZONE1 = Path("/sys/class/thermal/thermal_zone1")


def fake_host(files: dict[Path, str], zones=(), disk=None) -> HostStats:
    def read_text(path: Path) -> str:
        try:
            return files[Path(path)]
        except KeyError as exc:
            raise FileNotFoundError(str(path)) from exc

    def statvfs(path: str):
        if disk is None:
            raise OSError("no such mount")
        return SimpleNamespace(f_frsize=4096, f_blocks=disk[0], f_bavail=disk[1])

    return HostStats(
        "/data", read_text=read_text, thermal_zones=lambda: list(zones), statvfs=statvfs
    )


def stat_line(user, system, idle, iowait):
    return f"cpu  {user} 0 {system} {idle} {iowait} 0 0 0 0 0\ncpu0 1 2 3 4 5 6 7 8 9 0\n"


class HostStatsTests(unittest.TestCase):
    def test_cpu_load_is_the_change_between_two_samples(self) -> None:
        files = {PROC_STAT: stat_line(100, 50, 850, 0)}
        host = fake_host(files)
        # One reading of a cumulative counter says nothing about the rate.
        self.assertIsNone(host.sample()["cpu_percent"])
        # 60 busy ticks out of 400 since the last sample.
        files[PROC_STAT] = stat_line(140, 70, 1180, 10)
        self.assertEqual(host.sample()["cpu_percent"], 15.0)

    def test_temperature_prefers_the_soc_zone_and_reads_millidegrees(self) -> None:
        files = {
            ZONE0 / "type": "cpu-thermal\n", ZONE0 / "temp": "46123\n",
            ZONE1 / "type": "nvme\n", ZONE1 / "temp": "61000\n",
        }
        host = fake_host(files, zones=(ZONE1, ZONE0))
        self.assertEqual(host.sample()["cpu_temperature_c"], 46.1)

    def test_any_zone_will_do_when_none_is_named_cpu(self) -> None:
        files = {ZONE1 / "type": "acpitz\n", ZONE1 / "temp": "38500\n"}
        self.assertEqual(fake_host(files, zones=(ZONE1,)).sample()["cpu_temperature_c"], 38.5)

    def test_memory_is_what_is_not_available(self) -> None:
        files = {PROC_MEMINFO: "MemTotal:  4000000 kB\nMemFree: 100 kB\nMemAvailable: 2500000 kB\n"}
        sample = fake_host(files).sample()
        self.assertEqual(sample["memory_percent"], 37.5)
        self.assertEqual(sample["memory_total_mb"], 3906)
        self.assertEqual(sample["memory_used_mb"], 1465)

    def test_load_uptime_and_disk(self) -> None:
        files = {PROC_LOADAVG: "0.42 0.31 0.25 1/210 4321\n", PROC_UPTIME: "123456.78 400000.00\n"}
        sample = fake_host(files, disk=(1_000_000, 250_000)).sample()
        self.assertEqual((sample["load_1m"], sample["load_5m"], sample["load_15m"]), (0.42, 0.31, 0.25))
        self.assertEqual(sample["uptime_seconds"], 123456)
        self.assertEqual(sample["disk_percent"], 75.0)
        self.assertEqual(sample["disk_free_gb"], 1.02)
        self.assertEqual(sample["disk_total_gb"], 4.1)

    def test_throttle_flags_name_both_the_current_and_the_remembered_bits(self) -> None:
        # Bits 0 and 2 now, bits 16 and 18 since boot: 0x50005.
        files = {THROTTLED_FILE: "0x50005\n"}
        sample = fake_host(files).sample()
        self.assertEqual(sample["throttled"]["active"], ["under_voltage", "throttled"])
        self.assertEqual(sample["throttled"]["occurred"], ["under_voltage", "throttled"])
        self.assertEqual(decode_throttle_flags(0)["active"], [])
        self.assertEqual(decode_throttle_flags(0x80000)["occurred"], ["soft_temperature_limit"])

    def test_a_host_with_none_of_the_files_still_answers(self) -> None:
        # A non-Pi host, or a container without sysfs: every field is None and
        # nothing raises, so the poll that carries it is unaffected.
        sample = fake_host({}).sample()
        for key in ("cpu_percent", "cpu_temperature_c", "memory_percent", "load_1m",
                    "uptime_seconds", "disk_percent", "throttled"):
            with self.subTest(key=key):
                self.assertIsNone(sample[key])
        self.assertTrue(sample["sampled_at"].endswith("Z"))

    def test_garbage_in_a_file_is_treated_like_a_missing_file(self) -> None:
        files = {PROC_STAT: "not a stat file\n", PROC_MEMINFO: "MemTotal: lots\n",
                 ZONE0 / "temp": "warm\n"}
        sample = fake_host(files, zones=(ZONE0,)).sample()
        self.assertIsNone(sample["cpu_percent"])
        self.assertIsNone(sample["memory_percent"])
        self.assertIsNone(sample["cpu_temperature_c"])


if __name__ == "__main__":
    unittest.main()
