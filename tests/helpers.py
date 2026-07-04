"""Gemeinsame Test-Helfer: synthetische Datensätze erzeugen."""

from __future__ import annotations

import datetime as dt


def ride(rid: int, start: dt.datetime, dist_m=40000.0, hr=140.0, suffer=80.0):
    mov = dist_m / 7.0
    return {
        "id": rid,
        "name": f"Ride {rid}",
        "type": "Ride",
        "sport_type": "Ride",
        "start_date": start.isoformat() + "Z",
        "start_date_local": start.isoformat() + "Z",
        "distance_m": dist_m,
        "moving_time_s": mov,
        "elapsed_time_s": mov * 1.1,
        "total_elevation_gain_m": 300.0,
        "average_speed_ms": dist_m / mov,
        "max_speed_ms": 13.0,
        "average_watts": None,
        "weighted_average_watts": None,
        "max_watts": None,
        "average_heartrate": hr,
        "max_heartrate": 185.0,
        "kilojoules": None,
        "suffer_score": suffer,
        "raw_json": "{}",
    }


def recovery(cycle_id: int, date: dt.date, score: float):
    return {
        "cycle_id": cycle_id,
        "date": date.isoformat(),
        "recovery_score": score,
        "resting_heart_rate": 52.0,
        "hrv_rmssd_milli": 80.0,
        "spo2_percentage": 97.0,
        "skin_temp_celsius": 34.0,
        "raw_json": "{}",
    }
