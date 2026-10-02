"""Schutzgeländer gegen Überlastung — bremst, treibt nie an.

Die Tagesempfehlung (`recommend.py`) entscheidet über Recovery, Form und
Wochenplan, *was* heute sinnvoll ist. Dieses Modul legt darüber eine Obergrenze,
die nur greift, wenn sich Belastung ungesund aufschaukelt — auch dann, wenn die
Whoop-Recovery grün ist und Spaß und Motivation „weiter!" sagen.

Drei Signale, jedes mit Herkunft:

1. **Lastsprung (Acute:Chronic Workload Ratio).** Ermüdung (7-Tage-Schnitt)
   geteilt durch Fitness (42-Tage-Schnitt), beide als exponentiell gewichtete
   Mittel — die Variante, die Williams et al. (2017, Br J Sports Med) gegenüber
   rollierenden Summen empfehlen. Gabbett (2016, Br J Sports Med) beschreibt
   0,8–1,3 als „sweet spot" und > 1,5 als Zone deutlich erhöhten
   Verletzungsrisikos. Die Daten stammen überwiegend aus Mannschafts- und
   Laufsport und sind methodisch umstritten (Impellizzeri et al. 2020) — darum
   hier nur als Bremse genutzt, nie als Prognose. Unterhalb von `ACWR_MIN_CTL`
   wird nicht gerechnet: bei sehr kleiner Basis ist jede normale Einheit ein
   „Sprung" und das Verhältnis sagt nichts.

2. **Tage am Stück.** Mindestens ein trainingsfreier Tag pro Woche ist
   Konsens in Trainingsleitlinien (u. a. ACSM-Position zu Übertraining,
   Meeusen et al. 2013, Eur J Sport Sci). Nach `STREAK_REST` Trainingstagen
   in Folge gibt es deshalb einen Ruhetag — unabhängig von der Tagesform,
   weil Anpassung in der Pause passiert, nicht im Sattel.

3. **Gehäuft schlechte Erholung.** Ein einzelner roter Whoop-Tag ist Rauschen
   (schlecht geschlafen, Alkohol, Infekt im Anflug) und wird schon in
   `recommend.py` behandelt. Mehrere rote Tage binnen einer Woche sind dagegen
   das typische Muster beginnender Überlastung (Meeusen et al. 2013:
   anhaltend erhöhter Ruhepuls / gedrückte HRV bei funktionellem
   Overreaching) — dann Ruhetag, auch wenn heute ein grüner Ausreißer dabei ist.

Rein und ohne DB — `recommend.build` reicht die Daten herein.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from . import form

# Intensitätsleiter: ein Deckel lässt alles bis einschließlich dieser Stufe zu.
LADDER = ["REST", "RECOVERY", "ENDURANCE", "TEMPO", "THRESHOLD", "VO2MAX"]

ACWR_CAUTION = 1.3       # Obergrenze des „sweet spot" (Gabbett 2016)
ACWR_STOP = 1.5          # „danger zone" (Gabbett 2016)
ACWR_MIN_CTL = 15.0      # darunter ist das Verhältnis bedeutungslos
ACWR_MIN_DAYS = 28       # so viel Historie braucht der 42-Tage-Schnitt mindestens

STREAK_DAY_LOAD = 20.0   # ab dieser Tageslast (TSS) zählt ein Tag als Trainingstag
STREAK_CAUTION = 5       # nach 5 Tagen am Stück: nichts Hartes mehr
STREAK_REST = 6          # nach 6 Tagen am Stück: Ruhetag

RED_RECOVERY = 34.0      # Whoop „rot" (wie `recommend._band`)
RED_WINDOW_DAYS = 7
RED_DAYS_STOP = 3        # 3 rote Tage binnen 7 → Ruhetag


@dataclass
class Guard:
    cap: str | None = None            # höchste erlaubte Einheit, None = kein Deckel
    level: str = "ok"                 # ok | caution | stop
    acwr: float | None = None
    streak_days: int = 0
    red_days: int = 0
    warnings: list[str] = field(default_factory=list)

    def apply(self, kind: str) -> str:
        """Begrenzt `kind` auf den Deckel — hebt nie an."""
        if self.cap is None:
            return kind
        return LADDER[min(LADDER.index(kind), LADDER.index(self.cap))]


def _de(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _tighten(g: Guard, cap: str, level: str, msg: str) -> None:
    if g.cap is None or LADDER.index(cap) < LADDER.index(g.cap):
        g.cap = cap
    if level == "stop" or g.level == "ok":
        g.level = level
    g.warnings.append(msg)


def acwr(rides: pd.DataFrame, today: dt.date) -> tuple[float | None, float | None]:
    """(ACWR, CTL) zum Ende von gestern — die heutige Einheit steht ja noch aus."""
    if rides.empty or "load" not in rides.columns:
        return None, None
    past = rides[rides["date"] < today][["start", "load"]]
    if past.empty:
        return None, None
    yesterday = pd.Timestamp(today - dt.timedelta(days=1))
    if getattr(past["start"].dt, "tz", None) is not None:
        yesterday = yesterday.tz_localize(past["start"].dt.tz)
    # Nullzeile, damit die Kurve über Pausentage bis gestern weiter abklingt.
    past = pd.concat([past, pd.DataFrame({"start": [yesterday], "load": [0.0]})])
    fdf = form.compute(past)
    if len(fdf) < ACWR_MIN_DAYS:
        return None, None
    last = fdf.iloc[-1]
    ctl, atl = float(last["ctl"]), float(last["atl"])
    if ctl < ACWR_MIN_CTL:
        return None, ctl
    return atl / ctl, ctl


def streak(rides: pd.DataFrame, today: dt.date) -> int:
    """Trainingstage in Folge, die gestern enden."""
    if rides.empty or "load" not in rides.columns:
        return 0
    daily = rides.groupby("date")["load"].sum()
    n, day = 0, today - dt.timedelta(days=1)
    while daily.get(day, 0.0) >= STREAK_DAY_LOAD:
        n += 1
        day -= dt.timedelta(days=1)
    return n


def red_days(rec: pd.DataFrame, today: dt.date) -> int:
    if rec.empty:
        return 0
    since = today - dt.timedelta(days=RED_WINDOW_DAYS - 1)
    d = rec["date"].dt.date
    win = rec[(d >= since) & (d <= today)]
    return int((win["recovery_score"] < RED_RECOVERY).sum())


def check(rides: pd.DataFrame, rec: pd.DataFrame, today: dt.date) -> Guard:
    g = Guard()

    ratio, _ = acwr(rides, today)
    g.acwr = round(ratio, 2) if ratio is not None else None
    if ratio is not None and ratio > ACWR_STOP:
        _tighten(g, "RECOVERY", "stop",
                 f"Lastsprung: Ermüdung liegt beim {_de(ratio)}-Fachen deiner Fitness "
                 f"(> {_de(ACWR_STOP)}). So schnelle Steigerungen gehen mit deutlich "
                 "mehr Verletzungen einher — heute nur locker (Z1).")
    elif ratio is not None and ratio > ACWR_CAUTION:
        _tighten(g, "ENDURANCE", "caution",
                 f"Last steigt zügig (Ermüdung {_de(ratio)}× Fitness, gesund bis "
                 f"{_de(ACWR_CAUTION)}) — heute nichts Hartes.")

    g.streak_days = streak(rides, today)
    if g.streak_days >= STREAK_REST:
        _tighten(g, "REST", "stop",
                 f"{g.streak_days} Trainingstage am Stück — heute Ruhetag. "
                 "Stärker wirst du in der Pause, nicht im Sattel.")
    elif g.streak_days >= STREAK_CAUTION:
        _tighten(g, "ENDURANCE", "caution",
                 f"{g.streak_days} Trainingstage am Stück — morgen spätestens "
                 "Ruhetag einplanen, heute nichts Hartes.")

    g.red_days = red_days(rec, today)
    if g.red_days >= RED_DAYS_STOP:
        _tighten(g, "REST", "stop",
                 f"{g.red_days} rote Recovery-Tage in den letzten {RED_WINDOW_DAYS} "
                 "Tagen — das Muster deutet auf Überlastung oder einen Infekt. "
                 "Heute Ruhetag, auch wenn es sich gut anfühlt.")
    return g
