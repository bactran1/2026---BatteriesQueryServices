from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("battery_kiosk", ROOT / "kiosk/kiosk.py")
assert SPEC and SPEC.loader
kiosk = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = kiosk
SPEC.loader.exec_module(kiosk)


class KioskTests(unittest.TestCase):
    def test_url_accepts_monitor_paths_and_ipv6(self):
        for url in ("http://192.168.10.10:8080", "https://monitor.local/rack?theme=dark&lang=vi",
                    "http://[::1]:8080/"):
            self.assertEqual(kiosk.validate_url(url), url)

    def test_url_rejects_unsafe_or_malformed_values(self):
        for url in ("", "monitor.local", "file:///etc/passwd", "http://", "http://host:bad",
                    "http://host:65536", "http://u:p@host", "http://host/\n", "http://host/a b"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                kiosk.validate_url(url)

    def test_brief_outage_preserves_dashboard_then_recovers(self):
        state = kiosk.Availability()
        self.assertFalse(state.online)
        self.assertFalse(state.update(False))
        self.assertTrue(state.update(True))
        self.assertTrue(state.online)
        self.assertFalse(state.update(False))
        self.assertFalse(state.update(False))
        self.assertTrue(state.online)
        self.assertTrue(state.update(False))
        self.assertFalse(state.online)
        self.assertTrue(state.update(True))
        self.assertEqual(state.failures, 0)

    def test_success_clears_failure_streak(self):
        state = kiosk.Availability()
        for result in (True, False, False, True, False, False):
            state.update(result)
        self.assertTrue(state.online)

    def test_browser_command_keeps_sandbox_gpu_and_dedicated_profile(self):
        url = "http://monitor.local:8080/?a=1&b=2"
        settings = kiosk.Settings(url, "/usr/bin/chromium")
        command = kiosk.browser_command(settings, url, Path("/home/battery-kiosk/snap/chromium/common/profile"))
        self.assertEqual(command[-1], url)
        self.assertIn("--kiosk", command)
        self.assertIn("--ozone-platform=x11", command)
        self.assertNotIn("--no-sandbox", command)
        self.assertNotIn("--disable-gpu", command)
        self.assertNotIn("--incognito", command)
        self.assertEqual(len([arg for arg in command if arg.startswith("--user-data-dir=")]), 1)

    def test_invalid_browser_and_refresh_settings_are_rejected(self):
        for browser, minutes in (("chromium", 360), ("/usr/bin/chromium", -1), ("/usr/bin/chromium", 100000)):
            with self.subTest(browser=browser, minutes=minutes), self.assertRaises(ValueError):
                kiosk.Settings("http://monitor:8080/", browser, minutes)

    def test_configuration_is_json_not_executable_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            result = subprocess.run([sys.executable, str(ROOT / "kiosk/kiosk.py"),
                                     "--write-config", str(path), "--url", "http://monitor/?a=1&b=2",
                                     "--browser", "/usr/bin/chromium", "--refresh-minutes", "0"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(path.read_text())
            self.assertEqual(data["url"], "http://monitor/?a=1&b=2")
            self.assertEqual(data["refresh_minutes"], 0)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_invalid_settings_do_not_replace_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("original")
            result = subprocess.run([sys.executable, str(ROOT / "kiosk/kiosk.py"),
                                     "--write-config", str(path), "--url", "file:///tmp/a",
                                     "--browser", "/usr/bin/chromium"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), "original")

    def test_waiting_page_and_actual_http_probe(self):
        server = kiosk.ThreadingHTTPServer(("127.0.0.1", 0), kiosk.WaitingHandler)
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/"
            self.assertTrue(kiosk.reachable(url))
            with urlopen(url, timeout=2) as response:
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertIn(b"Connecting to your monitor", response.read())
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        self.assertFalse(kiosk.reachable(url))

    def test_http_failures_are_not_reported_as_online(self):
        with patch.object(kiosk, "urlopen", side_effect=kiosk.HTTPError("http://host", 503, "down", {}, None)):
            self.assertFalse(kiosk.reachable("http://host"))

    def test_lightweight_window_manager_has_no_launcher_bindings(self):
        tree = ET.parse(ROOT / "kiosk/openbox.xml")
        namespace = {"ob": "http://openbox.org/3.4/rc"}
        self.assertIsNotNone(tree.find("ob:keyboard", namespace))
        self.assertFalse(tree.findall(".//ob:keybind", namespace))

    def test_supervisor_starts_waiting_then_recovers_after_outage(self):
        settings = kiosk.Settings("http://monitor:8080/", "/usr/bin/chromium", 0)
        event = MagicMock()
        event.is_set.side_effect = [False] * 7 + [True]
        clock = [0]
        event.wait.side_effect = lambda _timeout: clock.__setitem__(0, clock[0] + 12)
        server = MagicMock(server_port=54321)
        process = MagicMock()
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(kiosk.threading, "Event", return_value=event), \
                patch.object(kiosk.threading, "Thread"), \
                patch.object(kiosk, "ThreadingHTTPServer", return_value=server), \
                patch.object(kiosk.signal, "signal"), \
                patch.object(kiosk.subprocess, "run"), \
                patch.object(kiosk.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(kiosk, "reachable", side_effect=[False, True, True, False, False, False, True]), \
                patch.object(kiosk, "start_process", return_value=process) as start, \
                patch.object(kiosk, "stop_process") as stop:
            kiosk.supervise(settings, Path(directory))
            commands = [call.args[0] for call in start.call_args_list]
            targets = [command[-1] for command in commands if command[0] == settings.browser]
            self.assertEqual(targets, ["http://127.0.0.1:54321/", settings.url,
                                       "http://127.0.0.1:54321/", settings.url])
            self.assertGreaterEqual(stop.call_count, 5)
            server.shutdown.assert_called_once()
            server.server_close.assert_called_once()

    def test_supervisor_relaunches_exited_browser(self):
        settings = kiosk.Settings("http://monitor:8080/", "/usr/bin/chromium", 0)
        event = MagicMock()
        event.is_set.side_effect = [False] * 4 + [True]
        clock = [0]
        event.wait.side_effect = lambda _timeout: clock.__setitem__(0, clock[0] + 3)
        healthy = MagicMock()
        healthy.poll.return_value = None
        failed = MagicMock(returncode=1)
        failed.poll.return_value = 1
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(kiosk.threading, "Event", return_value=event), \
                patch.object(kiosk.threading, "Thread"), \
                patch.object(kiosk, "ThreadingHTTPServer", return_value=MagicMock(server_port=54321)), \
                patch.object(kiosk.signal, "signal"), \
                patch.object(kiosk.subprocess, "run"), \
                patch.object(kiosk.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(kiosk, "reachable", return_value=True), \
                patch.object(kiosk, "start_process", side_effect=[healthy, failed, healthy]) as start, \
                patch.object(kiosk, "stop_process"):
            kiosk.supervise(settings, Path(directory))
            self.assertEqual(start.call_count, 3)

    def test_launch_failure_retries_and_periodic_refresh_reopens_browser(self):
        settings = kiosk.Settings("http://monitor:8080/", "/usr/bin/chromium", 1)
        event = MagicMock()
        event.is_set.side_effect = [False] * 4 + [True]
        clock = [0]
        event.wait.side_effect = lambda _timeout: clock.__setitem__(0, clock[0] + 35)
        healthy = MagicMock()
        healthy.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(kiosk.threading, "Event", return_value=event), \
                patch.object(kiosk.threading, "Thread"), \
                patch.object(kiosk, "ThreadingHTTPServer", return_value=MagicMock(server_port=54321)), \
                patch.object(kiosk.signal, "signal"), \
                patch.object(kiosk.subprocess, "run"), \
                patch.object(kiosk.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(kiosk, "reachable", return_value=True), \
                patch.object(kiosk, "start_process", side_effect=[healthy, OSError("missing"), healthy, healthy]) as start, \
                patch.object(kiosk, "stop_process"), \
                self.assertLogs(kiosk.LOG, level="INFO"):
            kiosk.supervise(settings, Path(directory))
            self.assertEqual(start.call_count, 4)

    def test_installer_does_not_disable_security_or_touch_collector(self):
        source = (ROOT / "kiosk/install-kiosk.sh").read_text()
        for forbidden in ("xhost +", "--no-sandbox", "docker restart", "docker stop", "sudo reboot",
                          "full-upgrade", "passwd -d"):
            self.assertNotIn(forbidden, source)
        self.assertIn("[Seat:seat0]", source)
        self.assertIn("autologin-session=battery-kiosk", source)
        self.assertIn("--start-now", source)
        self.assertIn("previous-target", source)
        self.assertIn("dbus-run-session", source)


if __name__ == "__main__":
    unittest.main()
