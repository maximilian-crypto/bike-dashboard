"""Tests für den Fitness-Index.

Zwei Ebenen: die reinen Rechenbausteine (ohne DB, ohne Netz) und der
Gesamtindex gegen eine synthetische Historie. Der wichtigste Test ist
`test_plateau_bleibt_beim_ausgangsniveau` — er hält fest, dass der Index
*nicht* schon deshalb steigt, weil jemand fleißig Einheiten sammelt.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest

from bikedash import fitness, store


# ---------------------------------------------------------------------------
# Reine Rechenbausteine
# ---------------------------------------------------------------------------

def test_punkteskala_ist_verankert_und_symmetrisch():
    assert fitness.points(0.0, 0.2) == pytest.approx(50.0)
    # Volle Skala nach oben und unten liegt spiegelbildlich um 50.
    hoch = fitness.points(0.2, 0.2)
    runter = fitness.points(-0.2, 0.2)
    assert hoch == pytest.approx(100 - runter, abs=1e-9)
    assert 88 < hoch < 92


def test_punkteskala_saettigt_statt_zu_explodieren():
    """Ein Ausreißer darf den Index nicht sprengen — dafür der Tangens."""
    assert fitness.points(5.0, 0.2) <= 100.0
    assert fitness.points(-5.0, 0.2) >= 0.0
    # Doppelte Verbesserung gibt deutlich weniger als doppelt so viel Zuwachs.
    einfach = fitness.points(0.2, 0.2) - 50
    doppelt = fitness.points(0.4, 0.2) - 50
    assert doppelt < 1.6 * einfach


def test_punkte_ohne_bezugswert_sind_none():
    assert fitness.points(None, 0.2) is None


def test_decoupling_punkte_folgen_der_literatur():
    """Unter 5 % gilt als gut aerob konditioniert — das muss sich lohnen."""
    assert fitness.points_from_decoupling(10.0) == pytest.approx(50.0)
    assert fitness.points_from_decoupling(2.0) > 85
    assert fitness.points_from_decoupling(20.0) < 20
    assert fitness.points_from_decoupling(None) is None


def test_stufennamen():
    assert fitness.tier(30) == "Wiedereinstieg"
    assert fitness.tier(50) == "Grundlage"
    assert fitness.tier(75) == "Formstark"
    assert fitness.tier(99) == "Bestform"
    assert fitness.tier(None) == "—"


def test_leistungsschaetzung_waechst_mit_tempo_und_anstieg():
    flach = fitness.estimate_power(30.0, 3600, 0.0, 88.0)
    schnell = fitness.estimate_power(35.0, 3600, 0.0, 88.0)
    bergig = fitness.estimate_power(30.0, 3600, 500.0, 88.0)
    assert flach and schnell and bergig
    assert schnell > flach and bergig > flach
    # Luftwiderstand wächst mit v³: +17 % Tempo kostet deutlich mehr als +17 % Watt.
    assert schnell / flach > 1.17


def test_leistungsschaetzung_ohne_daten_ist_none():
    assert fitness.estimate_power(None, 3600, 0, 88) is None
    assert fitness.estimate_power(30, 0, 0, 88) is None
    assert fitness.estimate_power(0.0, 3600, 0, 88) is None


def test_efficiency_factor_zieht_den_ruhepuls_ab():
    """Die Schläge, die auch im Sessel laufen, tragen nichts zum Vortrieb bei."""
    ohne = fitness.efficiency_factor(200, 150)
    mit = fitness.efficiency_factor(200, 150, rest_hr=50)
    assert mit > ohne
    assert mit == pytest.approx(2.0)
    assert fitness.efficiency_factor(None, 150) is None
    assert fitness.efficiency_factor(200, 0) is None


def test_gesamtmasse():
    assert fitness.total_mass_kg(80) == 90.0
    assert fitness.total_mass_kg(None) == fitness.DEFAULT_MASS_KG
    assert fitness.total_mass_kg(0) == fitness.DEFAULT_MASS_KG


# ---------------------------------------------------------------------------
# Decoupling & HF-Erholung aus Streams
# ---------------------------------------------------------------------------

def _streams(n=1200, drift_bpm=0.0, speed=8.0):
    """Konstantes Tempo; der Puls driftet in der zweiten Hälfte um drift_bpm."""
    t = list(range(n))
    hr = [140 + (drift_bpm if i >= n // 2 else 0) for i in range(n)]
    out = [speed] * n
    return t, hr, out


def test_decoupling_null_bei_stabilem_puls():
    t, hr, out = _streams(drift_bpm=0)
    res = fitness.decoupling_from_streams(t, hr, out)
    assert res is not None
    assert res["decoupling"] == pytest.approx(0.0, abs=0.01)
    assert res["hr_drift"] == pytest.approx(0.0, abs=0.01)


def test_decoupling_positiv_wenn_der_puls_davonlaeuft():
    t, hr, out = _streams(drift_bpm=14)
    res = fitness.decoupling_from_streams(t, hr, out)
    # 140 -> 154 bei gleichem Tempo sind rund 9 % Drift.
    assert res["decoupling"] == pytest.approx(14 / 154 * 100, abs=0.5)
    assert res["hr_drift"] == pytest.approx(14.0)
    assert res["ef_first"] > res["ef_second"]


def test_decoupling_ignoriert_rollpausen():
    """Tempo 0 (Ampel) darf die Hälften nicht unterschiedlich verzerren."""
    t, hr, out = _streams(drift_bpm=0)
    for i in range(100, 200):
        out[i] = 0.0
    res = fitness.decoupling_from_streams(t, hr, out)
    assert res is not None
    assert abs(res["decoupling"]) < 0.5


def test_decoupling_braucht_genug_daten():
    assert fitness.decoupling_from_streams([], [], []) is None
    assert fitness.decoupling_from_streams(list(range(60)), [140] * 60, [8] * 60) is None
    assert fitness.decoupling_from_streams(None, None, None) is None


def test_hf_erholung_findet_den_groessten_abfall():
    t = list(range(600))
    hr = [120] * 200 + [175] * 100 + [130] * 300   # Abfall 45 bpm nach der Spitze
    val = fitness.hr_recovery_60(t, hr)
    assert val == pytest.approx(45.0)


def test_hf_erholung_ohne_abfall_ist_none():
    t = list(range(600))
    assert fitness.hr_recovery_60(t, [140] * 600) is None
    assert fitness.hr_recovery_60([], []) is None


def test_metrics_aus_streams_bevorzugt_watt():
    t, hr, _ = _streams(drift_bpm=10)
    streams = {
        "time": {"data": t},
        "heartrate": {"data": hr},
        "watts": {"data": [200] * len(t)},
        "velocity_smooth": {"data": [8.0] * len(t)},
    }
    import pandas as pd
    m = fitness.metrics_from_streams(streams, 42, pd.Timestamp("2026-05-01"))
    # Watt schlägt Tempo: Gegenwind und Steigung verfälschen das Tempo, nicht die Leistung.
    assert m["basis"] == "power"
    assert m["ride_id"] == 42
    assert m["ride_day"] == "2026-05-01"
    assert m["decoupling"] > 0


def test_metrics_ohne_puls_gibt_es_nicht():
    import pandas as pd
    streams = {"time": {"data": list(range(600))}, "velocity_smooth": {"data": [8.0] * 600}}
    assert fitness.metrics_from_streams(streams, 1, pd.Timestamp("2026-05-01")) is None


# ---------------------------------------------------------------------------
# Gesamtindex gegen synthetische Historie
# ---------------------------------------------------------------------------

def _seed(days=300, gain=0.0, hrv_gain=0.0, rhr_drop=0.0):
    """Historie mit steuerbarem Fortschritt.

    ``gain`` = relativer Tempozuwachs bei GLEICHEM Puls über den Zeitraum.
    """
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    rides, recs = [], []
    for d in range(days):
        day = start + dt.timedelta(days=d)
        prog = d / days
        recs.append({
            "cycle_id": 9000 + d, "date": day.isoformat(), "recovery_score": 60.0,
            "resting_heart_rate": 55.0 * (1 - rhr_drop * prog),
            "hrv_rmssd_milli": 70.0 * (1 + hrv_gain * prog),
            "spo2_percentage": 97.0, "skin_temp_celsius": 34.0, "raw_json": "{}",
        })
        if day.weekday() not in (1, 3, 5):
            continue
        speed = 25.0 * (1 + gain * prog)
        dist_km = 45.0
        mov = dist_km / speed * 3600
        st = dt.datetime.combine(day, dt.time(10, 0))
        rides.append({
            "id": 700000 + d, "name": "R", "type": "Ride", "sport_type": "Ride",
            "start_date": st.isoformat() + "Z", "start_date_local": st.isoformat() + "Z",
            "distance_m": dist_km * 1000, "moving_time_s": mov, "elapsed_time_s": mov,
            "total_elevation_gain_m": 350.0, "average_speed_ms": dist_km * 1000 / mov,
            "max_speed_ms": 14.0, "average_watts": None, "weighted_average_watts": None,
            "max_watts": None, "average_heartrate": 140.0, "max_heartrate": 175.0,
            "kilojoules": None, "suffer_score": None, "raw_json": "{}",
        })
    store.upsert_strava_activities(rides)
    store.upsert_whoop_recovery(recs)
    store.set_state("whoop_max_hr", "185")


def test_ohne_daten_kein_index_aber_eine_begruendung():
    fi = fitness.compute()
    assert not fi.available
    assert fi.reason
    assert fi.to_dict()["score"] is None


def test_zu_kurze_historie_setzt_keinen_anker():
    _seed(days=10, gain=0.2)
    fi = fitness.compute()
    assert not fi.available
    # Ein Anker auf zehn Tagen wäre für immer falsch — also lieber keiner.
    assert fitness.load_anchor() is None


def test_plateau_bleibt_beim_ausgangsniveau():
    """Der Kern der Sache: Einheiten sammeln allein hebt den Index nicht.

    Dieser Fahrer trainiert 300 Tage lang exakt gleich. Effizienz und
    Regeneration müssen bei 50 stehen bleiben — nur die Konsistenz zählt.
    """
    _seed(days=300, gain=0.0)
    fi = fitness.compute()
    assert fi.available
    by = {s.key: s for s in fi.subscores}
    assert by["eff"].score == pytest.approx(50.0, abs=3.0)
    assert by["reg"].score == pytest.approx(50.0, abs=3.0)
    assert by["cap"].score == pytest.approx(50.0, abs=5.0)
    assert fi.score < 62


def test_fortschritt_hebt_den_index():
    _seed(days=300, gain=0.14, hrv_gain=0.25, rhr_drop=0.08)
    fi = fitness.compute()
    by = {s.key: s for s in fi.subscores}
    assert by["eff"].score > 65
    assert by["reg"].score > 65
    assert fi.score > 62
    # … aber nicht bis an den Anschlag: oben muss Luft für das zweite Jahr sein.
    assert fi.score < 95
    assert fi.tier != "—"


def test_verlauf_steigt_monoton_genug_und_liefert_deltas():
    _seed(days=300, gain=0.14, hrv_gain=0.25)
    fi = fitness.compute()
    assert len(fi.history) > 5
    assert fi.history["score"].iloc[-1] > fi.history["score"].iloc[0]
    assert fi.delta_90 is not None and fi.delta_90 > 0
    assert fi.best is not None and fi.best >= fi.score - 0.01


def test_einzelne_fahrt_verschiebt_den_index_kaum():
    """Kein „+1 pro Workout": eine Einheit mehr darf nur Bruchteile bewegen."""
    _seed(days=300, gain=0.10)
    vorher = fitness.compute().score
    gestern = dt.datetime.combine(dt.date.today() - dt.timedelta(days=1), dt.time(10, 0))
    store.upsert_strava_activities([{
        "id": 999999, "name": "Extra", "type": "Ride", "sport_type": "Ride",
        "start_date": gestern.isoformat() + "Z", "start_date_local": gestern.isoformat() + "Z",
        "distance_m": 60000.0, "moving_time_s": 7200, "elapsed_time_s": 7200,
        "total_elevation_gain_m": 400.0, "average_speed_ms": 60000 / 7200,
        "max_speed_ms": 14.0, "average_watts": None, "weighted_average_watts": None,
        "max_watts": None, "average_heartrate": 141.0, "max_heartrate": 175.0,
        "kilojoules": None, "suffer_score": None, "raw_json": "{}",
    }])
    nachher = fitness.compute().score
    assert abs(nachher - vorher) < 2.0


def test_anker_bleibt_stabil_ueber_laeufe():
    """Ein wandernder Anker würde jeden Fortschritt wegkürzen."""
    _seed(days=300, gain=0.14)
    erst = fitness.compute().anchor
    zweit = fitness.compute().anchor
    assert erst == zweit == fitness.load_anchor()
    fitness.reset_anchor()
    assert fitness.load_anchor() is None


def test_compute_ohne_persist_schreibt_nichts():
    _seed(days=300, gain=0.1)
    fi = fitness.compute(persist=False)
    assert fi.available
    assert store.get_kv(fitness.KV_ANCHOR) is None


def test_fehlendes_signal_kostet_keine_punkte():
    """Ohne Whoop und ohne Streams muss der Index aus dem Rest entstehen."""
    _seed(days=300, gain=0.14)
    store.set_kv(fitness.KV_ANCHOR, store.dumps({
        "created": "2026-01-01", "from": "2026-01-01", "to": "2026-02-01",
        "ef": {"estimate": 1.5}, "ctl": 40.0, "hrv": None, "rhr": None,
    }))
    fi = fitness.compute()
    by = {s.key: s for s in fi.subscores}
    assert by["reg"].score is None
    assert by["dur"].score is None
    assert fi.available          # trotzdem ein Index
    assert by["reg"].confidence == "keine Daten"


def test_to_dict_ist_json_tauglich():
    import json
    _seed(days=300, gain=0.14)
    d = fitness.compute().to_dict()
    json.dumps(d)                 # darf nicht werfen
    assert d["score"] is not None
    assert d["tier"]
    assert "eff" in d["subscores"]


def test_streams_offen_zaehlt_und_wird_abgehakt():
    _seed(days=300, gain=0.1)
    offen = fitness.streams_pending()
    assert offen > 0
    fitness._mark_attempted({700000 + 3})
    assert fitness.streams_pending() <= offen


def test_tempo_bei_referenzpuls_braucht_pulsspreizung():
    """Ohne Streuung im Puls wäre die Regressionsgerade frei erfunden."""
    import pandas as pd
    gleich = pd.DataFrame({
        "hr": [140.0] * 8, "speed_kmh": [26.0] * 8, "is_indoor": [False] * 8,
    })
    assert fitness.speed_at_hr(gleich, 140) is None
    gestreut = pd.DataFrame({
        "hr": [125.0, 130, 135, 140, 145, 150, 155, 160],
        "speed_kmh": [22.0, 23, 24, 25, 26, 27, 28, 29],
        "is_indoor": [False] * 8,
    })
    assert fitness.speed_at_hr(gestreut, 140) == pytest.approx(25.0, abs=0.3)
