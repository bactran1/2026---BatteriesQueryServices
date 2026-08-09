from __future__ import annotations

import json
import urllib.error
import urllib.request


class CollectorError(Exception):
    """Raised when the collector cannot be reached or returns invalid data."""


class CollectorClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_snapshot(self) -> dict:
        url = f"{self.base_url}/api/readings"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status >= 400:
                    raise CollectorError(f"collector returned HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise CollectorError(str(exc)) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("batteries"), list):
            raise CollectorError("collector response did not include batteries")
        return payload
