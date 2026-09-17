"""Tests für den Saisonplan (progressive Überlast mit Zieldatum)."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from bikedash import season


def _rides(weekly_load: float, weeks: int, until: dt.date) -> pd.DataFrame:
    """Gleichmäßige Historie: `weeks` Wochen mit je `weekly_load` Last."""
    rows = []
    for w in range(weeks):
        monday = until - dt.timedelta(days=until.weekday() + 7 * (w + 1))
        for d in range(3):                      # drei Einheiten pro Woche
            start = dt.datetime.combine(monday + dt.timedelta(days=d * 2), dt.time(18))
            rows.append({"start": start, "date": start.date(),
                         "load": weekly_load / 3.0})
    return pd.DataFrame(rows).sort_values("start").reset_index(drop=True)


# --- Takt der Entlastungswochen -------------------------------------------

def test_every_fourth_week_is_deload():
    assert [season.is_deload_week(w) for w in range(8)] == [
        False, False, False, True, False, False, False, True]


def test_first_week_is_never_deload():
    assert season.is_deload_week(0) is False


# --- Phasen ----------------------------------------------------------------

def test_phases_by_weeks_remaining():
    assert season.phase_for(24) == season.PHASE_BASIS
    assert season.phase_for(12) == season.PHASE_BASIS
    assert season.phase_for(11) == season.PHASE_AUFBAU
    assert season.phase_for(4) == season.PHASE_AUFBAU
    assert season.phase_for(3) == season.PHASE_FORM
    assert season.phase_for(0) == season.PHASE_SAISON


def test_base_phase_allows_only_one_hard_day():
    """Grundlage baut über Umfang, nicht über Intensität."""
    assert season.hard_days_for(season.PHASE_BASIS) == 1
    assert season.hard_days_for(season.PHASE_AUFBAU) == 2


# --- Sollkurve -------------------------------------------------------------

def test_ramp_grows_by_ten_percent_per_build_week():
    base = 100.0
    assert season.ramp_target(base, 0) == 100.0
    assert abs(season.ramp_target(base, 1) - 110.0) < 1e-9
    assert abs(season.ramp_target(base, 2) - 121.0) < 1e-9


def test_deload_week_drops_below_previous_week():
    base = 100.0
    assert season.ramp_target(base, 3) < season.ramp_target(base, 2)
    # 65 % dessen, was der Plan diese Woche sonst fordern würde (100 · 1,1³).
    assert abs(season.ramp_target(base, 3) - 133.1 * season.DELOAD_FACTOR) < 1e-9


def test_deload_does_not_consume_a_build_step():
    """Nach der Entlastung geht es dort weiter, wo die Steigerung stand."""
    base = 100.0
    assert abs(season.ramp_target(base, 4) - 133.1) < 1e-9   # 100 * 1,1^3


def test_ctl_ceiling_caps_absurd_ramps():
    """Aus dem Stand darf der Plan keinen Sprung ins Nichts fordern."""
    ceiling = season.ctl_ceiling(10.0)
    assert ceiling == 7.0 * (10.0 + 6.0 * season.MAX_CTL_RAMP)
    assert season.ctl_ceiling(None) is None


def test_recent_best_week_ignores_zero_weeks():
    assert season.recent_best_week([50.0, 0.0, 80.0]) == 80.0
    assert season.recent_best_week([0.0, 0.0]) is None
    assert season.recent_best_week([]) is None


# --- Zusammenbau -----------------------------------------------------------

def test_plan_starts_from_actual_volume_not_a_wish():
    today = dt.date(2026, 9, 21)                 # ein Montag
    rides = _rides(70.0, 6, today)
    plan = season.build(rides, today=today, season_start=dt.date(2027, 3, 1))
    assert abs(plan.baseline_load - 70.0) < 1.0
    assert plan.week_index == 0
    assert plan.phase == season.PHASE_BASIS


def test_plan_ramps_over_following_weeks():
    """Kern des Ganzen: das Wochenziel steigt, statt den Schnitt zu spiegeln."""
    today = dt.date(2026, 9, 21)
    rides = _rides(70.0, 6, today)
    first = season.build(rides, today=today, season_start=dt.date(2027, 3, 1))
    later = season.build(rides, today=today + dt.timedelta(days=14),
                         season_start=dt.date(2027, 3, 1))
    assert later.week_index == 2
    assert later.target_load > first.target_load


def test_anchor_is_persisted_so_the_plan_keeps_direction():
    today = dt.date(2026, 9, 21)
    rides = _rides(70.0, 6, today)
    season.build(rides, today=today, season_start=dt.date(2027, 3, 1))
    anchor = season.load_anchor()
    assert anchor is not None
    start, baseline = anchor
    assert start == today
    assert abs(baseline - 70.0) < 1.0


def test_reality_clamp_after_a_break():
    """Nach einer Pause wird herangeführt, nicht aufgeholt."""
    today = dt.date(2026, 9, 21)
    season.save_anchor(dt.date(2026, 6, 1), 200.0)    # alter, ambitionierter Plan
    rides = _rides(40.0, 3, today)                    # real zuletzt nur 40
    plan = season.build(rides, today=today, season_start=dt.date(2027, 3, 1))
    assert plan.target_load <= 40.0 * season.CATCHUP_CAP + 0.1
    assert any("Realität" in r for r in plan.rationale)


def test_deload_week_is_flagged_and_reasoned():
    today = dt.date(2026, 9, 21)
    season.save_anchor(today - dt.timedelta(days=21), 100.0)   # Planwoche 3
    rides = _rides(100.0, 6, today)
    plan = season.build(rides, today=today, season_start=dt.date(2027, 3, 1))
    assert plan.week_index == 3
    assert plan.is_deload
    assert any("Entlastungswoche" in r for r in plan.rationale)


def test_empty_history_still_yields_a_plan():
    plan = season.build(pd.DataFrame(), today=dt.date(2026, 9, 21),
                        season_start=dt.date(2027, 3, 1))
    assert plan.target_load >= season.MIN_WEEKLY_LOAD
    assert plan.current_ctl is None


def test_projection_reaches_the_season_and_grows():
    proj = season.projection(70.0, 24, current_ctl=10.0)
    assert len(proj) == 24
    assert proj[-1]["target_load"] > proj[0]["target_load"]
    assert proj[-1]["ctl"] > proj[0]["ctl"]
    assert any(p["is_deload"] for p in proj)
