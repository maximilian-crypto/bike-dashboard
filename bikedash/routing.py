"""Rundkurs-Routen über OpenRouteService (kostenlos, mit API-Key).

generate_loop() erzeugt eine Schleife der gewünschten Distanz ab dem
Startpunkt und liefert Geometrie (für die Karte), Distanz, Höhenmeter und
ein Höhenprofil zurück.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

import requests

from . import config

ORS_URL = "https://api.openrouteservice.org/v2/directions/{profile}/geojson"


@dataclass
class Route:
    lats: list[float]
    lons: list[float]
    distance_km: float
    ascent_m: float
    profile_dist_km: list[float]   # kumulierte Distanz für das Höhenprofil
    profile_ele_m: list[float]
    seed: int
    # Optionale Abbiege-Hinweise (nur wenn mit instructions=True angefordert).
    # Jeder Eintrag: {"instruction": str, "wp0": int, "wp1": int} – die Indizes
    # zeigen in die lats/lons-Geometrie. Für die On-Bike-Navigation der PWA.
    steps: list[dict[str, Any]] = field(default_factory=list)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ORS' round_trip überschätzt die Länge oft und produziert bei manchen Seeds
# wilde Ausreißer. Wir fragen die Ziel-Länge leicht reduziert an und probieren
# mehrere Seeds, um die zum Ziel passendste Schleife zu wählen.
_LENGTH_BIAS = 0.9
_MAX_ATTEMPTS = 6
_TOLERANCE = 0.12


def _request_route(
    cfg: dict[str, Any],
    length_km: float,
    seed: int,
    points: int = 3,
    instructions: bool = False,
) -> Route:
    ors = config.ors(cfg)
    ath = config.athlete(cfg)
    profile = str(ors.get("profile", "cycling-regular"))
    lat = float(ath["home_lat"])
    lon = float(ath["home_lon"])

    body = {
        "coordinates": [[lon, lat]],
        "options": {"round_trip": {"length": int(length_km * 1000), "points": points, "seed": seed}},
        "elevation": True,
        "instructions": instructions,
        "language": "de",
    }
    resp = requests.post(
        ORS_URL.format(profile=profile),
        json=body,
        headers={"Authorization": str(ors["api_key"]), "Content-Type": "application/json"},
        timeout=40,
    )
    if resp.status_code == 401:
        raise RuntimeError("ORS-API-Key ungültig (401). Bitte in der Einrichtung prüfen.")
    if resp.status_code == 429:
        raise RuntimeError("ORS-Limit erreicht (429). Etwas später erneut versuchen.")
    resp.raise_for_status()
    feat = resp.json()["features"][0]
    coords = feat["geometry"]["coordinates"]  # [lon, lat, ele]
    props = feat.get("properties", {})
    summary = props.get("summary", {})

    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    eles = [c[2] if len(c) > 2 else 0.0 for c in coords]
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + _haversine(lats[i - 1], lons[i - 1], lats[i], lons[i]))
    dist_km = summary.get("distance", cum[-1]) / 1000.0

    steps: list[dict[str, Any]] = []
    if instructions:
        for seg in props.get("segments", []):
            for st in seg.get("steps", []):
                wp = st.get("way_points", [0, 0])
                steps.append({
                    "instruction": st.get("instruction", ""),
                    "wp0": int(wp[0]),
                    "wp1": int(wp[1] if len(wp) > 1 else wp[0]),
                })

    return Route(
        lats=lats,
        lons=lons,
        distance_km=round(dist_km, 1),
        ascent_m=round(float(props.get("ascent", 0.0)), 0),
        profile_dist_km=[round(d / 1000.0, 2) for d in cum],
        profile_ele_m=eles,
        seed=seed,
        steps=steps,
    )


def _route_headwinds(
    route: Route, wind_from_deg: float, wind_kmh: float
) -> tuple[list[float], list[float]]:
    """Kumulierte Distanz (km) und Gegenwind-Komponente (km/h) je Abschnitt."""
    cum: list[float] = []
    head: list[float] = []
    dist = 0.0
    for i in range(len(route.lats) - 1):
        seg = _haversine(route.lats[i], route.lons[i], route.lats[i + 1], route.lons[i + 1])
        if seg <= 0:
            continue
        bearing = _bearing(route.lats[i], route.lons[i], route.lats[i + 1], route.lons[i + 1])
        hw = wind_kmh * math.cos(math.radians(bearing - wind_from_deg))
        dist += seg / 1000.0
        cum.append(round(dist, 3))
        head.append(hw)
    return cum, head


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def wind_score(route: Route, wind_from_deg: float) -> float:
    """+ = Hinweg eher Gegenwind, Rückweg eher Rückenwind (erwünscht)."""
    cum, head = _route_headwinds(route, wind_from_deg, 1.0)
    if not cum:
        return 0.0
    half = cum[-1] / 2
    first = [h for c, h in zip(cum, head) if c <= half]
    second = [h for c, h in zip(cum, head) if c > half]
    if not first or not second:
        return 0.0
    return sum(first) / len(first) - sum(second) / len(second)


def wind_summary(route: Route, wind_from_deg: float, wind_kmh: float) -> dict[str, Any]:
    cum, head = _route_headwinds(route, wind_from_deg, wind_kmh)
    if not cum:
        return {"ok": False, "hint": ""}
    half = cum[-1] / 2
    first = [h for c, h in zip(cum, head) if c <= half]
    second = [h for c, h in zip(cum, head) if c > half]
    f = sum(first) / len(first) if first else 0.0
    s = sum(second) / len(second) if second else 0.0

    def _fmt(v: float) -> str:
        return f"{(0.0 if abs(v) < 0.5 else v):+.0f}"

    good = f > s + 1.0  # Hinweg relativ mehr Gegenwind als der Rückweg
    if good:
        hint = (
            f"✅ Windklug geplant: Der Rückweg hat mehr Rückenwind "
            f"({_fmt(s)} km/h) als der Hinweg ({_fmt(f)} km/h). "
            "(+ = Gegenwind, − = Rückenwind)"
        )
    else:
        hint = ("ℹ️ Bei diesem Rundkurs ließ sich der Wind kaum sinnvoll aufteilen — "
                "achte unterwegs selbst auf die Windrichtung.")
    return {"ok": good, "first": f, "second": s, "hint": hint}


def generate_loop(
    cfg: dict[str, Any],
    length_km: float,
    seed: int | None = None,
    wind_from_deg: float | None = None,
    instructions: bool = False,
) -> Route:
    """Erzeugt eine Schleife nahe `length_km`.

    Ist `wind_from_deg` gesetzt, wird unter den passenden Distanz-Varianten die
    "windklügste" gewählt (Hinweg gegen den Wind, Rückweg mit Rückenwind).
    Mit `instructions=True` kommen Abbiege-Hinweise mit (für die PWA-Navigation).
    """
    if not config.has_routing(cfg):
        raise RuntimeError(
            "Routen-Feature nicht konfiguriert: ORS-API-Key und Heimat-Koordinaten "
            "in der Einrichtung setzen (siehe README)."
        )
    base_seed = seed if seed is not None else random.randint(1, 10_000)
    target_m = length_km * 1000.0
    req_km = length_km * _LENGTH_BIAS

    candidates: list[tuple[float, Route]] = []
    last_exc: Exception | None = None
    for i in range(_MAX_ATTEMPTS):
        s = base_seed + i * 13
        try:
            rt = _request_route(cfg, req_km, s, instructions=instructions)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
        err = abs(rt.distance_km * 1000 - target_m) / target_m
        candidates.append((err, rt))
        # Ohne Windoptimierung reicht die erste gut passende Route.
        if wind_from_deg is None and err <= _TOLERANCE:
            break

    if not candidates:
        raise last_exc or RuntimeError("Keine Route gefunden.")

    if wind_from_deg is None:
        return min(candidates, key=lambda c: c[0])[1]

    # Windoptimierung: unter den distanz-akzeptablen die windklügste wählen.
    acceptable = [c for c in candidates if c[0] <= 0.25] or candidates
    return max(acceptable, key=lambda c: wind_score(c[1], wind_from_deg))[1]
