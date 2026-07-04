"""GPX-Export für generierte Routen.

GPX ist reines XML — kein externes Paket nötig. Der erzeugte Track lässt sich
in Komoot, Garmin Connect, Wahoo, Strava & Co. als zu fahrende Route importieren.
"""

from __future__ import annotations

import datetime as dt
from xml.sax.saxutils import escape


def track_gpx(name: str, lats, lons, eles=None) -> str:
    """Baut einen GPX-1.1-Track aus Koordinaten (+ optionalen Höhen)."""
    n = min(len(lats), len(lons))
    eles = list(eles) if eles is not None else []
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe = escape(name)

    pts: list[str] = []
    for i in range(n):
        ele = ""
        if i < len(eles) and eles[i] is not None:
            ele = f"<ele>{float(eles[i]):.1f}</ele>"
        pts.append(f'<trkpt lat="{float(lats[i]):.6f}" lon="{float(lons[i]):.6f}">{ele}</trkpt>')

    body = "\n      ".join(pts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="RIDE Fahrrad-Dashboard" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <metadata><name>{safe}</name><time>{now}</time></metadata>\n"
        f"  <trk>\n    <name>{safe}</name>\n    <trkseg>\n"
        f"      {body}\n"
        "    </trkseg>\n  </trk>\n</gpx>\n"
    )


def route_to_gpx(route, name: str = "RIDE Rundkurs") -> str:
    """Bequemer Wrapper für ein routing.Route-Objekt."""
    eles = getattr(route, "profile_ele_m", None)
    return track_gpx(name, route.lats, route.lons, eles)
