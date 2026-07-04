"""Morgen-Report: heutige Empfehlung + Wetter + Form, optional als Handy-Push.

Push läuft über ntfy.sh (kostenlos, ohne Konto): in der ntfy-App auf dem Handy
ein selbst gewähltes Thema abonnieren und dasselbe Thema in der Einrichtung
unter [report] ntfy_topic eintragen.
"""

from __future__ import annotations

from typing import Any

import requests

from . import config, dataprep, form, recommend, weather


def build_text(cfg: dict[str, Any]) -> tuple[str, str]:
    """Gibt (Titel, Nachricht) für den heutigen Report zurück."""
    rc = recommend.build()
    title = f"Heute: {rc.title}"  # Titel ASCII/Latin-1 halten (HTTP-Header)

    parts: list[str] = []
    if rc.kind == "REST":
        parts.append("Ruhetag — erhol dich gut. 🌱")
    else:
        zone = f" in {rc.hr_low}-{rc.hr_high} bpm (Z{rc.zone_number})" if rc.hr_low else ""
        parts.append(
            f"{rc.duration_min[0]}-{rc.duration_min[1]} Min{zone}, "
            f"Trittfrequenz {rc.cadence}, RPE {rc.rpe}."
        )
        if rc.distance_km[1] > 0:
            parts.append(f"Ziel ~{rc.distance_km[0]:.0f}-{rc.distance_km[1]:.0f} km.")
    if rc.recovery_score is not None:
        parts.append(f"Recovery {rc.recovery_score:.0f} %.")
    parts.append(
        f"Woche bisher {rc.week_hours:.1f}/{rc.target_hours:.1f} h."
    )

    wx = weather.current(cfg)
    if wx is not None:
        parts.append(
            f"Wetter: {wx.icon} {wx.temp_c:.0f}°C, Wind {wx.wind_kmh:.0f} km/h aus "
            f"{wx.wind_dir}, Regen {wx.precip_prob}%."
        )
        tips = weather.advice(wx)
        if tips and not tips[0].startswith("👍"):
            parts.append(tips[0])

    fdf = form.compute(dataprep.prep_rides())
    if len(fdf) >= 7:
        cur = fdf.iloc[-1]
        status, _ = form.interpret(cur["tsb"])
        parts.append(f"Form (TSB) {cur['tsb']:+.0f} — {status}.")

    return title, "\n".join(parts)


def send_push(cfg: dict[str, Any], title: str, message: str) -> bool:
    """Schickt den Report per ntfy ans Handy. True bei Erfolg."""
    topic = str(cfg.get("report", {}).get("ntfy_topic", "")).strip()
    if not topic or topic.startswith("DEIN"):
        return False
    try:
        # Titel auf Latin-1 reduzieren, damit der HTTP-Header sicher ist.
        safe_title = title.encode("latin-1", "replace").decode("latin-1")
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": safe_title, "Tags": "bike", "Priority": "default"},
            timeout=20,
        )
        return resp.status_code < 300
    except requests.RequestException:
        return False
