import json
import math
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "monitor/src"))
from battery_monitor.storage import RetentionStore

STATIC = ROOT / "monitor/src/battery_monitor/static"
temp = tempfile.TemporaryDirectory(prefix="battery-chart-preview-")
store = RetentionStore(Path(temp.name) / "preview.sqlite3")
store.initialize()


def sample(when, hour=12, total=1):
    solar = max(0, math.sin((hour - 6) / 12 * math.pi)) * 4700
    home = 1250 + math.cos(hour * 1.7) * 560
    backup = 320 + math.sin(hour * 1.3) * 240
    battery = 650 if solar > 2500 else -450
    return {
        "service": {"captured_at": when.isoformat()},
        "batteries": [{"id": "rack-1", "address": 1, "status": "ok",
            "last_polled_at": when.isoformat(), "last_reading": {
                "timestamp": when.isoformat(), "power_w": battery, "current_a": battery / 54,
                "voltage_v": 54, "soc_percent": 82, "full_capacity_ah": 100,
                "remaining_capacity_ah": 82, "cell_voltages_v": [3.375] * 16,
                "temperatures_c": [25] * 4, "faults": [], "alarms": [],
            }}],
        "inverter": {"id": "preview", "status": "ok", "model": "Renogy X 8K",
            "last_reading": {"timestamp": when.isoformat(), "system_state": "normal",
                "pv_total_power_w": solar, "grid_import_power_w": max(0, home + backup + battery - solar),
                "grid_export_power_w": max(0, solar - home - backup - battery),
                "home_load_total_power_w": home, "load_total_power_w": backup,
                "load_energy_today_kwh": total * 0.8,
                "pv_energy_today_kwh": total * 1.3,
                "grid_import_energy_today_kwh": total * 0.4,
            }},
    }


today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
for day in range(760):
    when = today - timedelta(days=day)
    store.insert_snapshot(sample(when, total=20 + day % 17))
for hour in range(7 * 24):
    when = today - timedelta(days=6) + timedelta(hours=hour, minutes=5)
    store.insert_snapshot(sample(when, hour % 24, (hour % 24 + 1) * 1.2))


class Preview(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self):
        url = urlsplit(self.path)
        query = {key: value[0] for key, value in parse_qs(url.query).items()}
        route = url.path
        if route == "/":
            body = (STATIC / "index.html").read_text(encoding="utf-8").replace(
                "__BUILD_COMMIT__", "chart-preview-v1"
            ).encode()
            kind = "text/html; charset=utf-8"
        elif route.startswith("/api/"):
            data = {"events": []}
            if route == "/api/live":
                snapshot = sample(datetime.now(timezone.utc))
                data = {"collector_status": "online", "snapshot": snapshot,
                    "summary": {"average_soc_percent": 82, "total_power_w": 650,
                        "battery_count": 1, "online_count": 1}, "rack": {}, "storage": {}}
            elif route == "/api/energy":
                data = store.energy_history(query.get("view", "month"), query.get("date"), query.get("timezone", "UTC"))
            elif route == "/api/power-history":
                range_ = query.get("range", "date")
                if range_ == "date":
                    date_ = query.get("date", today.date().isoformat())
                    start = datetime.fromisoformat(date_).replace(tzinfo=ZoneInfo(query.get("timezone", "UTC")))
                    lower, upper = int(start.timestamp()), int((start + timedelta(days=1)).timestamp())
                    data = {"points": store.power_history(upper - lower, 3600, lower, upper),
                        "window_start_unix": lower, "window_end_unix": upper, "selected_date": date_}
                else:
                    seconds = {"1h": 3600, "24h": 86400, "7d": 604800, "30d": 2592000, "3y": 94608000}[range_]
                    data = {"points": store.power_history(seconds, max(3600, seconds // 200))}
            body = json.dumps(data).encode()
            kind = "application/json"
        elif route.startswith("/static/"):
            self.path = self.path[len("/static"):]
            return super().do_GET()
        else:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


try:
    ThreadingHTTPServer(("127.0.0.1", 8784), Preview).serve_forever()
except KeyboardInterrupt:
    pass
finally:
    store.close()
    temp.cleanup()
