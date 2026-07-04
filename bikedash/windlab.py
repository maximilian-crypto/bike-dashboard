"""Wind-Labor (Beta): Einfluss von Gegen-/Seitenwind auf deine Geschwindigkeit.

Pipeline je Fahrt:
  1. GPS-/Tempo-Streams von Strava holen und ausdünnen.
  2. Historische Winddaten (Open-Meteo-Archiv) für Tag & Ort der Fahrt.
  3. Pro Abschnitt Fahrtrichtung (Bearing) gegen die Windrichtung rechnen
     → Gegenwind-/Seitenwind-Komponente.
  4. Auf flachem Terrain Geschwindigkeit vs. Gegenwind auswerten (lineare
     Regression) → dein persönlicher "Gegenwind-Malus".

Hinweis: Heuristik. Ohne Wattmessung sind Effort-Schwankungen ein Störfaktor;
die Aussagekraft wächst mit mehr Fahrten ("successive genauer").
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import dataprep, store, strava

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_wind_cache: dict[tuple, dict[int, tuple[float, float]]] = {}


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def historical_wind(lat: float, lon: float, date: dt.date) -> dict[int, tuple[float, float]]:
    """Stündlicher Wind (km/h, Herkunftsrichtung °) für Tag & Ort. Gecacht."""
    import requests

    key = (round(lat, 2), round(lon, 2), date.isoformat())
    if key in _wind_cache:
        return _wind_cache[key]
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date.isoformat(),
        "end_date": date.isoformat(),
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "kmh",
        "timezone": "auto",
    }
    out: dict[int, tuple[float, float]] = {}
    try:
        resp = requests.get(ARCHIVE_URL, params=params, timeout=25)
        resp.raise_for_status()
        h = resp.json().get("hourly", {})
        times = h.get("time", [])
        spd = h.get("wind_speed_10m", [])
        deg = h.get("wind_direction_10m", [])
        for t, s, dg in zip(times, spd, deg):
            hour = int(t[11:13])  # "YYYY-MM-DDTHH:MM"
            out[hour] = (float(s or 0), float(dg or 0))
    except (requests.RequestException, ValueError, KeyError):
        pass
    _wind_cache[key] = out
    return out


def _downsample(n: int, target: int) -> list[int]:
    if n <= target:
        return list(range(n))
    step = n / target
    return [int(i * step) for i in range(target)]


def process_ride(cfg: dict, ride_id: int, start: dt.datetime, max_points: int = 120) -> int:
    """Verarbeitet eine Fahrt → Wind-Abschnitte in der DB. Gibt Anzahl zurück."""
    streams = strava.fetch_streams(cfg, ride_id)
    latlng = (streams.get("latlng") or {}).get("data")
    vel = (streams.get("velocity_smooth") or {}).get("data")
    tim = (streams.get("time") or {}).get("data")
    grade = (streams.get("grade_smooth") or {}).get("data")
    if not latlng or not vel or not tim:
        store.replace_wind_segments(ride_id, [])
        return 0

    idxs = _downsample(len(latlng), max_points)
    centroid_lat = sum(p[0] for p in latlng) / len(latlng)
    centroid_lon = sum(p[1] for p in latlng) / len(latlng)
    wind_by_hour = historical_wind(centroid_lat, centroid_lon, start.date())

    rows = []
    for k in range(len(idxs) - 1):
        i, j = idxs[k], idxs[k + 1]
        lat1, lon1 = latlng[i]
        lat2, lon2 = latlng[j]
        speed_kmh = (vel[i] or 0) * 3.6
        if speed_kmh < 8:  # stehende/rollende Punkte raus
            continue
        heading = _bearing(lat1, lon1, lat2, lon2)
        hour = (start + dt.timedelta(seconds=tim[i])).hour
        wspd, wdeg = wind_by_hour.get(hour, (0.0, 0.0))
        rel = math.radians(heading - wdeg)
        headwind = wspd * math.cos(rel)
        crosswind = abs(wspd * math.sin(rel))
        rows.append({
            "ride_id": ride_id,
            "t_idx": i,
            "lat": lat1,
            "lon": lon1,
            "speed_kmh": round(speed_kmh, 2),
            "grade": round(grade[i], 2) if grade and i < len(grade) and grade[i] is not None else None,
            "heading": round(heading, 1),
            "wind_kmh": round(wspd, 1),
            "wind_from_deg": round(wdeg, 1),
            "headwind_kmh": round(headwind, 2),
            "crosswind_kmh": round(crosswind, 2),
        })
    store.replace_wind_segments(ride_id, rows)
    return len(rows)


def _attempted_ids() -> set[int]:
    raw = store.get_state("wind_attempted")
    return set(json.loads(raw)) if raw else set()


def _mark_attempted(ids: set[int]) -> None:
    store.set_state("wind_attempted", json.dumps(sorted(_attempted_ids() | ids)))


def run_analysis(cfg: dict, limit: int = 15, force: bool = False, progress_cb=None) -> dict:
    """Verarbeitet (noch nicht versuchte) Fahrten. Gibt Zusammenfassung zurück."""
    rides = dataprep.prep_rides()
    if rides.empty:
        return {"processed": 0, "segments": 0, "rides": 0}
    # "versucht" statt nur "hat Segmente": so werden Indoor-Fahrten ohne GPS
    # nicht bei jedem Lauf erneut abgefragt.
    done = set() if force else _attempted_ids()
    todo = rides[~rides["id"].isin(done)].sort_values("start", ascending=False).head(limit)

    total_seg = 0
    n = 0
    attempted: set[int] = set()
    for pos, (_, row) in enumerate(todo.iterrows()):
        if progress_cb:
            progress_cb(pos, len(todo), row.get("name", ""))
        start = row["start"].to_pydatetime()
        rid = int(row["id"])
        try:
            total_seg += process_ride(cfg, rid, start)
            attempted.add(rid)
            n += 1
        except RuntimeError:
            break  # Rate-Limit o. Ä. – bisher Verarbeitetes bleibt erhalten
    if attempted:
        _mark_attempted(attempted)
    return {"processed": n, "segments": total_seg, "rides": len(todo)}


@dataclass
class WindFit:
    slope: float          # km/h Geschwindigkeitsänderung je km/h Gegenwind
    intercept: float
    n: int
    df: pd.DataFrame


def analyze(flat_thresh: float = 1.5) -> WindFit | None:
    """Lineare Beziehung Geschwindigkeit ~ Gegenwind auf flachem Terrain."""
    df = store.read_table("wind_segments")
    if df.empty:
        return None
    flat = df[df["grade"].abs() <= flat_thresh].dropna(subset=["speed_kmh", "headwind_kmh"])
    if len(flat) < 20:
        return None
    x = flat["headwind_kmh"].to_numpy()
    y = flat["speed_kmh"].to_numpy()
    slope, intercept = np.polyfit(x, y, 1)
    return WindFit(slope=float(slope), intercept=float(intercept), n=len(flat), df=flat)
