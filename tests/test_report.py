"""Tests für den Morgen-Report (bikedash/report.py).

Kern: der Push geht genau einmal pro Tag raus, sobald die heutige Whoop-
Recovery da ist, spätestens zur Frist — und nie vor dem frühesten Zeitpunkt.
Ohne Netzwerk: ntfy wird durch einen Stub ersetzt, Wetter bleibt aus (keine
Heimat-Koordinaten).
"""

from __future__ import annotations

import datetime as dt

from bikedash import report, store, zwift

from .helpers import recovery, ride

CFG = {"report": {"ntfy_topic": "max-test-topic"}}


def _local(h: int, m: int = 0, day: dt.date = dt.date(2026, 9, 18)) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(h, m), tzinfo=report.TZ)


def _seed(today: dt.date, with_today_recovery: bool = True) -> None:
    rides = [ride(100 + i, dt.datetime.combine(today - dt.timedelta(days=i * 2 + 1), dt.time(9)))
             for i in range(8)]
    store.upsert_strava_activities(rides)
    store.set_state("whoop_max_hr", "197")
    recs = [recovery(10 + i, today - dt.timedelta(days=i), 70.0) for i in range(1, 6)]
    if with_today_recovery:
        recs.append(recovery(1, today, 74.0))
    store.upsert_whoop_recovery(recs)


# --- Entscheidung „fällig?" (rein) ------------------------------------------

def test_due_sends_as_soon_as_recovery_is_there():
    ok, why = report.due(_local(7, 10), has_recovery=True, sent=None)
    assert ok and "Recovery" in why


def test_due_waits_without_recovery_before_deadline():
    ok, why = report.due(_local(8, 30), has_recovery=False, sent=None)
    assert not ok and "wartet" in why


def test_due_fires_at_deadline_even_without_recovery():
    ok, why = report.due(_local(10, 0), has_recovery=False, sent=None)
    assert ok and "Frist" in why


def test_due_never_before_earliest():
    ok, _ = report.due(_local(5, 45), has_recovery=True, sent=None)
    assert not ok


def test_due_only_once_per_day():
    today = dt.date(2026, 9, 18)
    ok, why = report.due(_local(9, 0, today), has_recovery=True, sent=today)
    assert not ok and "schon gesendet" in why
    # Gestern gesendet zählt nicht.
    ok, _ = report.due(_local(9, 0, today), has_recovery=True, sent=today - dt.timedelta(days=1))
    assert ok


# --- Datenbank-Seite ----------------------------------------------------------

def test_recovery_present_matches_today_only():
    today = dt.date(2026, 9, 18)
    _seed(today, with_today_recovery=False)
    assert not report.recovery_present(today)
    store.upsert_whoop_recovery([recovery(1, today, 74.0)])
    assert report.recovery_present(today)


def test_mark_and_last_sent_roundtrip():
    assert report.last_sent() is None
    report.mark_sent(dt.date(2026, 9, 18))
    assert report.last_sent() == dt.date(2026, 9, 18)


# --- Text ---------------------------------------------------------------------

def test_first_line_carries_the_decision(monkeypatch):
    monkeypatch.setenv("ATHLETE_FTP", "170")
    today = dt.date(2026, 9, 18)
    _seed(today)
    zwift.remember(zwift.PushResult("sent", name="Bikedash 18-09 Grundlage Z2 89min",
                                    date=today.isoformat()))
    title, msg = report.build_text(CFG, today=today)
    assert title.startswith("Heute: ")
    lines = msg.splitlines()
    if "Ruhetag" in title:
        assert lines[0].startswith("Erhol dich")
        return
    assert " min" in title and " W" in title
    assert "Trittfrequenz" in lines[0] and " W" in lines[0]
    assert any(l.startswith("Zwift: Workout liegt bereit") for l in lines)
    assert any(l.startswith("Recovery 74 %") for l in lines)
    assert any(l.startswith("Woche:") for l in lines)
    # Titel muss als HTTP-Header durchgehen.
    title.encode("latin-1")


def test_stale_recovery_is_said_out_loud():
    today = dt.date(2026, 9, 18)
    _seed(today, with_today_recovery=False)
    _, msg = report.build_text(CFG, today=today, stale_recovery=True)
    assert msg.splitlines()[0].startswith("Whoop-Recovery von heute fehlt noch")


def test_zwift_line_only_for_today(monkeypatch):
    monkeypatch.setenv("ATHLETE_FTP", "170")
    today = dt.date(2026, 9, 18)
    _seed(today)
    zwift.remember(zwift.PushResult("sent", name="x", date="2026-09-17"))   # gestern
    _, msg = report.build_text(CFG, today=today)
    assert "Zwift" not in msg


# --- Senden -------------------------------------------------------------------

def test_send_if_due_sends_once_and_marks(monkeypatch):
    today = dt.date(2026, 9, 18)
    _seed(today)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(report, "send_push", lambda cfg, t, m: sent.append((t, m)) or True)

    now = _local(7, 30, today).astimezone(dt.timezone.utc)
    status, why = report.send_if_due(CFG, now=now)
    assert status == "sent" and len(sent) == 1
    assert report.last_sent() == today

    status, _ = report.send_if_due(CFG, now=now + dt.timedelta(minutes=30))
    assert status == "already" and len(sent) == 1


def test_send_if_due_waits_then_fires_at_deadline(monkeypatch):
    today = dt.date(2026, 9, 18)
    _seed(today, with_today_recovery=False)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(report, "send_push", lambda cfg, t, m: sent.append((t, m)) or True)

    status, _ = report.send_if_due(CFG, now=_local(8, 0, today).astimezone(dt.timezone.utc))
    assert status == "waiting" and not sent
    status, _ = report.send_if_due(CFG, now=_local(10, 5, today).astimezone(dt.timezone.utc))
    assert status == "sent" and len(sent) == 1
    assert "fehlt noch" in sent[0][1]


def test_send_if_due_without_topic():
    status, _ = report.send_if_due({}, now=_local(9).astimezone(dt.timezone.utc))
    assert status == "no_topic"


def test_failed_push_does_not_mark_sent(monkeypatch):
    today = dt.date(2026, 9, 18)
    _seed(today)
    monkeypatch.setattr(report, "send_push", lambda cfg, t, m: False)
    status, _ = report.send_if_due(CFG, now=_local(8, 0, today).astimezone(dt.timezone.utc))
    assert status == "failed" and report.last_sent() is None


def test_send_push_sets_click_header(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

    def _post(url, data, headers, timeout):
        seen.update(url=url, headers=headers)
        return _R()

    monkeypatch.setattr(report.requests, "post", _post)
    cfg = {"report": {"ntfy_topic": "t0pic", "dashboard_url": "https://x.streamlit.app"}}
    assert report.send_push(cfg, "Heute: Grundlage Z2 · 89 min", "hallo")
    assert seen["url"] == "https://ntfy.sh/t0pic"
    assert seen["headers"]["Click"] == "https://x.streamlit.app"
    assert not report.send_push({"report": {"ntfy_topic": "DEIN_NTFY_THEMA"}}, "t", "m")
