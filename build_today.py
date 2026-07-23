"""Schreibt ``mobile/today.json`` für die Ride-PWA.

Läuft im GitHub-Actions-Sync (nach dem Datenabgleich): baut die deterministische
Tagesempfehlung + HF-Zonen (Max-HF/Ruhepuls aus Whoop bzw. LTHR) + Wetter als
statische JSON, die die PWA von GitHub Pages same-origin lädt (``fetch('today.json')``).

BEWUSST OHNE Routen-Polyline: die Datei liegt öffentlich auf Pages; eine Route ab
Zuhause würde die als Secret gehaltene Heimat-Koordinate veröffentlichen. Die PWA
plant ihre Route weiter clientseitig aus dem GPS.

Die Empfehlung ist deterministisch und damit gratis; hier wird KEINE Claude-API
benutzt. Wetterfehler sind unkritisch – dann fehlt eben das Feld.

Benutzung:
    python build_today.py                 # schreibt mobile/today.json
    python build_today.py pfad/ziel.json  # in eine andere Datei (z. B. für Tests)
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

from bikedash import config, dataprep, milestones, recommend, weather, zones

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "mobile" / "today.json"


def _load_cfg() -> dict[str, Any]:
    """Config aus config.toml + Umgebungs-Overlay – ohne die strenge Validierung
    von ``load_config`` (Strava/Whoop-Creds sind hier nicht nötig)."""
    cfg = config.load_config_raw()
    config._overlay_env(cfg)
    return cfg


def _parse_cadence(text: str) -> tuple[int | None, int | None]:
    """Wandelt "85–95" / "90-100" in (85, 95). "–" -> (None, None)."""
    nums = re.findall(r"\d+", text or "")
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        return int(nums[0]), int(nums[0])
    return None, None


def _milestone_payload() -> dict[str, Any] | None:
    """Kompakter Meilenstein für die Ride-PWA: nächstes Ziel + Orden-Zähler.

    Route-frei und ohne persönliche Koordinaten – nur aggregierte Kilometer.
    Fehlt die Datenbasis, bleibt das Feld weg (unkritisch fürs Frontend).
    """
    try:
        rides = dataprep.prep_rides()
        if rides.empty:
            return None
        total_km = float(rides["distance_km"].sum())
        mv = milestones.compute(total_km)
        nxt = mv.next_targets[0] if mv.next_targets else None
        return {
            "total_km": round(total_km, 1),
            "orden_earned": len(mv.earned),
            "orden_total": mv.badges_total,
            "next_name": nxt.label if nxt else None,
            "next_icon": nxt.icon if nxt else None,
            "next_remaining_km": round(nxt.remaining_km, 1) if nxt else None,
            "next_km": round(nxt.km, 1) if nxt else None,
        }
    except Exception:  # noqa: BLE001
        return None


def _weather_payload(cfg: dict[str, Any]) -> dict[str, Any] | None:
    try:
        wx = weather.current(cfg)
    except Exception:  # noqa: BLE001
        return None
    if wx is None:
        return None
    return {
        "temp_c": round(wx.temp_c, 1),
        "wind_kmh": round(wx.wind_kmh, 1),
        "wind_deg": round(wx.wind_deg),
        "wind_dir": wx.wind_dir,
        "gust_kmh": round(wx.gust_kmh, 1),
        "code": wx.code,
        "desc": wx.desc,
    }


def build(out_path: Path = DEFAULT_OUT, today: dt.date | None = None) -> dict[str, Any]:
    cfg = _load_cfg()
    today = today or dt.date.today()
    rc = recommend.build(today)

    max_hr = zones.max_hr_from_data()
    rest_hr = zones.resting_hr_baseline()
    lthr = zones.lthr_from_config()
    cad_lo, cad_hi = _parse_cadence(rc.cadence)

    # Bewusst OHNE Routen-Polyline: today.json liegt öffentlich auf GitHub Pages,
    # eine Route ab Zuhause würde die (als Secret gehaltene) Heimat-Koordinate
    # veröffentlichen. Die PWA plant die Route weiter clientseitig aus dem GPS.
    wx = _weather_payload(cfg)
    milestone = _milestone_payload()

    payload: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "date": today.isoformat(),
        "recommendation": {
            "kind": rc.kind,
            "title": rc.title,
            "readiness_band": rc.readiness_band,
            "recovery_score": rc.recovery_score,
            "zone_number": rc.zone_number,
            "zone_label": rc.zone_label,
            "hr_low": rc.hr_low,
            "hr_high": rc.hr_high,
            "cadence": rc.cadence,
            "cadence_low": cad_lo,
            "cadence_high": cad_hi,
            "rpe": rc.rpe,
            "duration_min": list(rc.duration_min),
            "distance_km": list(rc.distance_km),
            "target_distance_km": rc.target_distance_mid,
            "week_hours": rc.week_hours,
            "target_hours": rc.target_hours,
            "tsb": rc.tsb,
            "rationale": rc.rationale,
        },
        "zones": {
            "max_hr": max_hr,
            "rest_hr": rest_hr,
            "lthr": lthr,
            "target_zone": rc.zone_number,
            "method": zones.method_label(rest_hr, lthr),
        },
        "weather": wx,
        "milestone": milestone,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    payload = build(out)
    rc = payload["recommendation"]
    print(f"today.json geschrieben -> {out}  ({rc['kind']}, route-frei)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
