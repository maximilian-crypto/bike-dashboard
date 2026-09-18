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


# --- Selbstkontrolle des gehosteten Laufs ---------------------------------

def test_zones_expose_ftp_and_load_sources(tmp_path, monkeypatch):
    """today.json muss zeigen, ob FTP angekommen ist und womit gerechnet wurde.

    Sonst faellt eine fehlende Actions-Variable nur durch still zu niedrige
    Lastwerte auf — und das merkt niemand.
    """
    import datetime as _dt
    import json as _json

    from bikedash import store
    from tests.helpers import recovery as _recovery
    from tests.helpers import ride as _ride

    monkeypatch.setenv("ATHLETE_FTP", "170")
    day = _dt.date(2026, 9, 17)

    z = _ride(1, _dt.datetime.combine(day, _dt.time(18)))
    z["type"] = z["sport_type"] = "VirtualRide"
    z["moving_time_s"] = 3600
    z["weighted_average_watts"] = 170.0
    z["raw_json"] = _json.dumps({"device_watts": True, "trainer": True})
    store.upsert_strava_activities([z])
    store.set_state("whoop_max_hr", "197")
    store.upsert_whoop_recovery([_recovery(1, day, 73.0)])

    out = tmp_path / "today.json"
    payload = build_today.build(out, today=day)

    assert payload["zones"]["ftp"] == 170
    assert payload["zones"]["load_sources"].get("power") == 1


def test_load_sources_survives_a_broken_database(monkeypatch):
    """Das Diagnosefeld darf den Tagesplan niemals kippen."""
    def _boom():
        raise RuntimeError("DB weg")
    monkeypatch.setattr(build_today.dataprep, "prep_rides", _boom)
    assert build_today._load_sources() == {}


# --- Zwift-Zustellung (über intervals.icu) ---------------------------------

def test_today_json_reports_zwift_status_when_unconfigured(tmp_path, monkeypatch):
    """Ohne API-Key: Feld da, Status „skipped" — und der Tagesplan läuft durch."""
    monkeypatch.delenv("INTERVALS_API_KEY", raising=False)
    today = dt.date(2026, 6, 15)
    _seed(today)
    payload = build_today.build(tmp_path / "today.json", today=today)
    assert payload["zwift"]["status"] == "skipped"
    assert payload["zwift"]["date"] == "2026-06-15"


def test_today_json_pushes_workout_to_intervals(tmp_path, monkeypatch):
    """Mit Key + FTP wird das Tagesworkout angelegt; Ergebnis in today.json und app_kv."""
    from bikedash import zwift

    class _Resp:
        def __init__(self, data):
            self.status_code, self._data, self.text = 200, data, "{}"

        def json(self):
            return self._data

    calls: list[tuple[str, str]] = []

    class _Session:
        def get(self, url, **kw):
            calls.append(("GET", url))
            return _Resp([])

        def post(self, url, **kw):
            calls.append(("POST", url))
            assert kw["json"]["external_id"] == "bikedash-2026-06-15"
            assert kw["json"]["name"].startswith("Bikedash 15-06")
            return _Resp({"id": 42})

    monkeypatch.setattr(zwift.requests, "Session", _Session)
    monkeypatch.setenv("ATHLETE_FTP", "170")
    monkeypatch.setenv("INTERVALS_API_KEY", "k3y")
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i12345")

    today = dt.date(2026, 6, 15)
    _seed(today)
    payload = build_today.build(tmp_path / "today.json", today=today)

    if payload["recommendation"]["kind"] == "REST":
        assert payload["zwift"]["status"] == "skipped"
        return
    assert payload["zwift"]["status"] == "sent"
    assert payload["zwift"]["event_id"] == 42
    assert [c[0] for c in calls] == ["GET", "POST"]
    assert "athlete/i12345/" in calls[1][1]
    last = zwift.last_result()
    assert last is not None and last.status == "sent" and last.date == "2026-06-15"
