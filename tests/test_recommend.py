import datetime as dt

from bikedash import recommend, store

from .helpers import recovery, ride


def _seed_rides(today):
    """Dichter Block (8 Fahrten in ~17 Tagen) → hohe Ermüdung / stark negativer TSB."""
    rides = [ride(100 + i, dt.datetime.combine(today - dt.timedelta(days=i * 2 + 3),
                                               dt.time(9)))
             for i in range(8)]
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "185")


def _seed_fresh(today):
    """Wenige, länger zurückliegende Fahrten → frische Form (TSB nahe/über 0),
    diese Woche kein Volumen. Prüft den Quality-Pfad, wenn die Form ihn zulässt."""
    rides = [ride(200 + i, dt.datetime.combine(today - dt.timedelta(days=d), dt.time(9)))
             for i, d in enumerate((10, 14))]
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "185")


def test_red_recovery_is_easy_or_rest():
    today = dt.date(2026, 6, 15)
    _seed_rides(today)
    store.upsert_whoop_recovery([recovery(1, today, 25.0)])
    rc = recommend.build(today=today)
    assert rc.readiness_band == "red"
    assert rc.kind in ("RECOVERY", "REST")


def test_green_recovery_fresh_form_is_quality():
    today = dt.date(2026, 6, 15)
    _seed_fresh(today)
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    rc = recommend.build(today=today)
    assert rc.readiness_band == "green"
    assert rc.tsb is not None and rc.tsb > recommend.TSB_HARD_FLOOR
    assert rc.kind in ("TEMPO", "THRESHOLD")
    assert rc.hr_low is not None and rc.hr_high > rc.hr_low


def test_deep_fatigue_overrides_green():
    """Selbst bei grüner Whoop-Recovery erzwingt tiefer TSB Erholung (Punkt c)."""
    today = dt.date(2026, 6, 15)
    _seed_rides(today)   # dichter Block → TSB < -30
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    rc = recommend.build(today=today)
    assert rc.readiness_band == "green"
    assert rc.tsb is not None and rc.tsb < recommend.TSB_DEEP_FATIGUE
    assert rc.kind in ("RECOVERY", "REST")


def test_z3_tempo_at_moderate_freshness(monkeypatch):
    """Grün + solide-aber-nicht-topfrische Form → dosierter Z3-Tempo-Reiz (Punkt a)."""
    today = dt.date(2026, 6, 15)
    _seed_fresh(today)
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: -5.0)
    rc = recommend.build(today=today)
    assert rc.kind == "TEMPO" and rc.zone_number == 3


def test_z4_threshold_at_high_freshness(monkeypatch):
    today = dt.date(2026, 6, 15)
    _seed_fresh(today)
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 12.0)
    rc = recommend.build(today=today)
    assert rc.kind == "THRESHOLD" and rc.zone_number == 4


def test_no_recovery_is_conservative():
    today = dt.date(2026, 6, 15)
    _seed_rides(today)
    rc = recommend.build(today=today)
    assert rc.readiness_band == "unknown"
    assert rc.kind in ("ENDURANCE", "RECOVERY")
