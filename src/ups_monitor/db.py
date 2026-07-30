from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS devices (
    serial TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    firmware TEXT,
    rated_va REAL,
    rated_watts REAL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_collector TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collectors (
    name TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    version TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    serial TEXT NOT NULL REFERENCES devices(serial) ON DELETE CASCADE,
    source_timestamp TEXT NOT NULL,
    received_at TEXT NOT NULL,
    collector TEXT NOT NULL,
    status TEXT NOT NULL,
    battery_charge REAL,
    runtime_minutes REAL,
    input_voltage REAL,
    output_voltage REAL,
    output_current REAL,
    load_percent REAL,
    power_watts REAL,
    power_observed_at TEXT,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_samples_serial_time
ON samples(serial, received_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    serial TEXT NOT NULL REFERENCES devices(serial) ON DELETE CASCADE,
    source_event_id INTEGER,
    event_time TEXT NOT NULL,
    reasoning TEXT,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT,
    collector TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_time
ON events(event_time DESC);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def ingest(self, payload: dict[str, Any]) -> None:
        received_at = utc_now()
        collector = payload["collector"]
        device = payload["device"]
        sample = payload["sample"]
        serial = device["serial"]

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO collectors(name, hostname, version, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    hostname=excluded.hostname,
                    version=excluded.version,
                    last_seen=excluded.last_seen
                """,
                (
                    collector["name"],
                    collector["hostname"],
                    collector.get("version"),
                    received_at,
                    received_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO devices(
                    serial, model, firmware, rated_va, rated_watts,
                    first_seen, last_seen, last_collector
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(serial) DO UPDATE SET
                    model=excluded.model,
                    firmware=COALESCE(excluded.firmware, devices.firmware),
                    rated_va=COALESCE(excluded.rated_va, devices.rated_va),
                    rated_watts=COALESCE(excluded.rated_watts, devices.rated_watts),
                    last_seen=excluded.last_seen,
                    last_collector=excluded.last_collector
                """,
                (
                    serial,
                    device["model"],
                    device.get("firmware"),
                    device.get("rated_va"),
                    device.get("rated_watts"),
                    received_at,
                    received_at,
                    collector["name"],
                ),
            )
            connection.execute(
                """
                INSERT INTO samples(
                    serial, source_timestamp, received_at, collector, status,
                    battery_charge, runtime_minutes, input_voltage, output_voltage,
                    output_current, load_percent, power_watts, power_observed_at,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    serial,
                    sample["timestamp"],
                    received_at,
                    collector["name"],
                    sample["status"],
                    sample.get("battery_charge"),
                    sample.get("runtime_minutes"),
                    sample.get("input_voltage"),
                    sample.get("output_voltage"),
                    sample.get("output_current"),
                    sample.get("load_percent"),
                    sample.get("power_watts"),
                    sample.get("power_observed_at"),
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                ),
            )
            for event in payload.get("events", []):
                event_key = event.get("key") or self.event_key(serial, event)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO events(
                        event_key, serial, source_event_id, event_time, reasoning,
                        description, severity, category, collector
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_key,
                        serial,
                        event.get("id"),
                        event["timestamp"],
                        event.get("reasoning"),
                        event["description"],
                        event.get("severity", "info"),
                        event.get("category"),
                        collector["name"],
                    ),
                )

    @staticmethod
    def event_key(serial: str, event: dict[str, Any]) -> str:
        material = "|".join(
            [
                serial,
                str(event.get("id", "")),
                event.get("timestamp", ""),
                event.get("reasoning", ""),
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def list_devices(
        self,
        configured: dict[str, dict[str, Any]],
        stale_after_seconds: int,
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    d.*,
                    s.source_timestamp,
                    s.received_at,
                    s.collector,
                    s.status,
                    s.battery_charge,
                    s.runtime_minutes,
                    s.input_voltage,
                    s.output_voltage,
                    s.output_current,
                    s.load_percent,
                    s.power_watts,
                    s.power_observed_at
                FROM devices d
                LEFT JOIN samples s ON s.id = (
                    SELECT id FROM samples
                    WHERE serial = d.serial
                    ORDER BY received_at DESC
                    LIMIT 1
                )
                ORDER BY d.first_seen
                """
            ).fetchall()

        by_serial = {row["serial"]: dict(row) for row in rows}
        for serial, metadata in configured.items():
            by_serial.setdefault(
                serial,
                {
                    "serial": serial,
                    "model": metadata.get("model", "Expected UPS"),
                    "firmware": None,
                    "rated_va": metadata.get("rated_va"),
                    "rated_watts": metadata.get("rated_watts"),
                    "first_seen": None,
                    "last_seen": None,
                    "last_collector": None,
                    "source_timestamp": None,
                    "received_at": None,
                    "collector": None,
                    "status": "offline",
                    "battery_charge": None,
                    "runtime_minutes": None,
                    "input_voltage": None,
                    "output_voltage": None,
                    "output_current": None,
                    "load_percent": None,
                    "power_watts": None,
                    "power_observed_at": None,
                },
            )

        now = datetime.now(timezone.utc)
        result: list[dict[str, Any]] = []
        for serial, device in by_serial.items():
            metadata = configured.get(serial, {})
            received_at = parse_timestamp(device.get("received_at"))
            is_stale = (
                received_at is None
                or (now - received_at).total_seconds() > stale_after_seconds
            )
            device["stale"] = is_stale
            device["online"] = not is_stale
            if is_stale:
                device["status"] = "offline"
            device["name"] = metadata.get("name") or device.get("model")
            device["location"] = metadata.get("location")
            device["loads"] = metadata.get("loads")
            device["role"] = metadata.get("role")
            device["power_path"] = metadata.get("power_path")
            device["runtime_note"] = metadata.get("runtime_note")
            device["active"] = metadata.get("active", True) is not False
            device["expected_collectors"] = metadata.get("collectors", [])
            result.append(device)

        order = {
            serial: metadata.get("order", 999)
            for serial, metadata in configured.items()
        }
        result.sort(key=lambda item: (order.get(item["serial"], 999), item["name"]))
        return result

    def device_history(
        self, serial: str, hours: int, limit: int
    ) -> list[dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_timestamp, received_at, collector, status,
                       battery_charge, runtime_minutes, input_voltage,
                       output_voltage, output_current, load_percent, power_watts
                FROM samples
                WHERE serial = ? AND received_at >= ?
                ORDER BY received_at ASC
                LIMIT ?
                """,
                (serial, since.isoformat(), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recent_events(self, limit: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, serial, source_event_id, event_time, reasoning,
                       description, severity, category, collector
                FROM events
                ORDER BY event_time DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune(self, retention_days: int) -> int:
        before = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM samples WHERE received_at < ?", (before.isoformat(),)
            )
            return cursor.rowcount

    def metrics(
        self,
        configured: dict[str, dict[str, Any]],
        stale_after_seconds: int,
    ) -> str:
        devices = self.list_devices(configured, stale_after_seconds)
        lines = [
            "# HELP ups_monitor_up Whether the UPS is reporting fresh data.",
            "# TYPE ups_monitor_up gauge",
            "# HELP ups_battery_charge_percent Current battery charge percentage.",
            "# TYPE ups_battery_charge_percent gauge",
            "# HELP ups_runtime_minutes Estimated remaining runtime in minutes.",
            "# TYPE ups_runtime_minutes gauge",
            "# HELP ups_power_watts Latest reported average power draw in watts.",
            "# TYPE ups_power_watts gauge",
        ]
        for device in devices:
            if not device.get("active", True):
                continue
            labels = (
                f'serial="{escape_label(device["serial"])}",'
                f'model="{escape_label(device["model"])}",'
                f'name="{escape_label(device["name"])}"'
            )
            lines.append(f"ups_monitor_up{{{labels}}} {1 if device['online'] else 0}")
            add_metric(lines, "ups_battery_charge_percent", labels, device.get("battery_charge"))
            add_metric(lines, "ups_runtime_minutes", labels, device.get("runtime_minutes"))
            add_metric(lines, "ups_power_watts", labels, device.get("power_watts"))
        return "\n".join(lines) + "\n"


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")

    collector = payload.get("collector")
    device = payload.get("device")
    sample = payload.get("sample")
    if not all(isinstance(value, dict) for value in (collector, device, sample)):
        raise ValueError("collector, device, and sample objects are required")

    require_string(collector, "name", 100)
    require_string(collector, "hostname", 255)
    require_string(device, "serial", 128)
    require_string(device, "model", 128)
    require_string(sample, "timestamp", 64)
    require_string(sample, "status", 32)
    if sample["status"] not in {"online", "on_battery", "warning", "unknown"}:
        raise ValueError("invalid sample status")

    events = payload.get("events", [])
    if not isinstance(events, list) or len(events) > 100:
        raise ValueError("events must be a list containing no more than 100 items")
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("each event must be an object")
        require_string(event, "timestamp", 64)
        require_string(event, "description", 500)

    return payload


def require_string(value: dict[str, Any], key: str, max_length: int) -> None:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip() or len(item) > max_length:
        raise ValueError(f"{key} must be a non-empty string")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def escape_label(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def add_metric(
    lines: list[str], name: str, labels: str, value: Any
) -> None:
    if value is not None:
        lines.append(f"{name}{{{labels}}} {float(value)}")
