"""Tests für die Aufbereitung – insbesondere die Indoor-/Outdoor-Erkennung.

Zwift meldet seine Fahrten als ``VirtualRide``; Rollen-Einheiten, die ein
Head-Unit ganz normal als ``Ride`` aufzeichnet, erkennen wir am ``trainer``-Flag
im Strava-Rohdatensatz.
"""

from __future__ import annotations

import datetime as dt
import json

from bikedash import dataprep, store

from .helpers import recovery, ride


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


# --- Wahl der Lastquelle ---------------------------------------------------

def _athlete_config(tmp_path, **vals):
    from bikedash import config
    body = "[athlete]\n" + "\n".join(f"{k} = {v}" for k, v in vals.items())
    config.CONFIG_PATH.write_text(body, encoding="utf-8")


def test_power_used_when_device_watts_and_ftp(tmp_path):
    """Rolle mit echten Wattdaten: leistungsbasierte Last, nicht HF."""
    _athlete_config(tmp_path, ftp=250, lthr=165)
    z = ride(1, dt.datetime(2026, 1, 5, 18, 0))
    z["type"] = z["sport_type"] = "VirtualRide"
    z["moving_time_s"] = 3600
    z["weighted_average_watts"] = 250.0
    z["raw_json"] = json.dumps({"device_watts": True, "trainer": True})
    store.upsert_strava_activities([z])
    store.set_state("whoop_max_hr", "188")
    store.upsert_whoop_recovery(
        [recovery(1, dt.date(2026, 1, 5), 70.0)])   # liefert den Ruhepuls

    df = dataprep.prep_rides()
    assert df.iloc[0]["load_source"] == "power"
    assert abs(df.iloc[0]["load"] - 100.0) < 0.01   # 1 h an der FTP = 100


def test_estimated_watts_do_not_count_as_power(tmp_path):
    """Stravas geschaetzte Watt (device_watts=false) sind keine Messwerte."""
    _athlete_config(tmp_path, ftp=250, lthr=165)
    r = ride(1, dt.datetime(2026, 1, 5, 18, 0), hr=150.0)
    r["weighted_average_watts"] = 250.0
    r["raw_json"] = json.dumps({"device_watts": False})
    store.upsert_strava_activities([r])
    store.set_state("whoop_max_hr", "188")
    store.upsert_whoop_recovery(
        [recovery(1, dt.date(2026, 1, 5), 70.0)])   # liefert den Ruhepuls

    assert dataprep.prep_rides().iloc[0]["load_source"] == "hr"


def test_hr_used_without_ftp(tmp_path):
    """Ohne FTP faellt auch eine Wattfahrt auf die Herzfrequenz zurueck."""
    _athlete_config(tmp_path, lthr=165)
    z = ride(1, dt.datetime(2026, 1, 5, 18, 0), hr=150.0)
    z["weighted_average_watts"] = 250.0
    z["raw_json"] = json.dumps({"device_watts": True})
    store.upsert_strava_activities([z])
    store.set_state("whoop_max_hr", "188")
    store.upsert_whoop_recovery(
        [recovery(1, dt.date(2026, 1, 5), 70.0)])   # liefert den Ruhepuls

    assert dataprep.prep_rides().iloc[0]["load_source"] == "hr"


def test_falls_back_to_suffer_score_without_hr(tmp_path):
    _athlete_config(tmp_path, lthr=165)
    r = ride(1, dt.datetime(2026, 1, 5, 18, 0), hr=None, suffer=95.0)
    r["average_heartrate"] = None
    store.upsert_strava_activities([r])
    store.set_state("whoop_max_hr", "188")
    store.upsert_whoop_recovery(
        [recovery(1, dt.date(2026, 1, 5), 70.0)])   # liefert den Ruhepuls

    row = dataprep.prep_rides().iloc[0]
    assert row["load_source"] == "suffer_score"
    assert row["load"] == 95.0


def test_load_is_on_tss_scale(tmp_path):
    """Eine Stunde an der Schwelle ergibt 100 – unabhaengig von der Quelle."""
    _athlete_config(tmp_path, lthr=165)
    r = ride(1, dt.datetime(2026, 1, 5, 18, 0), hr=165.0)
    r["moving_time_s"] = 3600
    store.upsert_strava_activities([r])
    store.set_state("whoop_max_hr", "188")
    store.upsert_whoop_recovery(
        [recovery(1, dt.date(2026, 1, 5), 70.0)])   # liefert den Ruhepuls

    row = dataprep.prep_rides().iloc[0]
    assert row["load_source"] == "hr"
    assert abs(row["load"] - 100.0) < 0.5
