"""Tests für die Aufbereitung – insbesondere die Indoor-/Outdoor-Erkennung.

Zwift meldet seine Fahrten als ``VirtualRide``; Rollen-Einheiten, die ein
Head-Unit ganz normal als ``Ride`` aufzeichnet, erkennen wir am ``trainer``-Flag
im Strava-Rohdatensatz.
"""

from __future__ import annotations

import datetime as dt
import json

from bikedash import dataprep, store

from .helpers import ride


def test_virtual_ride_is_indoor():
    assert dataprep.is_indoor("VirtualRide", "VirtualRide") is True
    assert dataprep.is_indoor(None, "VirtualRide") is True


def test_outdoor_ride_is_not_indoor():
    assert dataprep.is_indoor("Ride", "Ride") is False
    assert dataprep.is_indoor("GravelRide", "GravelRide") is False


def test_trainer_flag_marks_indoor():
    """Rolle mit Head-Unit: Typ ist ``Ride``, aber Strava setzt ``trainer``."""
    assert dataprep.is_indoor("Ride", "Ride", json.dumps({"trainer": True})) is True
    assert dataprep.is_indoor("Ride", "Ride", json.dumps({"trainer": False})) is False


def test_broken_raw_json_does_not_raise():
    assert dataprep.is_indoor("Ride", "Ride", "kein json") is False
    assert dataprep.is_indoor("Ride", "Ride", "") is False
    assert dataprep.is_indoor(None, None, None) is False


def test_prep_rides_splits_distance_by_venue():
    outdoor = ride(1, dt.datetime(2026, 1, 5, 10, 0), dist_m=30000.0)
    indoor = ride(2, dt.datetime(2026, 1, 6, 10, 0), dist_m=20000.0)
    indoor["type"] = indoor["sport_type"] = "VirtualRide"
    store.upsert_strava_activities([outdoor, indoor])

    df = dataprep.prep_rides()
    assert list(df["is_indoor"]) == [False, True]
    assert df["distance_km_outdoor"].sum() == 30.0
    assert df["distance_km_indoor"].sum() == 20.0
    # Die Gesamtdistanz bleibt unangetastet.
    assert df["distance_km"].sum() == 50.0
