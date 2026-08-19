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

    # today.json ist bewusst route-frei (Datenschutz): kein Route-Feld.
    assert "route" not in data
    # Ohne Heimat-Koordinaten & ohne Netz kein Wetter.
    assert data["weather"] is None
