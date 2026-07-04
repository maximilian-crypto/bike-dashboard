import datetime as dt

from bikedash import recommend, store

from .helpers import recovery, ride


def _seed_rides(today):
    rides = [ride(100 + i, dt.datetime.combine(today - dt.timedelta(days=i * 2 + 3),
                                               dt.time(9)))
             for i in range(8)]
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "185")


def test_red_recovery_is_easy_or_rest():
    today = dt.date(2026, 6, 15)
    _seed_rides(today)
    store.upsert_whoop_recovery([recovery(1, today, 25.0)])
    rc = recommend.build(today=today)
    assert rc.readiness_band == "red"
    assert rc.kind in ("RECOVERY", "REST")


def test_green_recovery_low_volume_is_quality():
    today = dt.date(2026, 6, 15)
    _seed_rides(today)
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    rc = recommend.build(today=today)
    assert rc.readiness_band == "green"
    assert rc.kind in ("TEMPO", "THRESHOLD")
    assert rc.hr_low is not None and rc.hr_high > rc.hr_low


def test_no_recovery_is_conservative():
    today = dt.date(2026, 6, 15)
    _seed_rides(today)
    rc = recommend.build(today=today)
    assert rc.readiness_band == "unknown"
    assert rc.kind in ("ENDURANCE", "RECOVERY")
