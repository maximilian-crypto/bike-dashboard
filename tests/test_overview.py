"""Tests für die Kopf-Kacheln der Startseite (bikedash/overview.py) und den
Einrichtungs-Check (config.setup_status)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd

from bikedash import config, overview

TODAY = dt.date(2026, 10, 26)   # Montag


def _rec(n=20, today_hrv=60.0, today_rhr=50.0, gap=0):
    days = [TODAY - dt.timedelta(days=gap + i) for i in range(n)]
    return pd.DataFrame({
        "date": pd.to_datetime(days[::-1]),
        "recovery_score": [70.0] * n,
        "hrv_rmssd_milli": [50.0] * (n - 1) + [today_hrv],
        "resting_heart_rate": [53.0] * (n - 1) + [today_rhr],
    })


def test_recovery_today_compares_with_own_baseline():
    sleep = pd.DataFrame({"date": pd.to_datetime([TODAY]), "asleep_h": [6.4], "need_h": [7.9]})
    r = overview.recovery_today(_rec(), sleep, TODAY)
    assert r.is_today and r.score == 70.0
    assert r.hrv == 60.0 and r.hrv_delta == 10.0
    assert r.rhr == 50.0 and r.rhr_delta == -3.0
    assert r.sleep_h == 6.4 and r.sleep_need_h == 7.9


def test_recovery_today_flags_stale_and_needs_baseline():
    r = overview.recovery_today(_rec(n=4, gap=3), None, TODAY)
    assert not r.is_today
    assert r.hrv_delta is None          # zu wenig Tage für einen Normalwert
    assert not overview.recovery_today(pd.DataFrame(), None, TODAY).available


def test_this_week_counts_monday_to_today_and_previous_week_same_span():
    wed = TODAY + dt.timedelta(days=2)
    rides = pd.DataFrame({
        "date": [TODAY, wed, TODAY - dt.timedelta(days=7), TODAY - dt.timedelta(days=3)],
        "moving_h": [1.0, 0.5, 2.0, 9.0], "distance_km": [30.0, 15.0, 60.0, 300.0],
    })
    w = overview.this_week(rides, wed)
    assert (w.rides, w.hours, w.km) == (2, 1.5, 45.0)
    assert w.prev_hours == 2.0            # Vorwoche nur bis Mittwoch, nicht die ganze
    assert w.days_left == 4


def test_progress_reads_fitness_and_form():
    fi = SimpleNamespace(available=True, score=57.1, delta_30=2.0, tier="Aufbau")
    p = overview.progress(fi, -5.0)
    assert (p.fitness, p.fitness_delta_30, p.form_label) == (57.1, 2.0, "Ausgeglichen")
    assert overview.progress(None, None).fitness is None


def test_setup_status_reports_set_and_missing_without_values():
    cfg = {"athlete": {"ftp": 170, "weight_kg": 0, "season_start": "2027-04-01"},
           "report": {"ntfy_topic": "DEIN_THEMA"}, "intervals": {"api_key": "k"}}
    st = {i["env"]: i["set"] for i in config.setup_status(cfg)}
    assert st["ATHLETE_FTP"] and st["ATHLETE_SEASON_START"] and st["INTERVALS_API_KEY"]
    assert not st["ATHLETE_WEIGHT_KG"]       # 0 zählt als nicht gesetzt
    assert not st["NTFY_TOPIC"]              # Platzhalter zählt als nicht gesetzt
    assert not st["ATHLETE_LTHR"]
    assert all(set(i) == {"env", "label", "set", "fallback"} for i in config.setup_status(cfg))
