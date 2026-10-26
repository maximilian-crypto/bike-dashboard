import datetime as dt
import json

from bikedash import fitness, intensity, recommend, store, strava

from .helpers import recovery, ride


def _streams(segments):
    """Streams aus (Sekunden, bpm)-Abschnitten, 1-s-Takt."""
    time_s, hr = [], []
    t = 0
    for secs, bpm in segments:
        for _ in range(secs):
            time_s.append(t)
            hr.append(bpm)
            t += 1
    return {"time": {"data": time_s}, "heartrate": {"data": hr},
            "velocity_smooth": {"data": [8.0] * len(time_s)}}


def test_histogram_counts_seconds_and_skips_pauses():
    h = intensity.hr_histogram([0, 1, 2, 3, 60, 61], [140, 140, 141, 141, 150, 150])
    assert h == {140: 1.0, 141: 2.0, 150: 1.0}   # 3 → 60 ist eine Pause
    assert intensity.minutes_at_or_above(h, 141) == 3.0 / 60


def test_sync_recent_stores_once_and_feeds_fitness(monkeypatch):
    today = dt.date(2026, 10, 26)
    store.upsert_strava_activities([
        ride(1, dt.datetime.combine(today - dt.timedelta(days=1), dt.time(9)), dist_m=60000.0),
        ride(2, dt.datetime.combine(today - dt.timedelta(days=40), dt.time(9))),  # zu alt
    ])
    calls = []

    def fake(cfg, rid):
        calls.append(rid)
        return _streams([(3600, 135), (3000, 165)])

    monkeypatch.setattr(strava, "fetch_streams", fake)
    res = intensity.sync_recent({}, today=today)
    assert res == {"processed": 1, "with_hr": 1}
    assert calls == [1]
    assert intensity.minutes_above_map(160) == {1: 50.0}
    assert 1 in fitness._attempted_ids()
    assert not store.read_table("ride_metrics").empty

    intensity.sync_recent({}, today=today)
    assert calls == [1]   # kein zweiter Abruf


def test_sync_recent_marks_rides_without_hr(monkeypatch):
    today = dt.date(2026, 10, 26)
    store.upsert_strava_activities([ride(1, dt.datetime.combine(today, dt.time(7)))])
    monkeypatch.setattr(strava, "fetch_streams", lambda cfg, rid: {})
    assert intensity.sync_recent({}, today=today) == {"processed": 1, "with_hr": 0}
    assert json.loads(store.read_table("ride_hr_hist")["hist"][0]) == {}


def test_sync_recent_stops_at_rate_limit(monkeypatch):
    today = dt.date(2026, 10, 26)
    store.upsert_strava_activities([ride(1, dt.datetime.combine(today, dt.time(7)))])

    def limited(cfg, rid):
        raise RuntimeError("Rate-Limit")

    monkeypatch.setattr(strava, "fetch_streams", limited)
    assert intensity.sync_recent({}, today=today)["processed"] == 0
    assert store.read_table("ride_hr_hist").empty   # beim nächsten Sync erneut


def _seed_yesterday(today, hist=None):
    """Lockere Vortage, gestern 110 min mit mäßigem Durchschnittspuls."""
    rides = [ride(200 + i, dt.datetime.combine(today - dt.timedelta(days=d), dt.time(9)))
             for i, d in enumerate((4, 6))]
    rides.append(ride(300, dt.datetime.combine(today - dt.timedelta(days=1), dt.time(17)),
                      dist_m=46000.0, hr=140.0))
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "185")
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    if hist is not None:
        store.upsert_ride_hr_hist([{"ride_id": 300, "ride_day": "x",
                                    "hist": json.dumps(hist), "computed_at": "x"}])


def test_second_half_in_z4_counts_as_hard(monkeypatch):
    """Fall vom 25.10.2026: geplant 66 min Z2, gefahren doppelt so lang mit einer
    Stunde Z4 am Ende. Der Durchschnittspuls sieht locker aus — der Verlauf nicht."""
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 5.0)
    today = dt.date(2026, 6, 15)
    _seed_yesterday(today, hist={135: 3600.0, 165: 3000.0})
    assert recommend.build(today=today).kind == "ENDURANCE"


def test_without_stream_falls_back_to_average(monkeypatch):
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 5.0)
    today = dt.date(2026, 6, 15)
    _seed_yesterday(today)
    assert recommend.build(today=today).kind == "VO2MAX"


def test_few_minutes_in_z4_stay_easy(monkeypatch):
    """Ein paar Anstiege machen aus einer Grundlagenfahrt noch keine harte Einheit."""
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 5.0)
    today = dt.date(2026, 6, 15)
    _seed_yesterday(today, hist={135: 6000.0, 165: 300.0})
    assert recommend.build(today=today).kind == "VO2MAX"
