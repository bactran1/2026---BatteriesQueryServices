#!/usr/bin/env python3
"""LightDM session supervisor. Standard library only; never polls the collector."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CONFIG = Path("/etc/battery-kiosk/config.json")
LOG = logging.getLogger("battery-kiosk")
WAITING_PAGE = b"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Battery dashboard</title><style>
*{box-sizing:border-box}body{margin:0;background:#141618;color:#f5f5f7;
font:20px system-ui,sans-serif;min-height:100vh;display:grid;place-items:center}
main{padding:40px;max-width:640px}h1{font-size:32px;line-height:1.15;letter-spacing:0}
p{color:#b8bec4;line-height:1.5}i{display:block;width:64px;height:4px;background:#ff9f0a}
</style><main><i></i><h1>Battery dashboard</h1>
<p>Connecting to your monitor...</p><p>The dashboard will return automatically.</p></main></html>"""


def validate_url(value: str) -> str:
    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("URL must not contain whitespace or control characters")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use an absolute http:// or https:// monitor URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Do not put credentials in the kiosk URL")
    _ = parsed.port  # Validate malformed ports before changing the host.
    return value


@dataclass(frozen=True)
class Settings:
    url: str
    browser: str
    refresh_minutes: int = 360

    def __post_init__(self) -> None:
        validate_url(self.url)
        if not self.browser.startswith("/"):
            raise ValueError("Browser must be an absolute executable path")
        if not 0 <= self.refresh_minutes <= 99999:
            raise ValueError("Refresh minutes must be between 0 and 99999")


class Availability:
    """Ignore brief outages, but always recover from a failed initial page load."""

    def __init__(self) -> None:
        self.online = False
        self.failures = 0

    def update(self, reachable: bool) -> bool:
        before = self.online
        if reachable:
            self.failures = 0
            self.online = True
        else:
            self.failures += 1
            if self.failures >= 3:
                self.online = False
        return before != self.online


def reachable(url: str) -> bool:
    try:
        request = Request(url, headers={"User-Agent": "Battery-Kiosk/1.0", "Cache-Control": "no-cache"})
        # Probe the dashboard, not collector health: battery outages must remain visible.
        with urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, OSError, ValueError):
        return False


def browser_command(settings: Settings, target: str, profile: Path) -> list[str]:
    return [settings.browser, "--kiosk", "--no-first-run", "--no-default-browser-check",
            "--noerrdialogs", "--disable-session-crashed-bubble", "--ozone-platform=x11",
            f"--user-data-dir={profile}", target]


class WaitingHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(WAITING_PAGE)))
        self.end_headers()
        self.wfile.write(WAITING_PAGE)

    def log_message(self, *_args: object) -> None:
        pass


def start_process(command: list[str]) -> subprocess.Popen:
    LOG.info("Starting %s", command[0])
    process = subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace")

    def drain() -> None:
        assert process.stderr is not None
        with process.stderr:
            for line in process.stderr:
                LOG.info("%s: %s", Path(command[0]).name, line.rstrip()[:2000])

    threading.Thread(target=drain, daemon=True).start()
    return process


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    # Kill only the process group created for this kiosk child, never another browser.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def run(settings: Settings) -> None:
    import fcntl

    if os.geteuid() == 0 or not os.environ.get("DISPLAY"):
        raise RuntimeError("Run through the Battery Kiosk LightDM session, not root or a plain SSH shell")
    home = Path.home()
    log_dir = home / ".local/state/battery-kiosk"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "session.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handler = RotatingFileHandler(log_dir / "kiosk.log", maxBytes=2_000_000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)
        supervise(settings, home)


def supervise(settings: Settings, home: Path) -> None:
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    # This path works for both native Chromium and Ubuntu's confined Chromium Snap.
    profile = home / "snap/chromium/common/battery-kiosk-profile"
    profile.mkdir(parents=True, exist_ok=True)
    for command in (["xset", "s", "off"], ["xset", "s", "noblank"], ["xset", "-dpms"]):
        try:
            subprocess.run(command, check=False, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as error:
            LOG.warning("Screen setting failed: %s", error)
    server = ThreadingHTTPServer(("127.0.0.1", 0), WaitingHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    waiting_url = f"http://127.0.0.1:{server.server_port}/"
    availability = Availability()
    browser = window_manager = None
    next_probe = next_launch = launched_at = 0.0
    backoff = 2.0
    try:
        while not stopped.is_set():
            now = time.monotonic()
            if window_manager is None or window_manager.poll() is not None:
                stop_process(window_manager)
                try:
                    window_manager = start_process(["openbox", "--sm-disable", "--config", "/etc/battery-kiosk/openbox.xml"])
                except OSError as error:
                    LOG.error("Window manager could not start: %s", error)
                    stopped.wait(5)
                    continue
            if now >= next_probe:
                changed = availability.update(reachable(settings.url))
                next_probe = time.monotonic() + 10
                if changed:
                    LOG.info("Monitor %s", "reachable" if availability.online else "unavailable")
                    stop_process(browser)
                    browser = None
                    next_launch = 0
            refresh_due = (settings.refresh_minutes > 0 and browser is not None
                           and now - launched_at >= settings.refresh_minutes * 60)
            if refresh_due:
                LOG.info("Periodic dashboard refresh")
                stop_process(browser)
                browser = None
                next_launch = 0
            if browser is not None and browser.poll() is not None:
                LOG.warning("Chromium exited: %s", browser.returncode)
                stop_process(browser)
                browser = None
                next_launch = now + backoff
                backoff = min(30, backoff * 2)
            if browser is None and now >= next_launch:
                target = settings.url if availability.online else waiting_url
                try:
                    browser = start_process(browser_command(settings, target, profile))
                    launched_at = time.monotonic()
                except OSError as error:
                    LOG.error("Chromium could not start: %s", error)
                    next_launch = time.monotonic() + backoff
                    backoff = min(30, backoff * 2)
            elif browser is not None and now - launched_at > 60:
                backoff = 2
            stopped.wait(2)
    finally:
        stop_process(browser)
        stop_process(window_manager)
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--validate-url")
    action.add_argument("--write-config", type=Path)
    action.add_argument("--run", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--browser")
    parser.add_argument("--refresh-minutes", type=int, default=360)
    args = parser.parse_args()
    try:
        if args.validate_url:
            validate_url(args.validate_url)
        elif args.write_config:
            settings = Settings(args.url or "", args.browser or "", args.refresh_minutes)
            temporary = args.write_config.with_suffix(".tmp")
            temporary.write_text(json.dumps(settings.__dict__, indent=2) + "\n", encoding="utf-8")
            temporary.replace(args.write_config)
        else:
            settings = Settings(**json.loads(CONFIG.read_text(encoding="utf-8")))
            run(settings)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"battery-kiosk: {error}\n")


if __name__ == "__main__":
    main()
