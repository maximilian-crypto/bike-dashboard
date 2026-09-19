"""Aufbereitung der Rohtabellen zu auswertbaren DataFrames.

Wird sowohl vom Dashboard als auch von der Empfehlungs-Engine genutzt,
damit beide identisch rechnen.
"""

from __future__ import annotations

import json

import pandas as pd

from . import config
from . import load as load_mod
from . import store, zones

# Strava-Typen, die eine Indoor-/Rollen-Einheit kennzeichnen. Zwift meldet seine
# Fahrten grundsätzlich als ``VirtualRide``.
INDOOR_TYPES = {"VirtualRide"}


def is_indoor(type_: str | None, sport_type: str | None,
              raw_json: str | None = None) -> bool:
    """Ist die Aktivität eine Indoor-/Rollenfahrt?

    Primär über den Strava-Typ (Zwift & Co. melden ``VirtualRide``). Zusätzlich
    greift Stravas ``trainer``-Flag aus dem Rohdatensatz — das deckt Rollen-
    Einheiten ab, die ein Head-Unit ganz normal als ``Ride`` aufzeichnet.
    """
    if (sport_type or "") in INDOOR_TYPES or (type_ or "") in INDOOR_TYPES:
        return True
    if raw_json:
        try:
            return bool(json.loads(raw_json).get("trainer"))
        except (ValueError, TypeError):
            return False
    return False


def has_power_meter(raw_json: str | None) -> bool:
    """Echte Wattdaten? Stravas ``device_watts`` unterscheidet Powermeter
    (bzw. Smart-Trainer) von Stravas Schätzung aus Tempo und Höhenprofil.

    Modulweit, weil ausser der Lastberechnung auch der Fitness-Index wissen
    muss, ob die Wattzahlen einer Fahrt gemessen oder geraten sind.
    """
    if not raw_json:
        return False
    try:
        return bool(json.loads(raw_json).get("device_watts"))
    except (ValueError, TypeError):
        return False


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

    # Indoor/Outdoor trennen: Rollen-Kilometer sind für Verschleiß, Tempo- und
    # Windauswertung etwas grundsätzlich anderes als Kilometer auf der Straße.
    def _col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name]
        return pd.Series([None] * len(df), index=df.index)

    df["is_indoor"] = [
        is_indoor(t, s, r)
        for t, s, r in zip(_col("type"), _col("sport_type"), _col("raw_json"))
    ]
    df["distance_km_outdoor"] = df["distance_km"].where(~df["is_indoor"], 0.0)
    df["distance_km_indoor"] = df["distance_km"].where(df["is_indoor"], 0.0)

    # Trainingslast auf einheitlicher TSS-Skala (1 h an der Schwelle = 100).
    # Reihenfolge nach Verlässlichkeit: echte Wattdaten → Herzfrequenz →
    # Stravas Relative Effort → grobe Dauer×HF-Schätzung.
    max_hr = zones.max_hr_from_data()
    rest_hr = zones.resting_hr_baseline()
    lthr = zones.lthr_from_config()
    ftp = config.ftp_from_config()
    hr_factor = (df["average_heartrate"].fillna(120) / 120).clip(0.6, 2.0)
    estimate = df["moving_h"] * 50 * hr_factor

    def _row_load(row) -> tuple[float, str]:
        if has_power_meter(row.get("raw_json")):
            tss = load_mod.power_tss(
                row["moving_time_s"], row.get("weighted_average_watts"), ftp
            )
            if tss is not None:
                return tss, "power"
        tss = load_mod.hr_tss(
            row["moving_time_s"], row["average_heartrate"], max_hr, rest_hr, lthr
        )
        if tss is not None:
            return tss, "hr"
        if pd.notna(row["suffer_score"]):
            return float(row["suffer_score"]), "suffer_score"
        return float(estimate.loc[row.name]), "estimate"

    computed = [_row_load(row) for _, row in df.iterrows()]
    df["load"] = [c[0] for c in computed]
    df["load_source"] = [c[1] for c in computed]
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
