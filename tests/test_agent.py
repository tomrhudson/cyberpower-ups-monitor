from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ups_monitor.agent import read_powerpanel

from tests.helpers import create_powerpanel_database


class AgentTests(unittest.TestCase):
    def test_reads_powerpanel_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "PowerPanel.sqlite3"
            create_powerpanel_database(database_path)

            payload = read_powerpanel(database_path, "test-collector")

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["collector"]["name"], "test-collector")
        self.assertEqual(payload["device"]["serial"], "TEST123")
        self.assertEqual(payload["device"]["rated_watts"], 1000)
        self.assertEqual(payload["sample"]["status"], "online")
        self.assertEqual(payload["sample"]["battery_charge"], 100)
        self.assertEqual(payload["sample"]["power_watts"], 378.5)
        self.assertEqual(payload["sample"]["load_percent"], 37.9)
        self.assertEqual(payload["events"][0]["severity"], "warning")


if __name__ == "__main__":
    unittest.main()
