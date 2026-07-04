"""Form-Modell (Banister): Fitness (CTL), Ermüdung (ATL), Form (TSB).

- CTL (Chronic Training Load): exponentiell gewichteter Schnitt der Tageslast
  über ~42 Tage → deine "Fitness".
- ATL (Acute Training Load): dasselbe über ~7 Tage → deine "Ermüdung".
- TSB (Training Stress Balance): CTL(gestern) − ATL(gestern) → deine "Form".

Als Tageslast nutzen wir denselben `load`-Wert wie im Trainingsbelastungs-Tab
(Stravas Relative Effort bzw. eine Schätzung aus Dauer & HF).
"""

from __future__ import annotations

import math

import pandas as pd

CTL_TAU = 42
ATL_TAU = 7


def compute(rides: pd.DataFrame) -> pd.DataFrame:
    """Erwartet ein DataFrame mit Spalten 'start' (datetime) und 'load'."""
    if rides.empty:
        return pd.DataFrame(columns=["date", "ctl", "atl", "tsb"])

    daily = rides.set_index("start")["load"].resample("D").sum().fillna(0.0)
    idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(idx, fill_value=0.0)

    ac = 1 - math.exp(-1 / CTL_TAU)
    aa = 1 - math.exp(-1 / ATL_TAU)
    ctl_vals, atl_vals, tsb_vals = [], [], []
    c = a = 0.0
    for load in daily.to_numpy():
        # TSB basiert auf den Werten von gestern (vor der heutigen Last).
        tsb_vals.append(c - a)
        c = c + ac * (load - c)
        a = a + aa * (load - a)
        ctl_vals.append(c)
        atl_vals.append(a)

    return pd.DataFrame({
        "date": daily.index,
        "ctl": ctl_vals,
        "atl": atl_vals,
        "tsb": tsb_vals,
    })


def interpret(tsb: float) -> tuple[str, str]:
    """Gibt (Status, Hinweis) zur aktuellen Form zurück."""
    if tsb > 15:
        return ("Sehr frisch", "Top erholt — ideal für ein Rennen/harte Tage. "
                "Hält das zu lange an, verlierst du Fitness.")
    if tsb > 5:
        return ("Frisch", "Gute Spritzigkeit bei erhaltener Fitness.")
    if tsb >= -10:
        return ("Ausgeglichen", "Gesunde Balance aus Belastung und Erholung.")
    if tsb >= -30:
        return ("Ermüdet (Aufbau)", "Du baust gerade Fitness auf — normal in harten Phasen.")
    return ("Stark überlastet", "Hohe Ermüdung — Erholung einplanen, Verletzungs-/Übertrainingsrisiko.")
