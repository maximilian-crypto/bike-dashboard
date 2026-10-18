"""Tests für den Wochenrückblick (bikedash/weekly.py)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from bikedash import store, weekly

TZ = ZoneInfo("Europe/Berlin")
MONDAY = dt.date(2026, 10, 19)


def _rides(rows):
    """rows: (Tage ab Montag, km, Stunden)."""
    return pd.DataFrame([{"date": MONDAY + dt.timedelta(days=d), "distance_km": km,
                          "moving_h": h, "load": 50.0 * h} for d, km, h in rows])


def test_due_window_sunday_evening_and_monday_catch_up():
    sun_eve = dt.datetime(2026, 10, 25, 21, 13, tzinfo=TZ)
    ok, _, monday = weekly.due(sun_eve, None)
    assert ok and monday == MONDAY
    ok, why, _ = weekly.due(sun_eve, weekly.week_key(MONDAY))
    assert not ok and "schon" in why
    assert not weekly.due(dt.datetime(2026, 10, 25, 17, 0, tzinfo=TZ), None)[0]
    ok, _, monday = weekly.due(dt.datetime(2026, 10, 26, 7, 0, tzinfo=TZ), None)
    assert ok and monday == MONDAY                     # Montag: Vorwoche nachholen
    assert not weekly.due(dt.datetime(2026, 10, 26, 13, 0, tzinfo=TZ), None)[0]
    assert not weekly.due(dt.datetime(2026, 10, 21, 20, 0, tzinfo=TZ), None)[0]


def test_summary_counts_only_this_week_and_finds_new_badges():
    rides = _rides([(-3, 10_000.0, 300.0), (1, 30.0, 1.0), (4, 45.0, 1.5)])
    ws = weekly.summarize(rides, None, MONDAY)
    assert ws.rides == 2 and ws.hours == 2.5 and ws.km == 75.0
    title, msg = weekly.text(ws)
    assert title == "Deine Woche: 2 Fahrten - 2,5 h"
    assert "75 km" in msg


def test_quiet_week_is_friendly_never_red():
    ws = weekly.summarize(_rides([(-10, 40.0, 1.5)]), None, MONDAY)
    title, msg = weekly.text(ws)
    assert ws.rides == 0 and "ruhige Woche" in title
    assert "völlig okay" in msg
    for word in ("verfehlt", "Ziel nicht", "zu wenig", "nur "):
        assert word not in msg


def test_sleep_fitness_and_next_week_lines():
    sleep = pd.DataFrame({"date": [pd.Timestamp(MONDAY + dt.timedelta(days=d)) for d in range(7)],
                          "asleep_h": [6.0, 7.0, 6.5, 5.5, 7.5, 8.0, 7.0]})
    # Wie fitness.compute: "day" ist eine Datetime-Spalte, kein date.
    hist = pd.DataFrame({"day": pd.to_datetime([MONDAY - dt.timedelta(days=1),
                                                MONDAY + dt.timedelta(days=6)]),
                         "score": [50.0, 50.8]})
    fi = SimpleNamespace(available=True, score=50.8, history=hist,
                         highlights=["Bei 140 bpm fährst du inzwischen 27,1 km/h statt 26,3."])
    plan = SimpleNamespace(phase_label="Grundlage", is_deload=True, target_hours=3.5)
    ws = weekly.summarize(_rides([(2, 30.0, 1.0)]), sleep, MONDAY, fi, plan)
    _, msg = weekly.text(ws)
    assert "Ø 6,8 h Schlaf in 7 Nächten" in msg
    assert "+0,8 zur Vorwoche" in msg and "27,1 km/h" in msg
    assert "Phase „Grundlage“, Entlastungswoche, ≈ 3,5 h" in msg


def test_send_if_due_marks_week_once(monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(weekly.report, "send_push", lambda cfg, t, m: sent.append((t, m)) or True)
    monkeypatch.setattr(weekly, "build_text", lambda monday: ("T", f"M {monday}"))
    cfg = {"report": {"ntfy_topic": "abc"}}
    now = dt.datetime(2026, 10, 25, 19, 13, tzinfo=dt.timezone.utc)   # So., 20:13 MEZ
    assert weekly.send_if_due(cfg, now)[0] == "sent"
    assert store.get_kv(weekly.KV_SENT) == "2026-W43"
    assert weekly.send_if_due(cfg, now)[0] == "already"
    assert len(sent) == 1
    assert weekly.send_if_due({}, now)[0] == "no_topic"


def test_build_text_runs_on_real_db():
    from .helpers import ride
    store.upsert_strava_activities([ride(1, dt.datetime.combine(MONDAY + dt.timedelta(days=2),
                                                                dt.time(18)))])
    title, msg = weekly.build_text(MONDAY)
    assert title.startswith("Deine Woche: 1 Fahrt")
    assert "Rückblick 19.10.–25.10." in msg
