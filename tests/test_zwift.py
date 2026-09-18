"""Tests für die Zwift-Zustellung über intervals.icu (bikedash/zwift.py).

Ohne Netzwerk: die HTTP-Session wird durch einen Stub ersetzt, der die Aufrufe
mitschreibt. So lässt sich prüfen, dass pro Tag genau ein Eintrag entsteht,
Änderungen aktualisiert und Ruhetage aufgeräumt werden — die Kernzusage
„kein manueller Schritt, keine Duplikate".
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from bikedash import power, zwift

FTP = 170
DAY = dt.date(2026, 9, 18)
CFG = {"intervals": {"api_key": "k3y", "athlete_id": "i12345"}}


def _rc(kind: str, minutes: int, cadence: str = "85–95"):
    """Nachbau einer Recommendation mit echter Blockstruktur aus power.py."""
    blocks = power.structure(kind, minutes, FTP, cadence) if kind != "REST" else []
    plan = [{"label": b.label, "minutes": b.minutes, "low_w": b.low_w,
             "high_w": b.high_w, "zone": b.zone, "cadence": b.cadence} for b in blocks]
    titles = {"ENDURANCE": "Grundlagenausdauer (Z2)", "THRESHOLD": "Schwellen-Intervalle (Z4)",
              "REST": "Ruhetag", "RECOVERY": "Lockerer Erholungs-Spin"}
    return SimpleNamespace(kind=kind, title=titles[kind], ftp=FTP if kind != "REST" else None,
                           power_plan=plan)


class _Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data
        self.text = text or ("{}" if data is not None else "")

    def json(self):
        return self._data


class _Session:
    """Stub für requests.Session: liefert vorbereitete Antworten, protokolliert Aufrufe."""

    def __init__(self, existing=None, fail_get=False, fail_post=False):
        self.existing = existing or []
        self.fail_get = fail_get
        self.fail_post = fail_post
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if self.fail_get:
            return _Resp(401, text="Unauthorized")
        return _Resp(200, self.existing)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if self.fail_post:
            return _Resp(422, text="bad request")
        return _Resp(200, {"id": 4711, **kw["json"]})

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw))
        return _Resp(200, {"id": 99, **kw["json"]})

    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, kw))
        return _Resp(200, {})


# --- Übersetzung ------------------------------------------------------------

def test_workout_text_matches_dashboard_table_block_for_block():
    rc = _rc("ENDURANCE", 89)
    text = zwift.workout_text(rc.power_plan, FTP)
    lines = [l for l in text.splitlines() if l.startswith("- ")]
    # Ein Schritt je Block, gleiche Minuten wie in der Tabelle.
    assert len(lines) == len(rc.power_plan)
    assert [int(l.split()[1].rstrip("m")) for l in lines] == [b["minutes"] for b in rc.power_plan]
    assert "Einfahren" in text and "Hauptteil" in text and "Ausfahren" in text
    # Z2-Band 95–128 W bei FTP 170 → Mitte 111,5 W → 66 % FTP, Kadenzmitte 90.
    assert "- 71m 66% 90rpm" in text
    # Ausfahren hat keine Kadenzvorgabe.
    assert lines[-1].endswith("%")


def test_workout_text_intervals_have_no_trailing_rest():
    rc = _rc("THRESHOLD", 70, "85–100")
    text = zwift.workout_text(rc.power_plan, FTP)
    steps = [l for l in text.splitlines() if l.startswith("- ")]
    work = [l for l in steps if "98%" in l]          # Z4 155–179 W → 98 % FTP
    rest = [l for l in steps if "50%" in l and "92rpm" not in l]
    assert len(work) >= power.MIN_REPS
    # Nach dem letzten Intervall folgt direkt das Ausfahren — wie in der Tabelle.
    assert steps[-2] == work[-1]
    # Pausen: eine weniger als Intervalle, plus das Ausfahren (ebenfalls Z1 ohne rpm).
    assert len(rest) == len(work) - 1 + 1
    # Keine Nx-Wiederholungen: die hätten eine Pause zu viel.
    assert "x\n" not in text


def test_workout_text_needs_ftp_and_plan():
    assert zwift.workout_text([], FTP) == ""
    assert zwift.workout_text(_rc("ENDURANCE", 60).power_plan, 0) == ""


def test_workout_name_is_zwift_safe():
    name = zwift.workout_name("ENDURANCE", DAY, 89)
    assert name == "Bikedash 18-09 Grundlage Z2 89min"
    for kind in ("RECOVERY", "ENDURANCE", "TEMPO", "THRESHOLD"):
        n = zwift.workout_name(kind, DAY, 45)
        assert all(c.isalnum() or c in " -" for c in n), n
        assert n.startswith("Bikedash 18-09")


def test_ascii_name_strips_umlauts_and_symbols():
    assert zwift._ascii_name("Schwelle · Über/Änderung ×3") == "Schwelle Ueber Aenderung 3"


def test_cadence_and_percent_helpers():
    assert zwift._cadence_rpm("85–95") == 90
    assert zwift._cadence_rpm("85-100") == 92
    assert zwift._cadence_rpm(None) is None
    assert zwift._cadence_rpm("–") is None
    assert zwift._pct_of_ftp(155, 179, 170) == 98


def test_event_payload_fields():
    rc = _rc("ENDURANCE", 89)
    ev = zwift.event_payload(rc, DAY, FTP)
    assert ev["category"] == "WORKOUT" and ev["type"] == "Ride" and ev["indoor"] is True
    assert ev["start_date_local"] == "2026-09-18T00:00:00"
    assert ev["external_id"] == "bikedash-2026-09-18"
    assert ev["moving_time"] == sum(b["minutes"] for b in rc.power_plan) * 60
    assert ev["icu_ftp"] == FTP
    assert ev["description"].startswith("Bike-Dashboard, Tagesempfehlung vom 18.09.2026")


# --- Zustellung -------------------------------------------------------------

def test_push_skipped_without_config():
    res = zwift.push_today({}, _rc("ENDURANCE", 89), DAY, session=_Session())
    assert res.status == "skipped" and not res.ok


def test_placeholder_key_counts_as_unconfigured():
    assert not zwift.configured({"intervals": {"api_key": "DEIN_INTERVALS_ICU_KEY"}})
    assert zwift.settings({"intervals": {"api_key": "abc"}}) == ("abc", "0")


def test_push_creates_event_when_none_exists():
    s = _Session()
    res = zwift.push_today(CFG, _rc("ENDURANCE", 89), DAY, session=s)
    assert res.status == "sent" and res.ok
    assert res.event_id == 4711 and res.name == "Bikedash 18-09 Grundlage Z2 89min"
    methods = [c[0] for c in s.calls]
    assert methods == ["GET", "POST"]
    get_kw = s.calls[0][2]
    assert get_kw["params"] == {"oldest": "2026-09-18", "newest": "2026-09-18",
                                "category": "WORKOUT"}
    assert get_kw["auth"] == ("API_KEY", "k3y")
    assert s.calls[1][1] == "https://intervals.icu/api/v1/athlete/i12345/events"
    assert s.calls[1][2]["json"]["external_id"] == "bikedash-2026-09-18"


def test_push_updates_existing_event_instead_of_duplicating():
    existing = [{"id": 99, "external_id": "bikedash-2026-09-18",
                 "name": "Bikedash 18-09 Grundlage Z2 60min", "description": "alt"}]
    s = _Session(existing=existing)
    res = zwift.push_today(CFG, _rc("ENDURANCE", 89), DAY, session=s)
    assert res.status == "updated" and res.event_id == 99
    assert [c[0] for c in s.calls] == ["GET", "PUT"]
    assert s.calls[1][1].endswith("/events/99")


def test_push_leaves_identical_event_alone():
    rc = _rc("ENDURANCE", 89)
    ev = zwift.event_payload(rc, DAY, FTP)
    s = _Session(existing=[{"id": 5, "external_id": ev["external_id"],
                            "name": ev["name"], "description": ev["description"]}])
    res = zwift.push_today(CFG, rc, DAY, session=s)
    assert res.status == "unchanged" and res.ok and res.event_id == 5
    assert [c[0] for c in s.calls] == ["GET"]


def test_foreign_events_on_same_day_are_ignored():
    s = _Session(existing=[{"id": 1, "external_id": None, "name": "Fremdes Workout"}])
    res = zwift.push_today(CFG, _rc("ENDURANCE", 89), DAY, session=s)
    assert res.status == "sent"
    assert [c[0] for c in s.calls] == ["GET", "POST"]


def test_rest_day_removes_previous_workout():
    s = _Session(existing=[{"id": 7, "external_id": "bikedash-2026-09-18", "name": "x"}])
    res = zwift.push_today(CFG, _rc("REST", 0), DAY, session=s)
    assert res.status == "deleted" and res.event_id == 7
    assert [c[0] for c in s.calls] == ["GET", "DELETE"]


def test_rest_day_without_event_is_skipped():
    s = _Session()
    res = zwift.push_today(CFG, _rc("REST", 0), DAY, session=s)
    assert res.status == "skipped" and "Ruhetag" in res.detail
    assert [c[0] for c in s.calls] == ["GET"]


def test_http_errors_never_raise():
    res = zwift.push_today(CFG, _rc("ENDURANCE", 89), DAY, session=_Session(fail_get=True))
    assert res.status == "error" and "401" in res.detail
    res = zwift.push_today(CFG, _rc("ENDURANCE", 89), DAY, session=_Session(fail_post=True))
    assert res.status == "error" and "422" in res.detail


def test_remember_and_last_result_roundtrip():
    res = zwift.PushResult("sent", name="Bikedash 18-09 Grundlage Z2 89min",
                           event_id=1, date="2026-09-18", at="2026-09-18T04:05:00+00:00")
    zwift.remember(res)
    back = zwift.last_result()
    assert back == res
    line = zwift.status_line(back, today=DAY)
    assert "Bikedash 18-09 Grundlage Z2 89min" in line and "Intervals.icu" in line
    # Gestriges Ergebnis wird nicht als „heute bereit" verkauft.
    assert "nächsten Sync-Lauf" in zwift.status_line(back, today=DAY + dt.timedelta(days=1))
    assert "kein Workout" in zwift.status_line(None)


def test_status_line_reports_errors():
    res = zwift.PushResult("error", detail="HTTP 401 Unauthorized", date="2026-09-18")
    assert "Fehler" in zwift.status_line(res, today=DAY) and "401" in zwift.status_line(res, today=DAY)
