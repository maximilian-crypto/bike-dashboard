import datetime as dt

from bikedash import store

from .helpers import ride


def test_upsert_is_idempotent_and_updates():
    store.upsert_strava_activities([ride(1, dt.datetime(2026, 6, 1, 9))])
    assert store.counts()["strava_activities"] == 1

    # gleiche id erneut -> Update, kein Duplikat
    r = ride(1, dt.datetime(2026, 6, 1, 9))
    r["name"] = "Geändert"
    store.upsert_strava_activities([r])
    df = store.read_table("strava_activities")
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Geändert"


def test_state_roundtrip():
    assert store.get_state("foo") is None
    store.set_state("foo", "bar")
    assert store.get_state("foo") == "bar"
    store.set_state("foo", "baz")
    assert store.get_state("foo") == "baz"


def test_wind_segments_replace():
    rows = [{"ride_id": 1, "t_idx": 0, "lat": 1.0, "lon": 2.0, "speed_kmh": 25.0,
             "grade": 0.5, "heading": 90.0, "wind_kmh": 10.0, "wind_from_deg": 90.0,
             "headwind_kmh": 10.0, "crosswind_kmh": 0.0}]
    assert store.replace_wind_segments(1, rows) == 1
    assert store.wind_processed_ids() == {1}
    # erneutes Ersetzen verdoppelt nicht
    store.replace_wind_segments(1, rows)
    assert len(store.read_table("wind_segments")) == 1
