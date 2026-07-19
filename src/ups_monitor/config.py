from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    bind_host: str
    port: int
    database_path: Path
    device_config_path: Path | None
    ingest_token: str
    stale_after_seconds: int
    retention_days: int

    @classmethod
    def from_environment(cls) -> "Settings":
        token = os.environ.get("UPS_MONITOR_INGEST_TOKEN", "").strip()
        token_file = os.environ.get("UPS_MONITOR_INGEST_TOKEN_FILE", "").strip()
        if token_file:
            token = Path(token_file).read_text(encoding="utf-8").strip()

        config_value = os.environ.get("UPS_MONITOR_DEVICE_CONFIG", "").strip()
        return cls(
            bind_host=os.environ.get("UPS_MONITOR_BIND", "0.0.0.0"),
            port=int(os.environ.get("UPS_MONITOR_PORT", "8787")),
            database_path=Path(
                os.environ.get("UPS_MONITOR_DATABASE", "./data/ups-monitor.sqlite3")
            ),
            device_config_path=Path(config_value) if config_value else None,
            ingest_token=token,
            stale_after_seconds=int(
                os.environ.get("UPS_MONITOR_STALE_AFTER_SECONDS", "180")
            ),
            retention_days=int(os.environ.get("UPS_MONITOR_RETENTION_DAYS", "90")),
        )


def load_device_config(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("device configuration must be a JSON object")

    devices: dict[str, dict[str, Any]] = {}
    for serial, metadata in raw.items():
        if not isinstance(serial, str) or not isinstance(metadata, dict):
            raise ValueError("each configured device must map a serial to an object")
        devices[serial] = metadata
    return devices
