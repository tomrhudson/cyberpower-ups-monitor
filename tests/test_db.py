from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ups_monitor.db import Database, validate_payload
from ups_monitor.server import build_summary

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
                    "RETIRED": {
                        "name": "Legacy UPS",
                        "model": "OR700LCDRM1U",
                        "active": False,
                        "order": 3,
                    },
                },
                stale_after_seconds=999999999,
            )
            events = database.recent_events(10)
            metrics = database.metrics(
                {
                    "TEST123": {"name": "Main Rack UPS"},
                    "RETIRED": {
                        "name": "Legacy UPS",
                        "model": "OR700LCDRM1U",
                        "active": False,
                    },
                },
                stale_after_seconds=999999999,
            )

        self.assertEqual(len(devices), 3)
        self.assertEqual(devices[0]["name"], "Main Rack UPS")
        self.assertTrue(devices[0]["online"])
        self.assertEqual(devices[1]["status"], "offline")
        self.assertFalse(devices[2]["active"])
        self.assertEqual(len(events), 1)
        self.assertIn('serial="TEST123"', metrics)
        self.assertNotIn('serial="RETIRED"', metrics)

        summary = build_summary(devices)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["online"], 1)
        self.assertEqual(summary["offline"], 1)
        self.assertEqual(summary["inactive"], 1)

    def test_device_configuration_exposes_power_role_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "monitor.sqlite3")
            database.ingest(validate_payload(sample_payload()))
            devices = database.list_devices(
                {
                    "TEST123": {
                        "name": "Dedicated RPS UPS",
                        "role": "SmartPower backup",
                        "power_path": "UPS → UniFi RPS AC input",
                        "runtime_note": "Runtime reflects the RPS idle state.",
                    }
                },
                stale_after_seconds=999999999,
            )

        self.assertEqual(devices[0]["role"], "SmartPower backup")
        self.assertEqual(
            devices[0]["power_path"], "UPS → UniFi RPS AC input"
        )
        self.assertEqual(
            devices[0]["runtime_note"], "Runtime reflects the RPS idle state."
        )
        self.assertTrue(devices[0]["active"])

    def test_rejects_control_like_or_invalid_status(self) -> None:
        payload = sample_payload()
        payload["sample"]["status"] = "shutdown"
        with self.assertRaisesRegex(ValueError, "invalid sample status"):
            validate_payload(payload)


if __name__ == "__main__":
    unittest.main()
