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

from bikedash import (config, dataprep, fitness, fuel, milestones, recommend,
                      weather, zones, zwift)

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


def _load_sources(days: int = 28) -> dict[str, int]:
    """Zählt, woraus die Trainingslast der letzten Wochen berechnet wurde.

    Dient der Selbstkontrolle des gehosteten Laufs: steht hier kein ``power``,
    obwohl Rollen-Einheiten gefahren wurden, fehlt ``ATHLETE_FTP`` in den
    Actions-Secrets — ein Fehler, der sonst nur an still zu niedrigen Lastwerten
    auffiele.
    """
    try:
        rides = dataprep.prep_rides()
        if rides.empty or "load_source" not in rides.columns:
            return {}
        cutoff = dt.date.today() - dt.timedelta(days=days)
        recent = rides[rides["date"] >= cutoff]
        return {str(k): int(v) for k, v in recent["load_source"].value_counts().items()}
    except Exception:  # noqa: BLE001 – Diagnosefeld darf den Tagesplan nie kippen
        return {}


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
            # "orden" = benannter Orden, "step" = generisches Nahziel (Label ist
            # bereits eine Kilometerzahl) – die PWA formuliert danach.
            "next_kind": nxt.kind if nxt else None,
            "next_remaining_km": round(nxt.remaining_km, 1) if nxt else None,
            "next_km": round(nxt.km, 1) if nxt else None,
        }
    except Exception:  # noqa: BLE001
        return None


def _fitness_payload() -> dict[str, Any] | None:
    """Fitness-Index für Ride-PWA und Morgen-Report — nur die Kurzfassung.

    ``persist=False``: der gehostete Lauf soll das Ausgangsniveau nicht
    festschreiben. Der Anker gehört in den Moment, in dem der Nutzer den Index
    zum ersten Mal im Dashboard öffnet und die Historie sieht — nicht in einen
    Cron-Job, der ihn womöglich auf eine halb synchronisierte Datenbank setzt.
    """
    try:
        return fitness.compute(persist=False).to_dict()
    except Exception:  # noqa: BLE001 – ein Kennzahlenfeld darf den Tagesplan nie kippen
        return None


def _fuel_payload(rc: Any, today: dt.date) -> dict[str, Any] | None:
    """Wie viel extra essen fürs heutige Workout (bikedash/fuel.py).

    Nur aggregierte kcal und Portionen — das Körpergewicht selbst steht nicht in
    der öffentlichen Datei.
    """
    try:
        d = fuel.for_recommendation(rc, today).to_dict()
    except Exception:  # noqa: BLE001 – ein Hinweisfeld darf den Tagesplan nie kippen
        return None
    d.pop("weight_kg", None)
    return d


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
    ftp = config.ftp_from_config()
    cad_lo, cad_hi = _parse_cadence(rc.cadence)

    # Bewusst OHNE Routen-Polyline: today.json liegt öffentlich auf GitHub Pages,
    # eine Route ab Zuhause würde die (als Secret gehaltene) Heimat-Koordinate
    # veröffentlichen. Die PWA plant die Route weiter clientseitig aus dem GPS.
    wx = _weather_payload(cfg)
    milestone = _milestone_payload()
    load_sources = _load_sources()
    fit = _fitness_payload()
    fuel_plan = _fuel_payload(rc, today)

    # Tagesworkout in die Zwift-Bibliothek (über intervals.icu). Wirft nie;
    # das Ergebnis steht in today.json und app_kv, damit man im Dashboard
    # sieht, ob das Workout wirklich angekommen ist.
    push = zwift.push_today(cfg, rc, today)
    zwift.remember(push)

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
            # Wattvorgabe fuer die Rolle: drinnen die steuerbare Groesse, weil
            # die Herzfrequenz dem Reiz nachlaeuft und mit der Hitze driftet.
            # Ohne hinterlegte FTP bleiben die Felder null.
            "power_low": rc.power_low,
            "power_high": rc.power_high,
            "power_summary": rc.power_summary,
            "power_plan": rc.power_plan,
            "rationale": rc.rationale,
        },
        "zones": {
            "max_hr": max_hr,
            "rest_hr": rest_hr,
            "lthr": lthr,
            "ftp": ftp,
            "target_zone": rc.zone_number,
            "method": zones.method_label(rest_hr, lthr),
            # Womit die Trainingslast dieser Woche gerechnet wurde. Macht von
            # aussen sichtbar, ob ATHLETE_FTP/ATHLETE_LTHR im gehosteten Lauf
            # tatsächlich angekommen sind — sonst merkt man eine fehlende
            # Umgebungsvariable erst an stillschweigend falschen Zahlen.
            "load_sources": load_sources,
        },
        "weather": wx,
        "milestone": milestone,
        # Fitness-Index: ein Fortschrittswert aus Effizienz, Kapazität,
        # Ermüdungsresistenz, Regeneration und Konsistenz (bikedash/fitness.py).
        "fitness": fit,
        # Energie fürs Workout: Mehrbedarf in kcal, aufgeteilt auf vorher /
        # unterwegs / danach und übersetzt in Cola, Maoam, Toast.
        "fuel": fuel_plan,
        # Ist das heutige Workout in Zwift angekommen? (sent/updated/unchanged =
        # ja; skipped = nicht eingerichtet oder Ruhetag; error = Fehlertext)
        "zwift": push.to_dict(),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    payload = build(out)
    rc = payload["recommendation"]
    print(f"today.json geschrieben -> {out}  ({rc['kind']}, route-frei)")
    z = payload["zwift"]
    print(f"Zwift-Workout: {z['status']}"
          + (f" – {z['name']}" if z.get("name") else "")
          + (f" ({z['detail']})" if z.get("detail") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
