from __future__ import annotations

import json
import socket
import unittest
import urllib.error
from unittest.mock import patch

from battery_monitor.collector import CollectorClient, CollectorError


class CollectorClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = CollectorClient("http://collector.test", timeout_seconds=0.1)

    def test_rejects_malformed_json(self) -> None:
        with patch("urllib.request.urlopen", return_value=_Response(b"{")):
            with self.assertRaisesRegex(CollectorError, "malformed JSON"):
                self.client.fetch_snapshot()

    def test_reports_slow_response_timeout(self) -> None:
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            with self.assertRaisesRegex(CollectorError, "timed out"):
                self.client.fetch_snapshot()

    def test_preserves_http_status_for_unsupported_history(self) -> None:
        error = urllib.error.HTTPError(
            "http://collector.test/api/readings/history",
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(CollectorError) as context:
                self.client.fetch_history(0)
        self.assertEqual(context.exception.status_code, 404)

    def test_rejects_snapshot_without_batteries(self) -> None:
        payload = json.dumps({"service": {"status": "ok"}}).encode()
        with patch("urllib.request.urlopen", return_value=_Response(payload)):
            with self.assertRaisesRegex(CollectorError, "did not include batteries"):
                self.client.fetch_snapshot()

    def test_rejects_malformed_battery_entries(self) -> None:
        payload = json.dumps({"batteries": ["not-an-object"]}).encode()
        with patch("urllib.request.urlopen", return_value=_Response(payload)):
            with self.assertRaisesRegex(CollectorError, "did not include batteries"):
                self.client.fetch_snapshot()


class _Response:
    status = 200

    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.payload


if __name__ == "__main__":
    unittest.main()
