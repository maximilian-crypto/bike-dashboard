import datetime as dt

from bikedash import recommend, store

from .helpers import recovery, ride


def _seed_rides(today):
    """Dichter Block (12 Fahrten an 12 Tagen in Folge) → tiefe Ermüdung.

    Kalibriert auf die TSS-Skala (1 h an der Schwelle = 100), auf der die
    Schwellen in `recommend.py` definiert sind: dieser Block ergibt TSB ≈ −40.
    Der frühere, lockerere Block (8 Fahrten über 17 Tage) kam nur auf ≈ −19 und
    galt bloß deshalb als „tiefe Ermüdung", weil rohes Banister-TRIMP rund 1,6-
    mal heißer läuft als TSS.
    """
    rides = [ride(100 + i, dt.datetime.combine(today - dt.timedelta(days=i + 1),
                                               dt.time(9)))
             for i in range(12)]
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
    assert rc.kind in ("TEMPO", "THRESHOLD", "VO2MAX")
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
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: -15.0)
    rc = recommend.build(today=today)
    assert rc.kind == "TEMPO" and rc.zone_number == 3


def test_first_hard_session_is_4x4(monkeypatch):
    today = dt.date(2026, 6, 15)
    _seed_fresh(today)
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 12.0)
    rc = recommend.build(today=today)
    assert rc.kind == "VO2MAX" and rc.zone_number == 5


def test_second_hard_session_outside_basis_is_threshold(monkeypatch):
    """Aufbauphase, schon eine harte Einheit diese Woche → Schwelle (Z4)."""
    from bikedash import season
    today = dt.date(2026, 6, 18)   # Donnerstag
    _seed_fresh(today)
    store.upsert_strava_activities([ride(400, dt.datetime.combine(
        today - dt.timedelta(days=3), dt.time(9)), hr=170.0)])   # Montag, hart
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 5.0)
    monkeypatch.setattr(season, "hard_days_for", lambda phase: 2)
    real_build = season.build

    def _aufbau(*a, **kw):
        p = real_build(*a, **kw)
        p.phase = season.PHASE_AUFBAU
        return p
    monkeypatch.setattr(season, "build", _aufbau)
    rc = recommend.build(today=today)
    assert rc.kind == "THRESHOLD" and rc.zone_number == 4


def test_intervals_not_blocked_by_exceeded_week_target(monkeypatch):
    """Über dem Wochenziel, aber grün & frisch → trotzdem die harte Einheit.
    Vorher gab es hier nie Intervalle (Nutzerbefund Okt. 2026)."""
    today = dt.date(2026, 6, 17)   # Mittwoch
    _seed_fresh(today)
    store.upsert_strava_activities([ride(500 + i, dt.datetime.combine(
        today - dt.timedelta(days=i), dt.time(9)), dist_m=90000.0, hr=125.0)
        for i in (1, 2)])
    store.upsert_whoop_recovery([recovery(1, today, 85.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 0.0)
    rc = recommend.build(today=today)
    assert rc.week_load > 1.2 * rc.target_load
    assert rc.kind == "VO2MAX"


def test_yellow_after_long_gap_gets_tempo(monkeypatch):
    today = dt.date(2026, 6, 15)
    _seed_fresh(today)   # letzte Fahrten vor 10/14 Tagen, locker
    store.upsert_whoop_recovery([recovery(1, today, 55.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 5.0)
    rc = recommend.build(today=today)
    assert rc.readiness_band == "yellow"
    assert rc.kind == "TEMPO"


def test_yellow_without_gap_stays_aerobic(monkeypatch):
    today = dt.date(2026, 6, 15)
    _seed_fresh(today)
    store.upsert_strava_activities([ride(600, dt.datetime.combine(
        today - dt.timedelta(days=5), dt.time(9)), hr=170.0)])   # hart vor 5 Tagen
    store.upsert_whoop_recovery([recovery(1, today, 55.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 5.0)
    rc = recommend.build(today=today)
    assert rc.kind == "ENDURANCE"


def test_no_recovery_is_conservative():
    today = dt.date(2026, 6, 15)
    _seed_rides(today)
    rc = recommend.build(today=today)
    assert rc.readiness_band == "unknown"
    # 12 Fahrtage am Stück → das Schutzgeländer (guard.py) verordnet Ruhe.
    assert rc.kind in ("ENDURANCE", "RECOVERY", "REST")


def test_power_ride_counts_as_hard_by_intensity_factor(monkeypatch):
    """Eine 4×4 auf der Rolle hat einen mäßigen Durchschnittspuls (Ein-/Ausfahren,
    Pausen) — erkannt wird sie über NP/FTP. Sonst käme am Folgetag die nächste 4×4."""
    from bikedash import config
    monkeypatch.setattr(config, "ftp_from_config", lambda: 170)
    today = dt.date(2026, 6, 15)
    _seed_fresh(today)
    r = ride(700, dt.datetime.combine(today - dt.timedelta(days=1), dt.time(18)),
             dist_m=25000.0, hr=135.0)
    r.update(weighted_average_watts=148.0, raw_json='{"device_watts": true}')
    store.upsert_strava_activities([r])
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])
    monkeypatch.setattr(recommend, "_current_tsb", lambda rides, today: 5.0)
    rc = recommend.build(today=today)
    assert rc.kind == "ENDURANCE"   # gestern hart → heute Grundlage
