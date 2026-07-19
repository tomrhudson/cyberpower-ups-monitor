from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ups_monitor.db import Database, validate_payload

from tests.helpers import sample_payload


class DatabaseTests(unittest.TestCase):
    def test_ingest_and_list_devices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "monitor.sqlite3")
            payload = validate_payload(sample_payload())
            database.ingest(payload)
            database.ingest(payload)

            devices = database.list_devices(
                {
                    "TEST123": {
                        "name": "Main Rack UPS",
                        "location": "Rack",
                        "order": 1,
                    },
                    "PENDING": {
                        "name": "Office UPS",
                        "model": "AVRG750U",
                        "order": 2,
                    },
                },
                stale_after_seconds=999999999,
            )
            events = database.recent_events(10)

        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]["name"], "Main Rack UPS")
        self.assertTrue(devices[0]["online"])
        self.assertEqual(devices[1]["status"], "offline")
        self.assertEqual(len(events), 1)

    def test_rejects_control_like_or_invalid_status(self) -> None:
        payload = sample_payload()
        payload["sample"]["status"] = "shutdown"
        with self.assertRaisesRegex(ValueError, "invalid sample status"):
            validate_payload(payload)


if __name__ == "__main__":
    unittest.main()
