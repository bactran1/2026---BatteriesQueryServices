from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from batteries_query_service.config import load_settings


class CollectorConfigTests(unittest.TestCase):
    def test_build_commit_is_loaded_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "missing.toml"
            environment = {
                "BQS_CONFIG": str(config_path),
                "BQS_BUILD_COMMIT": "abc123",
            }
            with patch.dict(os.environ, environment, clear=True):
                settings = load_settings()

        self.assertEqual(settings.build_commit, "abc123")
        self.assertEqual([battery.address for battery in settings.batteries], [1, 2, 3])

if __name__ == "__main__":
    unittest.main()
