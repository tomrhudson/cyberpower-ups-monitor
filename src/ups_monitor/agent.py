from __future__ import annotations

import argparse
import hashlib
import json
import platform
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__


DEFAULT_DB = (
    "/Applications/PowerPanel Personal.app/Contents/Frameworks/assets/"
    "PPPE_Db.db"
)


def read_nut(
    ups_name: str, collector_name: str, timeout: int = 10
) -> dict[str, Any]:
    """Read one UPS from a local Network UPS Tools server."""
    if not ups_name.strip():
        raise ValueError("NUT UPS name is required")
    try:
        result = subprocess.run(
            ["upsc", ups_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise RuntimeError("NUT upsc command was not found") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"NUT query timed out for {ups_name}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown upsc error"
        raise RuntimeError(f"NUT query failed for {ups_name}: {detail[:500]}")
    return parse_nut_output(result.stdout, collector_name)


def parse_nut_output(output: str, collector_name: str) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()

    serial = values.get("device.serial") or values.get("ups.serial")
    model = values.get("device.model") or values.get("ups.model")
    if not serial or not model:
        raise RuntimeError("NUT response is missing model or serial")

    timestamp = datetime.now(timezone.utc).isoformat()
    realpower = optional_float(values.get("ups.realpower"))
    return {
        "schema_version": 1,
        "collector": {
            "name": collector_name,
            "hostname": socket.gethostname(),
            "version": __version__,
            "platform": platform.platform(),
        },
        "device": {
            "serial": serial,
            "model": model,
            "firmware": values.get("device.firmware"),
            "rated_va": optional_float(values.get("ups.power.nominal")),
            "rated_watts": optional_float(values.get("ups.realpower.nominal")),
        },
        "sample": {
            "timestamp": timestamp,
            "status": map_nut_status(values.get("ups.status", "")),
            "battery_charge": optional_float(values.get("battery.charge")),
            "runtime_minutes": seconds_to_minutes(values.get("battery.runtime")),
            "battery_voltage": optional_float(values.get("battery.voltage")),
            "input_voltage": optional_float(values.get("input.voltage")),
            "input_frequency": optional_float(values.get("input.frequency")),
            "output_voltage": optional_float(values.get("output.voltage")),
            "output_frequency": optional_float(values.get("output.frequency")),
            "output_current": optional_float(values.get("output.current")),
            "load_percent": optional_float(values.get("ups.load")),
            "power_watts": realpower,
            "power_observed_at": timestamp if realpower is not None else None,
            "power_measurement": (
                "NUT instantaneous real power" if realpower is not None else None
            ),
            "system_status": values.get("ups.status"),
        },
        "events": [],
    }


def map_nut_status(value: str) -> str:
    states = set(value.upper().split())
    if "OB" in states:
        return "on_battery"
    if states.intersection({"LB", "RB", "OVER", "BYPASS", "OFF", "FSD"}):
        return "warning"
    if "OL" in states:
        return "online"
    return "unknown"


def seconds_to_minutes(value: Any) -> float | None:
    seconds = optional_float(value)
    return round(seconds / 60, 1) if seconds is not None else None


def read_powerpanel(db_path: Path, collector_name: str) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"PowerPanel database not found: {db_path}")

    uri = f"file:{db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        device = connection.execute(
            """
            SELECT LocalTime, InVolt, InFreq, OutVolt, OutFreq, OutCur,
                   BatCap, BatRun, BatVolt, BatWar, SysSta, SysTemp,
                   SN, LP, Model, FV, RatPow, upsState, PowSour, DevLoad
            FROM DeviceLog
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if device is None:
            raise RuntimeError("PowerPanel DeviceLog does not contain samples")

        energy = connection.execute(
            """
            SELECT consumption, createTime
            FROM EnergyConsumption
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        event_rows = connection.execute(
            """
            SELECT
                log.id AS log_id,
                log.EventId AS source_event_id,
                log.CreateTime,
                enum.reasoning,
                enum.description,
                enum.status,
                enum.category
            FROM EventLog log
            LEFT JOIN EventEnum enum ON enum.id = log.EventId
            ORDER BY log.id DESC
            LIMIT 100
            """
        ).fetchall()
    finally:
        connection.close()

    serial = normalized_string(device["SN"])
    model = normalized_string(device["Model"])
    if not serial or not model:
        raise RuntimeError("latest PowerPanel sample is missing model or serial")

    status = map_status(device)
    source_timestamp = local_timestamp_to_utc(device["LocalTime"])
    power_watts = optional_float(energy["consumption"]) if energy else None
    power_timestamp = (
        local_timestamp_to_utc(energy["createTime"]) if energy else None
    )
    rated_watts = optional_float(device["LP"])
    load_percent = optional_float(device["DevLoad"])
    if (
        load_percent is None
        and power_watts is not None
        and rated_watts
        and rated_watts > 0
    ):
        load_percent = round((power_watts / rated_watts) * 100, 1)

    events = [build_event(serial, row) for row in reversed(event_rows)]
    return {
        "schema_version": 1,
        "collector": {
            "name": collector_name,
            "hostname": socket.gethostname(),
            "version": __version__,
            "platform": platform.platform(),
        },
        "device": {
            "serial": serial,
            "model": model.removesuffix("a"),
            "reported_model": model,
            "firmware": normalized_string(device["FV"]),
            "rated_va": optional_float(device["RatPow"]),
            "rated_watts": rated_watts,
        },
        "sample": {
            "timestamp": source_timestamp,
            "status": status,
            "battery_charge": optional_float(device["BatCap"]),
            "runtime_minutes": optional_float(device["BatRun"]),
            "battery_voltage": optional_float(device["BatVolt"]),
            "battery_warning": optional_int(device["BatWar"]),
            "input_voltage": optional_float(device["InVolt"]),
            "input_frequency": optional_float(device["InFreq"]),
            "output_voltage": optional_float(device["OutVolt"]),
            "output_frequency": optional_float(device["OutFreq"]),
            "output_current": optional_float(device["OutCur"]),
            "system_temperature": optional_float(device["SysTemp"]),
            "load_percent": load_percent,
            "power_watts": power_watts,
            "power_observed_at": power_timestamp,
            "power_measurement": (
                "PowerPanel current-hour average" if energy else None
            ),
            "power_source_code": optional_int(device["PowSour"]),
            "ups_state_code": optional_int(device["upsState"]),
            "system_status": normalized_string(device["SysSta"]),
        },
        "events": events,
    }


def map_status(device: sqlite3.Row) -> str:
    power_source = optional_int(device["PowSour"])
    battery_warning = optional_int(device["BatWar"])
    ups_state = optional_int(device["upsState"])
    if power_source is not None and power_source != 0:
        return "on_battery"
    if battery_warning not in (None, 0) or ups_state not in (None, 0):
        return "warning"
    if power_source == 0:
        return "online"
    return "unknown"


def build_event(serial: str, row: sqlite3.Row) -> dict[str, Any]:
    event_id = optional_int(row["source_event_id"])
    timestamp = local_timestamp_to_utc(row["CreateTime"])
    reasoning = normalized_string(row["reasoning"])
    description = normalized_string(row["description"]) or (
        f"PowerPanel event {event_id}"
    )
    status = optional_int(row["status"])
    severity = "critical" if status == 2 else "warning" if status == 1 else "info"
    key_material = f"{serial}|{event_id}|{timestamp}|{reasoning or ''}"
    return {
        "key": hashlib.sha256(key_material.encode("utf-8")).hexdigest(),
        "id": event_id,
        "timestamp": timestamp,
        "reasoning": reasoning,
        "description": description,
        "severity": severity,
        "category": normalized_string(row["category"]),
    }


def send_payload(
    server_url: str, token: str, payload: dict[str, Any], timeout: int
) -> None:
    target = server_url.rstrip("/") + "/api/v1/ingest"
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    request = Request(
        target,
        method="POST",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"CyberPowerUPSMonitorAgent/{__version__}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 202:
                raise RuntimeError(
                    f"monitor returned unexpected HTTP status {response.status}"
                )
    except HTTPError as error:
        detail = error.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"monitor rejected sample with HTTP {error.code}: {detail}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"monitor is unreachable: {error.reason}") from error


def load_agent_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = ("server", "collector", "token_file")
    missing = [name for name in required if not raw.get(name)]
    if missing:
        raise ValueError(f"agent config is missing: {', '.join(missing)}")
    return raw


def run(config_path: Path) -> dict[str, Any]:
    config = load_agent_config(config_path)
    token = Path(config["token_file"]).expanduser().read_text(
        encoding="utf-8"
    ).strip()
    if not token:
        raise ValueError("agent token file is empty")
    source = str(config.get("source", "powerpanel")).strip().lower()
    if source == "powerpanel":
        payload = read_powerpanel(
            Path(config.get("database", DEFAULT_DB)).expanduser(),
            str(config["collector"]),
        )
    elif source == "nut":
        payload = read_nut(
            str(config.get("ups", "")),
            str(config["collector"]),
            int(config.get("timeout_seconds", 15)),
        )
    else:
        raise ValueError(f"unsupported agent source: {source}")
    send_payload(
        str(config["server"]),
        token,
        payload,
        int(config.get("timeout_seconds", 15)),
    )
    return payload


def local_timestamp_to_utc(value: Any) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).isoformat()


def normalized_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send read-only PowerPanel telemetry to UPS Monitor"
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to the agent JSON configuration",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_payload",
        help="Print the collected payload after successful delivery",
    )
    arguments = parser.parse_args()
    try:
        payload = run(arguments.config.expanduser())
        if arguments.print_payload:
            print(json.dumps(payload, indent=2))
    except Exception as error:
        print(f"ups-monitor-agent: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
