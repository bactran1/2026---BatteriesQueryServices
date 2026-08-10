from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from batteries_query_service.buffer import SnapshotBuffer


class SnapshotBufferTests(unittest.TestCase):
    def test_sequences_snapshots_and_persists_stream_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "collector.sqlite3"
            buffer = SnapshotBuffer(path)
            buffer.initialize()
            stream_id = buffer.stream_id

            first = buffer.append(_snapshot("2026-08-10T12:00:00Z"))
            second = buffer.append(_snapshot("2026-08-10T12:01:00Z"))
            page = buffer.read_after(0, limit=10)

            self.assertEqual((first, second), (1, 2))
            self.assertEqual(page["latest_sequence"], 2)
            self.assertFalse(page["has_more"])
            self.assertEqual(len(page["snapshots"]), 2)
            self.assertEqual(page["snapshots"][1]["service"]["sequence"], 2)
            self.assertEqual(
                page["snapshots"][1]["service"]["buffer_stream_id"], stream_id
            )
            buffer.close()

            reopened = SnapshotBuffer(path)
            reopened.initialize()
            self.assertEqual(reopened.stream_id, stream_id)
            self.assertEqual(reopened.latest_sequence(), 2)
            reopened.close()

    def test_prunes_only_expired_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            buffer = SnapshotBuffer(Path(directory) / "collector.sqlite3")
            buffer.initialize()
            buffer.append(_snapshot("2026-08-10T12:00:00Z"))
            buffer.append(_snapshot("2026-08-10T12:01:00Z"))
            buffer.connection.execute(
                "UPDATE snapshots SET captured_at_unix = ? WHERE sequence = 1",
                (int(time.time()) - 3 * 60 * 60,),
            )
            buffer.connection.commit()

            self.assertEqual(buffer.prune_older_than_hours(1), 1)
            self.assertEqual(buffer.stats()["snapshot_count"], 1)
            buffer.close()


def _snapshot(captured_at: str) -> dict:
    return {
        "service": {"captured_at": captured_at},
        "batteries": [{"id": "rack-1", "address": 1, "status": "ok"}],
    }


if __name__ == "__main__":
    unittest.main()
