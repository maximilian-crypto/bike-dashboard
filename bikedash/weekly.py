"""Wochenrückblick: sonntagabends eine freundliche Push-Nachricht über die Woche.

Was war (Fahrten, Stunden, Kilometer), was neu ist (Orden, Fitness-Index), wie
der Schlaf war, und ein Satz zur kommenden Woche aus dem Saisonplan.

**Bewusst ohne Soll-Ist-Rot.** Der Rückblick vergleicht nie mit dem Wochenziel
und sagt nie „verfehlt". Eine Woche mit wenig oder gar keinem Training heißt
„ruhige Woche" — Klinikdienste, Krankheit und Alltag sind keine Trainingsfehler,
und ein Rückblick, der schlechtes Gewissen macht, wird irgendwann nicht mehr
gelesen. Motivation entsteht hier aus dem, was geklappt hat.

Zeitpunkt: Sonntag ab ``SEND_FROM`` (18:00 deutscher Zeit). Der Sync läuft alle
vier Stunden; verpasst er den Sonntagabend, wird Montag bis ``CATCH_UP_UNTIL``
nachgeholt — für die abgelaufene Woche. Ein Marker in ``app_kv`` sorgt für
genau einen Rückblick pro Woche.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import dataprep, fitness, milestones, report, season, store

SEND_FROM = dt.time(18, 0)        # Sonntag ab hier
CATCH_UP_UNTIL = dt.time(12, 0)   # Montag bis hier nachholen
KV_SENT = "weekly_sent_week"


@dataclass
class WeekSummary:
    monday: dt.date
    rides: int = 0
    hours: float = 0.0
    km: float = 0.0
    load: float = 0.0
    new_badges: list[str] = field(default_factory=list)
    next_target: str | None = None
    fitness_score: float | None = None
    fitness_delta: float | None = None
    highlight: str | None = None
    sleep_avg_h: float | None = None
    sleep_nights: int = 0
    next_week: str | None = None

    @property
    def sunday(self) -> dt.date:
        return self.monday + dt.timedelta(days=6)


# ---------------------------------------------------------------------------
# Wann?
# ---------------------------------------------------------------------------

def week_key(monday: dt.date) -> str:
    y, w, _ = monday.isocalendar()
    return f"{y}-W{w:02d}"


def due(now_local: dt.datetime, sent_key: str | None) -> tuple[bool, str, dt.date | None]:
    """(senden?, Begründung, Montag der gemeinten Woche) — rein, ohne DB."""
    d, t = now_local.date(), now_local.time()
    if d.weekday() == 6 and t >= SEND_FROM:
        monday = d - dt.timedelta(days=6)
    elif d.weekday() == 0 and t < CATCH_UP_UNTIL:
        monday = d - dt.timedelta(days=7)
    else:
        return False, "nicht im Zeitfenster (So ab 18 Uhr, Mo bis 12 Uhr)", None
    if sent_key == week_key(monday):
        return False, "für diese Woche schon gesendet", monday
    return True, f"Rückblick für {week_key(monday)} fällig", monday


# ---------------------------------------------------------------------------
# Was?
# ---------------------------------------------------------------------------

def summarize(rides: pd.DataFrame, sleep: pd.DataFrame | None, monday: dt.date,
              fi: Any | None = None, plan: Any | None = None) -> WeekSummary:
    """Zahlen der Woche Montag–Sonntag. Rein bis auf die übergebenen Objekte."""
    ws = WeekSummary(monday=monday)
    sunday = ws.sunday

    if not rides.empty:
        wk = rides[(rides["date"] >= monday) & (rides["date"] <= sunday)]
        ws.rides = int(len(wk))
        ws.hours = round(float(wk["moving_h"].sum()), 1)
        ws.km = round(float(wk["distance_km"].sum()), 1)
        ws.load = round(float(wk["load"].sum()), 0) if "load" in wk else 0.0

        before = float(rides[rides["date"] < monday]["distance_km"].sum())
        total = float(rides[rides["date"] <= sunday]["distance_km"].sum())
        names_before = {b.name for b in milestones.compute(before).earned}
        now = milestones.compute(total)
        ws.new_badges = [f"{b.icon} {b.name}" for b in reversed(now.earned)
                         if b.name not in names_before]
        if now.next_targets:
            nxt = now.next_targets[0]
            # Generische Nahziele heißen schon „5.215 km" — nicht „bis 5.215 km" doppeln.
            ws.next_target = (f"{nxt.icon} noch {nxt.remaining_km:.0f} km bis zum "
                              f"nächsten Ziel ({nxt.label})" if nxt.kind == "step"
                              else f"{nxt.icon} noch {nxt.remaining_km:.0f} km bis {nxt.label}")

    if sleep is not None and not sleep.empty and "asleep_h" in sleep.columns:
        d = sleep["date"].dt.date
        nights = sleep[(d >= monday) & (d <= sunday)]["asleep_h"].dropna()
        if len(nights):
            ws.sleep_nights = int(len(nights))
            ws.sleep_avg_h = round(float(nights.mean()), 1)

    if fi is not None and getattr(fi, "available", False):
        ws.fitness_score = fi.score
        hist = getattr(fi, "history", pd.DataFrame())
        if not hist.empty:
            days = pd.to_datetime(hist["day"]).dt.date
            prev = hist[days <= monday - dt.timedelta(days=1)]
            if not prev.empty:
                ws.fitness_delta = round(float(fi.score) - float(prev.iloc[-1]["score"]), 1)
        if fi.highlights:
            # Die Sätze sind fürs Dashboard formatiert; ntfy zeigt ** roh an.
            ws.highlight = str(fi.highlights[0]).replace("**", "")

    if plan is not None:
        bits = [f"Phase „{plan.phase_label}“"]
        if plan.is_deload:
            bits.append("Entlastungswoche")
        if plan.target_hours:
            bits.append(f"≈ {plan.target_hours:.1f} h".replace(".", ","))
        ws.next_week = ", ".join(bits)
    return ws


def _de(x: float, dec: int = 1) -> str:
    return f"{x:.{dec}f}".replace(".", ",")


def text(ws: WeekSummary) -> tuple[str, str]:
    """(Titel, Nachricht). Titel Latin-1-tauglich (HTTP-Header)."""
    span = f"{ws.monday:%d.%m.}–{ws.sunday:%d.%m.}"
    if ws.rides:
        title = f"Deine Woche: {ws.rides} Fahrt{'en' if ws.rides != 1 else ''} - {_de(ws.hours)} h"
    else:
        title = "Deine Woche: ruhige Woche"

    parts: list[str] = [f"Rückblick {span}"]
    if ws.rides:
        parts.append(f"🚴 {ws.rides} Fahrt{'en' if ws.rides != 1 else ''}, "
                     f"{_de(ws.hours)} h, {ws.km:.0f} km.")
        if ws.rides <= 1:
            parts.append("Eine ruhige Woche mit Bewegung — genau richtig, wenn der Alltag viel fordert.")
    else:
        parts.append("Diese Woche ohne Fahrt — völlig okay. Erholung zählt auch, und "
                     "die Form kommt schneller zurück, als es sich anfühlt.")

    for b in ws.new_badges[:3]:
        parts.append(f"🏅 Neuer Orden: {b}")
    if ws.next_target:
        parts.append(ws.next_target + ".")

    if ws.fitness_score is not None:
        line = f"📈 Fitness-Index {_de(ws.fitness_score)}"
        if ws.fitness_delta is not None and ws.fitness_delta >= 0.1:
            line += f" (+{_de(ws.fitness_delta)} zur Vorwoche)"
        elif ws.fitness_delta is not None and ws.fitness_delta <= -0.1:
            line += " — leicht gesunken, normal nach ruhigen Tagen"
        parts.append(line + ".")
    if ws.highlight:
        starts_with_emoji = not ws.highlight[:1].isalnum()
        parts.append(ws.highlight if starts_with_emoji else f"✨ {ws.highlight}")

    if ws.sleep_avg_h is not None:
        parts.append(f"😴 Ø {_de(ws.sleep_avg_h)} h Schlaf in {ws.sleep_nights} Nächten.")

    if ws.next_week:
        parts.append(f"Nächste Woche: {ws.next_week}. Wie viel davon geht, entscheidet "
                     "jeder Tag neu — die Kurz-Variante liegt immer mit in Zwift.")
    return title, "\n".join(parts)


def build_text(monday: dt.date) -> tuple[str, str]:
    """Rückblick für die Woche ab ``monday`` aus der Datenbank."""
    rides = dataprep.prep_rides()
    try:
        sleep = dataprep.prep_sleep()
    except Exception:  # noqa: BLE001
        sleep = None
    sunday = monday + dt.timedelta(days=6)
    try:
        fi = fitness.compute(sunday, persist=False)
    except Exception:  # noqa: BLE001 – eine Motivationszeile kippt keinen Rückblick
        fi = None
    try:
        plan = season.build(rides, sunday + dt.timedelta(days=1))
    except Exception:  # noqa: BLE001
        plan = None
    return text(summarize(rides, sleep, monday, fi, plan))


# ---------------------------------------------------------------------------
# Senden
# ---------------------------------------------------------------------------

def send_if_due(cfg: dict[str, Any], now: dt.datetime | None = None) -> tuple[str, str]:
    """Aufruf aus dem Sync-Workflow. Status: sent | waiting | already | no_topic | failed."""
    if not report.topic(cfg):
        return "no_topic", "kein ntfy-Thema gesetzt"
    now_local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(report.TZ)
    ok, why, monday = due(now_local, store.get_kv(KV_SENT))
    if not ok or monday is None:
        return ("already" if "schon" in why else "waiting"), why
    title, msg = build_text(monday)
    if not report.send_push(cfg, title, msg):
        return "failed", "ntfy hat nicht angenommen"
    store.set_kv(KV_SENT, week_key(monday))
    return "sent", why
