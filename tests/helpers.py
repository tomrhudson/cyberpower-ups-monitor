from __future__ import annotations

import sqlite3
from pathlib import Path


def create_powerpanel_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE DeviceLog (
            id INTEGER PRIMARY KEY,
            LocalTime TEXT NOT NULL,
            InVolt REAL,
            InFreq REAL,
            OutVolt REAL,
            OutFreq REAL,
            OutCur REAL,
            BatCap REAL,
            BatRun REAL,
            BatVolt REAL,
            BatWar INTEGER,
            SysSta TEXT,
            SysTemp REAL,
            SN TEXT,
            LP INTEGER,
            Model TEXT,
            FV TEXT,
            RatPow INTEGER,
            upsState INTEGER,
            PowSour INTEGER,
            DevLoad REAL
        );
        CREATE TABLE EnergyConsumption (
            id INTEGER PRIMARY KEY,
            consumption REAL,
            createTime TEXT
        );
        CREATE TABLE EventEnum (
            id INTEGER PRIMARY KEY,
            reasoning TEXT,
            description TEXT,
            status INTEGER,
            category TEXT
        );
        CREATE TABLE EventLog (
            id INTEGER PRIMARY KEY,
            EventId INTEGER,
            CreateTime TEXT
        );
        INSERT INTO DeviceLog VALUES (
            1, '2026-07-18 21:30:00', NULL, 60, 118, 60, 3.2,
            100, 18, 24, 0, '', NULL, 'TEST123', 1000,
            'CP1500PFCRM2U', 'BF01', 1500, 0, 0, NULL
        );
        INSERT INTO EnergyConsumption VALUES (
            1, 378.5, '2026-07-18 21:00:00'
        );
        INSERT INTO EventEnum VALUES (
            1, 'ID_UTILITY_FAILURE',
            'Utility power failed, transfer to backup mode', 1, 'I'
        );
        INSERT INTO EventLog VALUES (
            1, 1, '2026-07-18 20:00:00'
        );
        """
    )
    connection.commit()
    connection.close()


def sample_payload() -> dict:
    return {
        "schema_version": 1,
        "collector": {
            "name": "test-collector",
            "hostname": "test-collector",
            "version": "0.1.0",
        },
        "device": {
            "serial": "TEST123",
            "model": "CP1500PFCRM2U",
            "firmware": "BF01",
            "rated_va": 1500,
            "rated_watts": 1000,
        },
        "sample": {
            "timestamp": "2026-07-18T21:30:00+00:00",
            "status": "online",
            "battery_charge": 100,
            "runtime_minutes": 18,
            "output_voltage": 118,
            "power_watts": 378.5,
            "power_observed_at": "2026-07-18T21:00:00+00:00",
        },
        "events": [
            {
                "key": "test-event",
                "id": 1,
                "timestamp": "2026-07-18T20:00:00+00:00",
                "reasoning": "ID_UTILITY_FAILURE",
                "description": "Utility power failed",
                "severity": "warning",
                "category": "I",
            }
        ],
    }
