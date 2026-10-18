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


def test_whoop_sleep_roundtrip_and_prep():
    """Whoop-Schlaf (API v2) → Tabelle → Hauptschlaf je Aufwach-Tag, ohne Nickerchen."""
    from bikedash import dataprep, whoop

    def rec(sid, end, light, sws, rem, nap=False):
        return {"id": sid, "cycle_id": 1, "start": "2026-10-20T22:30:00.000Z", "end": end,
                "timezone_offset": "+02:00", "nap": nap, "score_state": "SCORED",
                "score": {"stage_summary": {"total_in_bed_time_milli": 8 * 3_600_000,
                                            "total_light_sleep_time_milli": light,
                                            "total_slow_wave_sleep_time_milli": sws,
                                            "total_rem_sleep_time_milli": rem},
                          "sleep_needed": {"baseline_milli": 8 * 3_600_000,
                                           "need_from_sleep_debt_milli": 3_600_000},
                          "sleep_performance_percentage": 70, "respiratory_rate": 15.2}}

    h = 3_600_000
    rows = [whoop.sleep_row(rec("a", "2026-10-21T04:30:00.000Z", 3 * h, h, h)),
            # 23:30 UTC = 01:30 Ortszeit am 22. → Aufwach-Tag 22.10.
            whoop.sleep_row(rec("b", "2026-10-21T23:30:00.000Z", 2 * h, h, h)),
            whoop.sleep_row(rec("n", "2026-10-21T13:00:00.000Z", h, 0, 0, nap=True))]
    assert rows[0]["asleep_h"] == 5.0 and rows[0]["need_h"] == 9.0 and rows[0]["debt_h"] == 1.0
    assert rows[1]["wake_date"] == "2026-10-22"
    store.upsert_whoop_sleep(rows)
    df = dataprep.prep_sleep()
    assert list(df["asleep_h"]) == [5.0, 4.0]          # Nickerchen nicht mitgezählt
    assert [d.date().isoformat() for d in df["date"]] == ["2026-10-21", "2026-10-22"]
