"""Wetter für den Startort über Open-Meteo (kostenlos, ohne API-Key).

Liefert aktuelle Werte + Tagesausblick (Temperatur, Niederschlag, UV, Wind)
und daraus abgeleitete, fahrtbezogene Hinweise.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import requests

from . import config

API_URL = "https://api.open-meteo.com/v1/forecast"

# WMO-Wettercodes → (Emoji, Beschreibung)
WMO = {
    0: ("☀️", "klar"), 1: ("🌤️", "überwiegend klar"), 2: ("⛅", "teils bewölkt"),
    3: ("☁️", "bedeckt"), 45: ("🌫️", "Nebel"), 48: ("🌫️", "Reifnebel"),
    51: ("🌦️", "leichter Niesel"), 53: ("🌦️", "Niesel"), 55: ("🌧️", "starker Niesel"),
    61: ("🌦️", "leichter Regen"), 63: ("🌧️", "Regen"), 65: ("🌧️", "starker Regen"),
    66: ("🌧️", "gefrierender Regen"), 67: ("🌧️", "gefrierender Regen"),
    71: ("🌨️", "leichter Schnee"), 73: ("🌨️", "Schnee"), 75: ("❄️", "starker Schnee"),
    77: ("🌨️", "Schneegriesel"), 80: ("🌦️", "Regenschauer"), 81: ("🌧️", "Schauer"),
    82: ("⛈️", "heftige Schauer"), 85: ("🌨️", "Schneeschauer"), 86: ("❄️", "Schneeschauer"),
    95: ("⛈️", "Gewitter"), 96: ("⛈️", "Gewitter mit Hagel"), 99: ("⛈️", "schweres Gewitter"),
}

COMPASS = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]


def wind_dir_label(deg: float) -> str:
    return COMPASS[int((deg % 360) / 45 + 0.5) % 8]


@dataclass
class Weather:
    temp_c: float
    feels_c: float
    precip_mm: float
    precip_prob: int
    uv: float
    wind_kmh: float
    gust_kmh: float
    wind_deg: float
    code: int
    t_max: float
    t_min: float

    @property
    def icon(self) -> str:
        return WMO.get(self.code, ("🌡️", "?"))[0]

    @property
    def desc(self) -> str:
        return WMO.get(self.code, ("", "unbekannt"))[1]

    @property
    def wind_dir(self) -> str:
        return wind_dir_label(self.wind_deg)


@dataclass
class Hour:
    """Eine Stunde aus dem Vorhersage-Raster (Ortszeit)."""

    time: dt.datetime
    temp_c: float
    feels_c: float
    precip_mm: float
    precip_prob: int
    code: int
    wind_kmh: float
    gust_kmh: float
    wind_deg: float
    uv: float
    is_day: bool

    @property
    def icon(self) -> str:
        return WMO.get(self.code, ("\U0001f321\ufe0f", "?"))[0]

    @property
    def desc(self) -> str:
        return WMO.get(self.code, ("", "unbekannt"))[1]

    @property
    def wind_dir(self) -> str:
        return wind_dir_label(self.wind_deg)


def _home(cfg: dict) -> tuple[float, float] | None:
    """Heimat-Koordinate aus der Einrichtung — None, wenn nicht gesetzt."""
    ath = config.athlete(cfg)
    lat = float(ath.get("home_lat", 0) or 0)
    lon = float(ath.get("home_lon", 0) or 0)
    if lat == 0 and lon == 0:
        return None
    return lat, lon


def hourly_forecast(cfg: dict, days: int = 2) -> list[Hour]:
    """Stundenraster fuer die naechsten Tage (fuer die Tageszeit-Empfehlung).

    Leere Liste bei fehlender Koordinate oder API-Problem — der Aufrufer faellt
    dann still auf "keine Empfehlung" zurueck.
    """
    home = _home(cfg)
    if home is None:
        return []
    lat, lon = home
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": (
            "temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
            "weather_code,wind_speed_10m,wind_gusts_10m,wind_direction_10m,uv_index,is_day"
        ),
        "wind_speed_unit": "kmh",
        "timezone": "auto",
        "forecast_days": max(1, min(int(days), 7)),
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=20)
        resp.raise_for_status()
        d = resp.json()
    except (requests.RequestException, ValueError):
        return []

    h = d.get("hourly") or {}
    times = h.get("time") or []

    def col(name: str) -> list:
        vals = h.get(name) or []
        return list(vals) + [None] * (len(times) - len(vals))

    temps, feels = col("temperature_2m"), col("apparent_temperature")
    prec, prob = col("precipitation"), col("precipitation_probability")
    codes = col("weather_code")
    wind, gust, wdeg = col("wind_speed_10m"), col("wind_gusts_10m"), col("wind_direction_10m")
    uv, isday = col("uv_index"), col("is_day")

    out: list[Hour] = []
    for i, ts in enumerate(times):
        try:
            when = dt.datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            continue
        out.append(Hour(
            time=when,
            temp_c=float(temps[i] or 0.0),
            feels_c=float(feels[i] if feels[i] is not None else (temps[i] or 0.0)),
            precip_mm=float(prec[i] or 0.0),
            precip_prob=int(prob[i] or 0),
            code=int(codes[i] or 0),
            wind_kmh=float(wind[i] or 0.0),
            gust_kmh=float(gust[i] or 0.0),
            wind_deg=float(wdeg[i] or 0.0),
            uv=float(uv[i] or 0.0),
            is_day=bool(isday[i]) if isday[i] is not None else True,
        ))
    return out


def current(cfg: dict) -> Weather | None:
    ath = config.athlete(cfg)
    lat = float(ath.get("home_lat", 0) or 0)
    lon = float(ath.get("home_lon", 0) or 0)
    if lat == 0 and lon == 0:
        return None
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": (
            "temperature_2m,apparent_temperature,precipitation,uv_index,"
            "wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code"
        ),
        "hourly": "precipitation_probability",
        "daily": "temperature_2m_max,temperature_2m_min",
        "wind_speed_unit": "kmh",
        "timezone": "auto",
        "forecast_days": 1,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=20)
        resp.raise_for_status()
        d = resp.json()
    except (requests.RequestException, ValueError):
        return None

    cur = d.get("current", {})
    daily = d.get("daily", {})
    hourly = d.get("hourly", {})
    probs = hourly.get("precipitation_probability") or [0]
    return Weather(
        temp_c=cur.get("temperature_2m", 0.0),
        feels_c=cur.get("apparent_temperature", cur.get("temperature_2m", 0.0)),
        precip_mm=cur.get("precipitation", 0.0),
        precip_prob=int(max(probs[:12] or [0])),
        uv=cur.get("uv_index", 0.0) or 0.0,
        wind_kmh=cur.get("wind_speed_10m", 0.0),
        gust_kmh=cur.get("wind_gusts_10m", 0.0),
        wind_deg=cur.get("wind_direction_10m", 0.0),
        code=int(cur.get("weather_code", 0)),
        t_max=(daily.get("temperature_2m_max") or [0])[0],
        t_min=(daily.get("temperature_2m_min") or [0])[0],
    )


def advice(w: Weather) -> list[str]:
    """Fahrtbezogene Hinweise aus den Wetterwerten."""
    tips: list[str] = []

    # Niederschlag
    if w.precip_mm >= 0.3 or w.code in {65, 67, 82, 95, 96, 99}:
        tips.append("🌧️ Es regnet/Gewitter — Schutzbleche & Regenjacke, oder lieber auf die Rolle.")
    elif w.precip_prob >= 50:
        tips.append(f"☔ {w.precip_prob} % Regenwahrscheinlichkeit — Regenjacke einpacken.")

    # Temperatur
    if w.temp_c <= 3:
        tips.append("🥶 Sehr kalt — warme Schichten, Handschuhe & Buff; Reifen mit weniger Druck.")
    elif w.temp_c <= 10:
        tips.append("🧥 Kühl — lange Kleidung und Windweste empfehlenswert.")
    elif w.temp_c >= 28:
        tips.append("🥵 Heiß — extra Flasche mitnehmen, früh/spät fahren, Intensität ggf. drosseln.")

    # UV
    if w.uv >= 6:
        tips.append(f"🧴 Hoher UV-Index ({w.uv:.0f}) — Sonnencreme & Brille nicht vergessen.")

    # Wind
    if w.wind_kmh >= 30 or w.gust_kmh >= 45:
        tips.append(
            f"💨 Kräftiger Wind ({w.wind_kmh:.0f} km/h aus {w.wind_dir}, Böen {w.gust_kmh:.0f}). "
            "Tipp: zuerst gegen den Wind raus, mit Rückenwind zurück."
        )
    elif w.wind_kmh >= 18:
        tips.append(
            f"🍃 Mäßiger Wind ({w.wind_kmh:.0f} km/h aus {w.wind_dir}) — "
            "Hinweg gegen den Wind einplanen."
        )

    if not tips:
        tips.append("👍 Gute Bedingungen — nichts Besonderes zu beachten.")
    return tips
