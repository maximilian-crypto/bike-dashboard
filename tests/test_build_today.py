"""Tests für build_today.py – schreibt today.json in tmp_path (nie ins echte mobile/).

Ohne Netzwerk: ORS/Wetter sind nicht konfiguriert, also bleiben route & weather None.
Die conftest-Fixture lenkt DB/Config auf eine Wegwerf-Umgebung.
"""

from __future__ import annotations

import datetime as dt
import json

import build_today
from bikedash import store

from .helpers import recovery, ride


def _seed(today):
    rides = [ride(100 + i, dt.datetime.combine(today - dt.timedelta(days=i * 2 + 3),
                                               dt.time(9)))
             for i in range(8)]
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "185")
    store.upsert_whoop_recovery([recovery(1, today, 90.0)])


def test_parse_cadence():
    assert build_today._parse_cadence("85–95") == (85, 95)   # en-dash wie in recommend.py
    assert build_today._parse_cadence("90-100") == (90, 100)
    assert build_today._parse_cadence("85") == (85, 85)
    assert build_today._parse_cadence("–") == (None, None)
    assert build_today._parse_cadence("") == (None, None)


def test_build_writes_valid_today_json(tmp_path):
    today = dt.date(2026, 6, 15)
    _seed(today)

    out = tmp_path / "today.json"
    payload = build_today.build(out, today=today)

    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == payload

    assert data["date"] == "2026-06-15"
    assert data["generated_at"].endswith("+00:00")

    rec = data["recommendation"]
    assert rec["title"] and rec["kind"] in {"RECOVERY", "ENDURANCE", "TEMPO", "THRESHOLD", "REST"}
    assert isinstance(rec["duration_min"], list) and len(rec["duration_min"]) == 2
    if rec["cadence"] != "–":
        assert rec["cadence_low"] is not None and rec["cadence_high"] is not None

    z = data["zones"]
    assert z["max_hr"] == 185
    assert z["rest_hr"] == 52          # aus dem Recovery-Ruhepuls im Helper
    assert z["method"] == "Karvonen/HRR"

    # Meilenstein-Feld ist da und (mit geseedeten Fahrten) befüllt.
    assert "milestone" in data
    assert data["milestone"] is not None
    assert data["milestone"]["orden_total"] >= 1
    assert data["milestone"]["total_km"] > 0
    # Die PWA formuliert den Banner-Text abhängig von der Zielart.
    assert data["milestone"]["next_kind"] in ("orden", "step", None)

    # today.json ist bewusst route-frei (Datenschutz): kein Route-Feld.
    assert "route" not in data
    # Ohne Heimat-Koordinaten & ohne Netz kein Wetter.
    assert data["weather"] is None


def test_today_json_enthaelt_die_shift_matrix(tmp_path):
    """Die PWA schlaegt die Gangempfehlung in today.json nach."""
    from bikedash import shift

    today = dt.date(2026, 6, 15)
    _seed(today)
    payload = build_today.build(tmp_path / "today.json", today=today)

    assert payload["shift"]["cells"]["above|in"]["action"] == "leichter"
    assert payload["shift"] == json.loads(json.dumps(shift.matrix_payload()))


def test_timing_bleibt_leer_ohne_wetter(tmp_path):
    """Ohne Heimat-Koordinate gibt es keine Vorhersage – das Feld faellt weg."""
    today = dt.date(2026, 6, 15)
    _seed(today)
    payload = build_today.build(tmp_path / "today.json", today=today)
    assert payload["timing"] is None


def test_timing_landet_in_today_json(tmp_path, monkeypatch):
    """Mit Vorhersage steht das beste Zeitfenster route- und koordinatenfrei drin."""
    import datetime as _dt

    from bikedash import daytime, weather

    today = _dt.date(2026, 6, 15)          # Montag -> Fenster 13–20 Uhr
    _seed(today)

    def fake_hours(cfg, days=2):
        out = []
        for h in range(24):
            windig = not (16 <= h < 19)
            out.append(weather.Hour(
                time=_dt.datetime.combine(today, _dt.time(h)),
                temp_c=19.0, feels_c=19.0, precip_mm=0.0, precip_prob=0, code=0,
                wind_kmh=32.0 if windig else 7.0,
                gust_kmh=45.0 if windig else 10.0,
                wind_deg=225.0, uv=3.0, is_day=True,
            ))
        return out

    monkeypatch.setattr(weather, "hourly_forecast", fake_hours)
    monkeypatch.setattr(daytime.weather, "hourly_forecast", fake_hours)

    payload = build_today.build(tmp_path / "today.json", today=today)
    timing = payload["timing"]
    assert timing is not None
    assert timing["window_from"] == 13 and timing["window_to"] == 20
    assert timing["settled"] is True                      # schoener Tag -> Wind entscheidet
    assert timing["best"]["start"].startswith("16")       # windstillstes Fenster
    assert "lat" not in json.dumps(timing) and "lon" not in json.dumps(timing)
