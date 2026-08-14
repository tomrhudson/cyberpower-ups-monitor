# CyberPower UPS Monitor

A self-hosted, monitoring-only dashboard for multiple CyberPower UPS units.
Small read-only collectors forward telemetry from PowerPanel Personal on
USB-connected Macs or Network UPS Tools (NUT) on Linux to one responsive web
interface.

The monitor intentionally exposes no UPS command, battery-test, outlet-control,
or shutdown endpoint.

## Features

- Fleet-wide online, on-battery, warning, stale, and offline status
- Battery charge, estimated runtime, load, voltage, and frequency
- Named protection roles and power paths for each active UPS
- Inactive hardware separated from fleet health and alert counts
- PowerPanel current-hour average watts when the UPS reports it
- Collector identity and data freshness
- Deduplicated PowerPanel event history
- Six-hour, 24-hour, and seven-day trends
- Prometheus text metrics
- SQLite storage with configurable retention
- Python standard-library server and collector

PowerPanel's `EnergyConsumption` value is an hourly average, not an
instantaneous watt measurement. The dashboard labels it accordingly.

## Architecture

```text
PowerPanel Personal DB on each Mac or local NUT server on Linux
        |
        | read-only collector every 60 seconds
        v
UPS Monitor ingest API
        |
        +-- SQLite history and deduplicated PowerPanel events
        +-- responsive dashboard
        +-- Prometheus metrics endpoint
        +-- optional Homarr application link
```

The UPS serial number is used as the stable device identity. A UPS can move
between collector hosts without splitting its history.

## Quick start

The server and collector require Python 3.9 or newer and have no third-party
Python dependencies.

```bash
cp config/devices.example.json config/devices.json
mkdir -p data secrets
python3 -c 'import secrets; print(secrets.token_urlsafe(48))' \
  > secrets/ingest-token
chmod 600 secrets/ingest-token
docker compose up -d --build
```

Replace the example serial numbers and device metadata in
`config/devices.json`, then open `http://localhost:8787`.

For development without Docker:

```bash
export PYTHONPATH="$PWD/src"
export UPS_MONITOR_INGEST_TOKEN=development-only-token
export UPS_MONITOR_DEVICE_CONFIG="$PWD/config/devices.json"
python3 -m ups_monitor
```

Run the automated tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Linux installation

The included installer targets a small Debian-based VM or unprivileged LXC.
A practical starting size is 2 vCPU, 1 GB RAM, and 16 GB storage.

Stage this repository inside the guest and run:

```bash
sudo ./deploy/lxc/install.sh
```

The installer creates:

- `/opt/cyberpower-ups-monitor` — application
- `/etc/cyberpower-ups-monitor` — device inventory and ingest token
- `/var/lib/cyberpower-ups-monitor` — SQLite database
- `cyberpower-ups-monitor.service` — hardened systemd unit

The monitor listens on TCP 8787. Keep it on a trusted network or place it
behind an authenticated reverse proxy. Restrict the ingest route separately if
your proxy supports route-based access controls.

## macOS collector installation

PowerPanel Personal must be installed and actively recording the connected UPS.
Copy this repository and the central ingest-token file to the Mac, then run:

```zsh
./collector/macos/install.sh \
  https://ups.example.net \
  collector-hostname \
  /secure/path/to/ingest-token
```

The installer creates a user LaunchAgent that reads the PowerPanel SQLite
database once per minute and sends one authenticated sample to the monitor.
The collector opens the PowerPanel database in read-only mode.

Collector files:

- `~/Library/Application Support/CyberPower UPS Monitor/`
- `~/Library/LaunchAgents/io.github.cyberpower-ups-monitor.agent.plist`
- `~/Library/Logs/CyberPower UPS Monitor/`

## Linux NUT collector installation

Configure and verify the locally attached UPS in NUT first. Copy this
repository and the central ingest-token file to the Linux host, then run:

```bash
sudo ./collector/linux/install.sh \
  http://ups-monitor.internal:8787 \
  collector-hostname \
  local-ups@localhost \
  /secure/path/to/ingest-token
```

The installer creates a hardened systemd oneshot service and timer that query
the local NUT server once per minute. It reads telemetry only; it does not
expose UPS commands through the dashboard.

## Configuration

The device inventory is keyed by UPS serial number:

```json
{
  "EXAMPLE-SERIAL-001": {
    "order": 1,
    "name": "Rack UPS",
    "model": "CP1500PFCRM2U",
    "rated_va": 1500,
    "rated_watts": 1000,
    "location": "Network rack",
    "loads": "Network and storage equipment",
    "role": "Primary rack power",
    "power_path": "UPS → rack PDU → network and storage equipment",
    "runtime_note": "Optional context for interpreting the runtime estimate.",
    "active": true,
    "collectors": ["rack-mac"]
  }
}
```

Set `"active": false` to retain a disconnected or retired UPS in the inventory
without counting it as an offline fleet member. Inactive units remain visible
in a separate dashboard section and keep their stored history.

Do not commit a production `devices.json` if hostnames, serial numbers, or
location descriptions are private. It is ignored by the included `.gitignore`.

Server settings are documented in
`deploy/systemd/monitor.env.example`. Store the ingest token in a
root-readable file rather than directly in source or Compose configuration.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/healthz` | GET | Service health |
| `/api/v1/summary` | GET | Fleet rollup |
| `/api/v1/devices` | GET | Current device readings |
| `/api/v1/devices/{serial}/history` | GET | Time-series history |
| `/api/v1/events` | GET | Deduplicated PowerPanel events |
| `/api/v1/metrics` | GET | Prometheus text format |
| `/api/v1/ingest` | POST | Authenticated collector ingestion |

Only ingestion requires the bearer token. The read API and UI should remain on
a trusted LAN or behind an authenticated reverse proxy.

## Optional dashboard integrations

The `deploy/npm` and `deploy/homarr` directories contain generic helper scripts
for Nginx Proxy Manager and Homarr installations that use SQLite internally.
They require environment variables rather than embedding deployment addresses.
Review them against your installed application version and back up the target
database before use.

For a normal Homarr application card, use:

- Name: `UPS Monitor`
- URL: your authenticated monitor URL
- Health URL: the same URL with `/healthz`

## Operations

```bash
systemctl status cyberpower-ups-monitor
journalctl -u cyberpower-ups-monitor --since today
curl -fsS http://127.0.0.1:8787/healthz
```

Back up `/var/lib/cyberpower-ups-monitor/ups-monitor.sqlite3` with the guest.
The default sample retention is 90 days.

## Security

See [SECURITY.md](SECURITY.md). In particular:

- Treat the ingest token as a secret.
- Do not expose the unauthenticated read API directly to the public internet.
- Review collected device metadata before sharing a database or diagnostics.

## License

MIT
