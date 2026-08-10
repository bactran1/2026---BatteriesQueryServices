from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class CollectorError(Exception):
    """Raised when the collector cannot be reached or returns invalid data."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class CollectorClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fetch_snapshot(self) -> dict:
        payload = self._get_json(f"{self.base_url}/api/readings")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("batteries"), list)
            or any(not isinstance(item, dict) for item in payload["batteries"])
        ):
            raise CollectorError("collector response did not include batteries")
        return payload

    def fetch_history(self, after_sequence: int, limit: int = 500) -> dict:
        query = urllib.parse.urlencode(
            {"after_sequence": max(0, int(after_sequence)), "limit": int(limit)}
        )
        payload = self._get_json(f"{self.base_url}/api/readings/history?{query}")
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("snapshots"), list)
            or any(not isinstance(item, dict) for item in payload["snapshots"])
        ):
            raise CollectorError("collector history response did not include snapshots")
        return payload

    def _get_json(self, url: str) -> object:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if response.status >= 400:
                    raise CollectorError(
                        f"collector returned HTTP {response.status}",
                        status_code=response.status,
                    )
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CollectorError(
                f"collector returned HTTP {exc.code}", status_code=exc.code
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CollectorError("collector returned malformed JSON") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise CollectorError(str(exc)) from exc
        return payload
