"""Aufbereitung der Rohtabellen zu auswertbaren DataFrames.

Wird sowohl vom Dashboard als auch von der Empfehlungs-Engine genutzt,
damit beide identisch rechnen.
"""

from __future__ import annotations

import pandas as pd

from . import load as load_mod
from . import store, zones


def prep_rides() -> pd.DataFrame:
    df = store.read_table("strava_activities")
    if df.empty:
        return df
    # Strava hängt auch an die LOKALE Startzeit ein "Z" an, als wäre es UTC.
    # Wir entfernen es und behandeln alles als tz-naive Ortszeit, damit es
    # konsistent mit den (tz-naiven) Whoop-Daten zusammengeführt werden kann.
    local = (
        df["start_date_local"].fillna(df["start_date"]).astype(str).str.replace(
            "Z", "", regex=False
        )
    )
    df["start"] = pd.to_datetime(local, errors="coerce")
    df = df.dropna(subset=["start"]).sort_values("start").reset_index(drop=True)
    df["date"] = df["start"].dt.date
    df["distance_km"] = df["distance_m"] / 1000
    df["moving_h"] = df["moving_time_s"] / 3600
    df["avg_speed_kmh"] = df["average_speed_ms"] * 3.6
    df["elev_m"] = df["total_elevation_gain_m"]

    # Tageslast als transparentes Banister-TRIMP (HF-basiert). Fällt HF/Ruhepuls
    # weg, greift Stravas Relative Effort, zuletzt eine grobe Dauer×HF-Schätzung.
    max_hr = zones.max_hr_from_data()
    rest_hr = zones.resting_hr_baseline()
    hr_factor = (df["average_heartrate"].fillna(120) / 120).clip(0.6, 2.0)
    estimate = df["moving_h"] * 50 * hr_factor

    def _row_load(row) -> float:
        trimp = load_mod.banister_trimp(
            row["moving_time_s"], row["average_heartrate"], max_hr, rest_hr
        )
        if trimp is not None:
            return trimp
        if pd.notna(row["suffer_score"]):
            return float(row["suffer_score"])
        return float(estimate.loc[row.name])

    df["load"] = df.apply(_row_load, axis=1)
    return df


def prep_recovery() -> pd.DataFrame:
    df = store.read_table("whoop_recovery")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def prep_cycles() -> pd.DataFrame:
    df = store.read_table("whoop_cycles")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["start"], errors="coerce", utc=True).dt.tz_localize(None)
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
