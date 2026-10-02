import datetime as dt

import pandas as pd

from bikedash import guard, recommend, store

from .helpers import recovery, ride


def _rides(days_loads, today):
    """DataFrame wie dataprep.prep_rides (nur die Spalten, die guard braucht)."""
    rows = [{"start": pd.Timestamp(today - dt.timedelta(days=d)) + pd.Timedelta(hours=9),
             "date": today - dt.timedelta(days=d), "load": load}
            for d, load in days_loads]
    return pd.DataFrame(rows)


def _rec(days_scores, today):
    return pd.DataFrame({"date": [pd.Timestamp(today - dt.timedelta(days=d)) for d, _ in days_scores],
                         "recovery_score": [s for _, s in days_scores]})


TODAY = dt.date(2026, 10, 2)
NO_REC = pd.DataFrame(columns=["date", "recovery_score"])


def test_apply_only_lowers():
    g = guard.Guard(cap="ENDURANCE")
    assert g.apply("THRESHOLD") == "ENDURANCE"
    assert g.apply("RECOVERY") == "RECOVERY"
    assert guard.Guard().apply("THRESHOLD") == "THRESHOLD"


def test_steady_training_is_ok():
    # 90 Tage lang jeden zweiten Tag 60 TSS: gleichmäßig, Verhältnis ≈ 1.
    r = _rides([(d, 60.0) for d in range(2, 90, 2)], TODAY)
    g = guard.check(r, NO_REC, TODAY)
    assert g.level == "ok" and g.cap is None
    assert g.acwr is not None and 0.8 < g.acwr < 1.3


def test_load_spike_caps_to_recovery():
    # Lange ruhige Basis, dann eine Woche mit dreifacher Last.
    base = [(d, 30.0) for d in range(10, 90, 2)]
    spike = [(d, 150.0) for d in (1, 2, 4, 5, 7)]
    g = guard.check(_rides(base + spike, TODAY), NO_REC, TODAY)
    assert g.acwr > guard.ACWR_STOP
    assert g.level == "stop" and g.cap == "RECOVERY"


def test_tiny_base_does_not_trigger_acwr():
    # Bei sehr kleiner Fitness ist jede Fahrt ein „Sprung" — nicht werten.
    r = _rides([(60, 20.0), (1, 80.0)], TODAY)
    assert guard.acwr(r, TODAY)[0] is None


def test_six_days_in_a_row_forces_rest():
    r = _rides([(d, 50.0) for d in range(1, 7)], TODAY)
    g = guard.check(r, NO_REC, TODAY)
    assert g.streak_days == 6 and g.cap == "REST" and g.level == "stop"


def test_five_days_in_a_row_blocks_intensity():
    r = _rides([(d, 50.0) for d in range(1, 6)], TODAY)
    g = guard.check(r, NO_REC, TODAY)
    assert g.streak_days == 5 and g.cap == "ENDURANCE" and g.level == "caution"


def test_short_spin_does_not_count_as_training_day():
    r = _rides([(d, 50.0) for d in range(1, 6)] + [(6, 10.0)], TODAY)
    assert guard.streak(r, TODAY) == 5


def test_repeated_red_recovery_forces_rest_despite_green_today():
    rec = _rec([(0, 85.0), (1, 25.0), (3, 30.0), (5, 20.0)], TODAY)
    g = guard.check(pd.DataFrame(), rec, TODAY)
    assert g.red_days == 3 and g.cap == "REST"


def test_recommend_respects_guard_with_green_recovery():
    """Grüne Recovery und frische Form, aber 6 Tage am Stück → Ruhetag."""
    today = dt.date(2026, 6, 15)
    rides = [ride(300 + d, dt.datetime.combine(today - dt.timedelta(days=d), dt.time(9)),
                  dist_m=20000.0, hr=120.0, suffer=30.0)
             for d in range(1, 7)]
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "185")
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    rc = recommend.build(today=today)
    assert rc.readiness_band == "green"
    assert rc.streak_days == 6
    assert rc.kind == "REST" and rc.guard_level == "stop"
    assert rc.warnings
