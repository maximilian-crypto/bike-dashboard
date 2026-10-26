"""Pulsverteilung je Fahrt — wie lange lag der Puls wo?

Der Durchschnittspuls einer Fahrt verwässert alles, was nicht gleichmäßig
gefahren wurde: eine Stunde Z2 plus eine Stunde Z4 ergibt im Schnitt Z3, und
die Fahrt galt in der Tagesempfehlung nicht als hart — am nächsten Morgen
standen 4×4-Intervalle im Plan (Befund 26.10.2026). Deshalb holt der Sync für
jede neue Fahrt einmal den Pulsverlauf von Strava.

Gespeichert wird bewusst **kein** Rohverlauf, sondern ein Histogramm
(Sekunden je bpm, ein paar Dutzend Zahlen pro Fahrt). Daraus lassen sich die
Zonenminuten jederzeit mit den *aktuellen* Zonen neu rechnen — ändert sich
LTHR oder Max-HF, stimmt die Auswertung alter Fahrten trotzdem.

Derselbe Abruf füttert nebenbei die Ermüdungsresistenz des Fitness-Index, die
sonst nur per Knopf im Dashboard nachgeladen wird.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd

from . import dataprep, fitness, store, strava

# Ab so vielen Minuten Puls in Z4 oder darüber zählt eine Fahrt als hart.
# Eine 4×4-Einheit bringt wegen der Pulsverzögerung (1–2 min bis zum Ziel)
# etwa 12–14 Minuten dort hin; einzelne Anstiege einer Grundlagenfahrt
# bleiben meist deutlich darunter.
HARD_MINUTES_Z4 = 12.0

# Nur die jüngsten Fahrten im Sync — für die Entscheidung über heute zählen
# die letzten Tage, nicht die ganze Historie (Stravas Kontingent schonen).
SYNC_DAYS = 14
SYNC_LIMIT = 10

# Längere Lücken im Zeitstrom sind Pausen (Ampel, Café): nicht als Zeit am
# letzten Puls zählen.
MAX_STEP_S = 10


def hr_histogram(time_s: list, hr: list) -> dict[int, float]:
    """Sekunden je ganzzahligem bpm aus den Strava-Streams ``time``/``heartrate``."""
    hist: dict[int, float] = {}
    n = min(len(time_s or []), len(hr or []))
    for i in range(1, n):
        step = time_s[i] - time_s[i - 1]
        bpm = hr[i]
        if not bpm or step <= 0 or step > MAX_STEP_S:
            continue
        key = int(round(bpm))
        hist[key] = hist.get(key, 0.0) + float(step)
    return hist


def minutes_at_or_above(hist: dict[int, float], bpm: int) -> float:
    return sum(s for b, s in hist.items() if b >= bpm) / 60.0


def histograms() -> dict[int, dict[int, float]]:
    """Alle gespeicherten Histogramme je Fahrt-ID. Leer = Fahrt ohne Puls."""
    df = store.read_table("ride_hr_hist")
    out: dict[int, dict[int, float]] = {}
    for _, r in df.iterrows():
        try:
            raw = json.loads(r["hist"] or "{}")
        except (TypeError, ValueError):
            continue
        out[int(r["ride_id"])] = {int(k): float(v) for k, v in raw.items()}
    return out


def minutes_above_map(bpm: int) -> dict[int, float]:
    """Minuten ≥ ``bpm`` je Fahrt — nur Fahrten mit Pulsverlauf."""
    return {rid: minutes_at_or_above(h, bpm) for rid, h in histograms().items() if h}


def sync_recent(cfg: dict[str, Any], today: dt.date | None = None,
                days: int = SYNC_DAYS, limit: int = SYNC_LIMIT) -> dict:
    """Holt die Streams neuer Fahrten und legt Histogramm (+ Fitness-Kennzahlen) ab.

    Jede Fahrt wird genau einmal abgefragt: auch ohne Puls entsteht eine
    (leere) Zeile, damit der nächste Sync sie nicht erneut anfragt.
    """
    today = today or dt.date.today()
    rides = dataprep.prep_rides()
    if rides.empty:
        return {"processed": 0, "with_hr": 0}
    done = set(histograms())
    recent = rides[(rides["date"] >= today - dt.timedelta(days=days))
                   & ~rides["id"].isin(done)].sort_values("start", ascending=False)
    fit_done = fitness._attempted_ids()

    rows: list[dict] = []
    metrics: list[dict] = []
    fit_tried: set[int] = set()
    for _, r in recent.head(limit).iterrows():
        rid = int(r["id"])
        try:
            streams = strava.fetch_streams(cfg, rid)
        except RuntimeError:
            break   # Rate-Limit: beim nächsten Sync weiter
        time_s = (streams.get("time") or {}).get("data") or []
        hr = (streams.get("heartrate") or {}).get("data") or []
        rows.append({
            "ride_id": rid,
            "ride_day": pd.Timestamp(r["start"]).normalize().date().isoformat(),
            "hist": json.dumps(hr_histogram(time_s, hr)),
            "computed_at": dt.datetime.now().isoformat(timespec="seconds"),
        })
        if rid not in fit_done and r["moving_time_s"] >= fitness.MIN_MINUTES * 60:
            fit_tried.add(rid)
            m = fitness.metrics_from_streams(streams, rid, r["start"])
            if m:
                metrics.append(m)
    store.upsert_ride_hr_hist(rows)
    if metrics:
        store.upsert_ride_metrics(metrics)
    if fit_tried:
        fitness._mark_attempted(fit_tried)
    return {"processed": len(rows),
            "with_hr": sum(1 for x in rows if x["hist"] != "{}")}
