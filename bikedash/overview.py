"""Die drei Kopf-Kacheln der Startseite: Erholung heute, diese Woche, Fortschritt.

Bewusst nur das, was der Nutzer morgens über sich wissen will (Nutzerentscheid
Okt. 2026) — keine Summen über den ganzen Zeitraum, die stehen im Tab
„Leistung & Fortschritt". Jede Zahl kommt mit ihrem Bezug: HRV und Ruhepuls
gegen den eigenen 30-Tage-Normalwert, Schlaf gegen Whoops Bedarf, die Woche
neben der Vorwoche. Kein Soll-Rot: die Woche wird gezeigt, nicht bewertet.

Rein, ohne Datenbank — das Dashboard reicht die Tabellen herein.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from . import form

BASE_DAYS = 30      # Normalwert = Median der letzten 30 Tage (ohne heute)
MIN_BASE = 7        # darunter gibt es keinen Normalwert


@dataclass
class RecoveryToday:
    score: float | None = None
    hrv: float | None = None
    hrv_delta: float | None = None       # ms gegen den 30-Tage-Median
    rhr: float | None = None
    rhr_delta: float | None = None       # bpm gegen den 30-Tage-Median
    sleep_h: float | None = None
    sleep_need_h: float | None = None
    is_today: bool = False               # False = letzter Wert ist älter als heute

    @property
    def available(self) -> bool:
        return self.score is not None or self.sleep_h is not None


@dataclass
class Week:
    rides: int = 0
    hours: float = 0.0
    km: float = 0.0
    prev_hours: float = 0.0              # Vorwoche bis zum selben Wochentag
    days_left: int = 0                   # Tage bis Sonntag (heute nicht mitgezählt)


@dataclass
class Progress:
    fitness: float | None = None
    fitness_delta_30: float | None = None
    tier: str | None = None
    tsb: float | None = None
    form_label: str | None = None


def _delta(series: pd.Series, dates: pd.Series, day: dt.date) -> float | None:
    base = series[(dates < day) & (dates >= day - dt.timedelta(days=BASE_DAYS))].dropna()
    return float(base.median()) if len(base) >= MIN_BASE else None


def recovery_today(rec: pd.DataFrame, sleep: pd.DataFrame | None,
                   today: dt.date) -> RecoveryToday:
    out = RecoveryToday()
    if rec is not None and not rec.empty:
        d = rec["date"].dt.date
        upto = rec[d <= today]
        if not upto.empty:
            last = upto.iloc[-1]
            day = last["date"].date()
            out.is_today = (today - day).days <= 1
            if pd.notna(last.get("recovery_score")):
                out.score = float(last["recovery_score"])
            for col, attr in (("hrv_rmssd_milli", "hrv"), ("resting_heart_rate", "rhr")):
                if col in rec.columns and pd.notna(last.get(col)):
                    val = float(last[col])
                    setattr(out, attr, round(val, 1))
                    med = _delta(rec[col], d, day)
                    if med is not None:
                        setattr(out, f"{attr}_delta", round(val - med, 1))
    if sleep is not None and not sleep.empty and "asleep_h" in sleep.columns:
        sd = sleep["date"].dt.date
        night = sleep[(sd <= today) & (sd >= today - dt.timedelta(days=1))]
        if not night.empty:
            row = night.iloc[-1]
            if pd.notna(row["asleep_h"]):
                out.sleep_h = round(float(row["asleep_h"]), 1)
            if "need_h" in sleep.columns and pd.notna(row.get("need_h")):
                out.sleep_need_h = round(float(row["need_h"]), 1)
    return out


def this_week(rides: pd.DataFrame, today: dt.date) -> Week:
    monday = today - dt.timedelta(days=today.weekday())
    w = Week(days_left=6 - today.weekday())
    if rides is None or rides.empty:
        return w
    cur = rides[(rides["date"] >= monday) & (rides["date"] <= today)]
    w.rides = int(len(cur))
    w.hours = round(float(cur["moving_h"].sum()), 1)
    w.km = round(float(cur["distance_km"].sum()), 1)
    prev_mon = monday - dt.timedelta(days=7)
    prev = rides[(rides["date"] >= prev_mon) & (rides["date"] <= today - dt.timedelta(days=7))]
    w.prev_hours = round(float(prev["moving_h"].sum()), 1)
    return w


def progress(fi: object | None, tsb: float | None) -> Progress:
    p = Progress(tsb=tsb)
    if tsb is not None:
        p.form_label = form.interpret(tsb)[0]
    if fi is not None and getattr(fi, "available", False):
        p.fitness = fi.score
        p.fitness_delta_30 = fi.delta_30
        p.tier = fi.tier
    return p
