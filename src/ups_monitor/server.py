from __future__ import annotations

import hmac
import json
import mimetypes
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .config import Settings, load_device_config
from .db import Database, validate_payload


MAX_BODY_BYTES = 1_048_576


class UPSMonitorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = Database(settings.database_path)
        self.device_config = load_device_config(settings.device_config_path)
        super().__init__((settings.bind_host, settings.port), RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    server: UPSMonitorServer

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path == "/":
                return self.send_static("index.html")
            if path.startswith("/assets/"):
                return self.send_static(path.removeprefix("/assets/"))
            if path == "/healthz":
                return self.send_json({"ok": True})
            if path == "/api/v1/summary":
                devices = self.server.database.list_devices(
                    self.server.device_config,
                    self.server.settings.stale_after_seconds,
                )
                return self.send_json(build_summary(devices))
            if path == "/api/v1/devices":
                devices = self.server.database.list_devices(
                    self.server.device_config,
                    self.server.settings.stale_after_seconds,
                )
                return self.send_json({"devices": devices})
            if path.startswith("/api/v1/devices/") and path.endswith("/history"):
                serial = unquote(path[len("/api/v1/devices/") : -len("/history")])
                query = parse_qs(parsed.query)
                hours = clamp_int(query.get("hours", ["24"])[0], 1, 24 * 90)
                limit = clamp_int(query.get("limit", ["2000"])[0], 1, 10_000)
                history = self.server.database.device_history(serial, hours, limit)
                return self.send_json({"serial": serial, "samples": history})
            if path == "/api/v1/events":
                query = parse_qs(parsed.query)
                limit = clamp_int(query.get("limit", ["100"])[0], 1, 500)
                return self.send_json(
                    {"events": self.server.database.recent_events(limit)}
                )
            if path == "/api/v1/metrics":
                body = self.server.database.metrics(
                    self.server.device_config,
                    self.server.settings.stale_after_seconds,
                ).encode("utf-8")
                return self.send_bytes(body, "text/plain; version=0.0.4")
            return self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        except Exception:
            traceback.print_exc()
            return self.send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error"
            )

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") != "/api/v1/ingest":
                return self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
            if not self.authorized():
                return self.send_error_json(HTTPStatus.UNAUTHORIZED, "unauthorized")

            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return self.send_error_json(
                    HTTPStatus.LENGTH_REQUIRED, "content length required"
                )
            length = int(raw_length)
            if length <= 0 or length > MAX_BODY_BYTES:
                return self.send_error_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid request size"
                )
            payload = json.loads(self.rfile.read(length))
            validated = validate_payload(payload)
            self.server.database.ingest(validated)
            self.server.database.prune(self.server.settings.retention_days)
            return self.send_json({"ok": True}, HTTPStatus.ACCEPTED)
        except (ValueError, json.JSONDecodeError) as error:
            return self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception:
            traceback.print_exc()
            return self.send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error"
            )

    def authorized(self) -> bool:
        expected = self.server.settings.ingest_token
        if not expected:
            return False
        provided = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not provided.startswith(prefix):
            return False
        return hmac.compare_digest(provided[len(prefix) :], expected)

    def send_static(self, name: str) -> None:
        if "/" in name or name.startswith("."):
            return self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        resource = files("ups_monitor.static").joinpath(name)
        if not resource.is_file():
            return self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_bytes(resource.read_bytes(), content_type)

    def send_json(
        self, value: Any, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(
            f'{self.address_string()} - [{self.log_date_time_string()}] '
            f'{format % args}'
        )


def build_summary(devices: list[dict[str, Any]]) -> dict[str, Any]:
    online = [device for device in devices if device["online"]]
    on_battery = [
        device for device in online if device.get("status") == "on_battery"
    ]
    warnings = [
        device
        for device in online
        if device.get("status") in {"warning", "unknown"}
    ]
    return {
        "total": len(devices),
        "online": len(online),
        "offline": len(devices) - len(online),
        "on_battery": len(on_battery),
        "warnings": len(warnings),
        "all_ok": len(online) == len(devices) and not on_battery and not warnings,
    }


def clamp_int(value: str, minimum: int, maximum: int) -> int:
    return min(max(int(value), minimum), maximum)


def serve(settings: Settings) -> None:
    if not settings.ingest_token:
        raise RuntimeError(
            "UPS_MONITOR_INGEST_TOKEN or UPS_MONITOR_INGEST_TOKEN_FILE is required"
        )
    server = UPSMonitorServer(settings)
    print(
        f"CyberPower UPS Monitor listening on "
        f"http://{settings.bind_host}:{settings.port}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
