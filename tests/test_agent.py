from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ups_monitor.agent import map_nut_status, parse_nut_output, read_powerpanel

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

    def test_parses_nut_output(self) -> None:
        payload = parse_nut_output(
            """
battery.charge: 100
battery.runtime: 1260
battery.voltage: 13.7
device.model: AVRG750U
device.serial: QGRJW2003974
input.voltage: 116.0
output.voltage: 116.0
ups.load: 34
ups.realpower.nominal: 450
ups.status: OL
""",
            "Columbia",
        )

        self.assertEqual(payload["collector"]["name"], "Columbia")
        self.assertEqual(payload["device"]["serial"], "QGRJW2003974")
        self.assertEqual(payload["device"]["model"], "AVRG750U")
        self.assertEqual(payload["device"]["rated_watts"], 450)
        self.assertEqual(payload["sample"]["runtime_minutes"], 21)
        self.assertEqual(payload["sample"]["load_percent"], 34)
        self.assertEqual(payload["sample"]["status"], "online")
        self.assertIsNone(payload["sample"]["power_watts"])

    def test_maps_nut_status(self) -> None:
        self.assertEqual(map_nut_status("OL"), "online")
        self.assertEqual(map_nut_status("OB DISCHRG"), "on_battery")
        self.assertEqual(map_nut_status("OL LB"), "warning")
        self.assertEqual(map_nut_status(""), "unknown")


if __name__ == "__main__":
    unittest.main()
