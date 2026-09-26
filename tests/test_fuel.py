"""Tests für bikedash/fuel.py – Mehrbedarf fürs Workout in Portionen."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from bikedash import fuel, recommend, report, store

from .helpers import recovery, ride

PLAN_Z2 = [
    {"minutes": 10, "low_w": 76, "high_w": 94},
    {"minutes": 72, "low_w": 95, "high_w": 127},
    {"minutes": 8, "low_w": 76, "high_w": 94},
]


def test_kj_is_roughly_kcal():
    # Die Faustregel „1 kJ am Pedal ≈ 1 kcal Umsatz" muss aus der Rechnung folgen.
    assert fuel.kcal_from_kj(1000) == pytest.approx(996, abs=5)


def test_plan_kj_uses_band_middle():
    assert fuel.plan_kj([{"minutes": 60, "low_w": 90, "high_w": 110}]) == pytest.approx(360)


def test_extra_excludes_resting_burn():
    gross, src = fuel.gross_kcal("ENDURANCE", 90, 70, PLAN_Z2)
    p = fuel.build_plan("ENDURANCE", 90, 70, PLAN_Z2)
    assert src == "power" and p.source == "power"
    assert p.kcal_extra == round(gross - fuel.rest_kcal(90, 70))
    assert 350 < p.kcal_extra < 600


def test_met_fallback_scales_with_weight_and_intensity():
    light = fuel.build_plan("ENDURANCE", 60, 60)
    heavy = fuel.build_plan("ENDURANCE", 60, 90)
    hard = fuel.build_plan("THRESHOLD", 60, 60)
    assert light.source == "met"
    assert heavy.kcal_extra > light.kcal_extra
    assert hard.kcal_extra > light.kcal_extra


def test_split_adds_up_and_short_rides_skip_during():
    short = fuel.split(200, 45)
    assert short["during"] == 0
    assert sum(short.values()) == pytest.approx(200)
    long = fuel.split(600, 120)
    assert long["during"] > 0
    assert long["during"] <= 300          # höchstens die Hälfte unterwegs
    assert sum(long.values()) == pytest.approx(600)


def test_portions_round_up_in_halves_never_zero():
    cola = fuel.FOODS["cola"]
    assert fuel.portions(10, cola) == 0.5
    assert fuel.portions(139, cola) == 1.0
    assert fuel.portions(140, cola) == 1.5
    assert fuel.portions(0, cola) == 0.0
    assert fuel.portion(300, "cola").label == "2½ Dosen Cola"
    assert fuel.portion(50, "toast").label == "½ Scheibe Toast mit Honig"
    assert fuel.portion(170, "maoam").label == "2 Maoam Bloxx"


def test_every_phase_covers_its_kcal():
    p = fuel.build_plan("ENDURANCE", 90, 70, PLAN_Z2)
    assert [ph.key for ph in p.phases] == ["before", "during", "after"]
    assert sum(ph.kcal for ph in p.phases) == pytest.approx(p.kcal_extra, abs=2)
    for ph in p.phases:
        for po in ph.portions:
            assert po.count * fuel.FOODS[po.key].kcal >= ph.kcal


def test_rest_day_has_no_extra_but_keeps_meal_note():
    p = fuel.build_plan("REST", 0, 70)
    assert not p.available
    assert p.short() == ""
    assert "Mahlzeiten" in p.notes[0]


def test_rest_after_ride_puts_everything_after():
    p = fuel.build_plan("REST", 0, 70, done_today_kcal=620)
    assert p.source == "ride" and p.kcal_extra == 620
    assert [ph.key for ph in p.phases] == ["after"]


def test_ride_extra_prefers_strava_kj():
    row = pd.Series({"moving_time_s": 3600, "kilojoules": 600.0})
    assert fuel.ride_extra_kcal(row, 70) == pytest.approx(fuel.kcal_from_kj(600) - 70)
    row = pd.Series({"moving_time_s": 3600, "kilojoules": None})
    assert fuel.ride_extra_kcal(row, 70) == pytest.approx((fuel.MET_UNKNOWN - 1) * 70)


def test_never_suggests_eating_less():
    for kind in ("RECOVERY", "ENDURANCE", "TEMPO", "THRESHOLD"):
        p = fuel.build_plan(kind, 60, 70)
        assert p.kcal_extra > 0
        assert all(ph.kcal >= 0 for ph in p.phases)


def test_to_dict_is_json_ready():
    d = fuel.build_plan("ENDURANCE", 90, 70, PLAN_Z2).to_dict()
    assert d["short"].startswith("Extra essen")
    assert d["phases"][1]["text"].startswith("2 Dosen Cola")
    assert isinstance(d["kcal_range"], list)


def _seed_today(today, rode_today=False):
    rides = [ride(100 + i, dt.datetime.combine(today - dt.timedelta(days=i * 2 + 3),
                                               dt.time(9))) for i in range(8)]
    if rode_today:
        r = ride(99, dt.datetime.combine(today, dt.time(7)))
        r["kilojoules"] = 700.0
        rides.append(r)
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "185")
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])


def test_for_recommendation_and_report_line():
    today = dt.date(2026, 6, 15)
    _seed_today(today)
    rc = recommend.build(today)
    fp = fuel.for_recommendation(rc, today)
    assert fp.available and fp.kcal_extra > 0
    assert report.fuel_line(rc, today).startswith("🍽 Extra essen")


def test_for_recommendation_after_todays_ride():
    today = dt.date(2026, 6, 15)
    _seed_today(today, rode_today=True)
    rc = recommend.build(today)
    assert rc.kind == "REST"
    fp = fuel.for_recommendation(rc, today)
    assert fp.source == "ride"
    assert fp.kcal_extra > 500
