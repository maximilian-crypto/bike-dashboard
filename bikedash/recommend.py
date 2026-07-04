"""Tagesempfehlung: leitet aus Wochenvolumen + Whoop-Erholung die heutige
Einheit ab (Sessiontyp, Dauer, HF-Zone in bpm, Trittfrequenz, Anstrengung).

Bewusst transparent & nachvollziehbar gehalten — jede Entscheidung kommt mit
einer Begründung, die im Dashboard angezeigt wird.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from . import dataprep, zones

# Sessiontyp-Vorlagen: (Ziel-Zone, Basisdauer min, Trittfrequenz, RPE 1-10, Tempofaktor)
TEMPLATES = {
    "REST":      dict(zone=None, base_min=0,  cadence="–",       rpe="–",   speed_factor=0.0),
    "RECOVERY":  dict(zone=1,    base_min=40, cadence="85–95",   rpe="2–3", speed_factor=0.82),
    "ENDURANCE": dict(zone=2,    base_min=90, cadence="85–95",   rpe="3–4", speed_factor=0.92),
    "TEMPO":     dict(zone=3,    base_min=75, cadence="85–95",   rpe="5–6", speed_factor=1.05),
    "THRESHOLD": dict(zone=4,    base_min=70, cadence="90–100",  rpe="7–8", speed_factor=1.00),
}

TITLES = {
    "REST": "Ruhetag",
    "RECOVERY": "Lockerer Erholungs-Spin",
    "ENDURANCE": "Grundlagenausdauer (Z2)",
    "TEMPO": "Tempo-Einheit (Z3)",
    "THRESHOLD": "Schwellen-Intervalle (Z4)",
}


@dataclass
class Recommendation:
    kind: str
    title: str
    readiness_band: str            # green | yellow | red | unknown
    recovery_score: float | None
    zone_number: int | None
    zone_label: str | None
    hr_low: int | None
    hr_high: int | None
    cadence: str
    rpe: str
    duration_min: tuple[int, int]
    distance_km: tuple[float, float]
    week_hours: float
    week_km: float
    week_rides: int
    target_hours: float
    rationale: list[str] = field(default_factory=list)

    @property
    def target_distance_mid(self) -> float:
        return round(sum(self.distance_km) / 2, 1)


def _band(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 67:
        return "green"
    if score >= 34:
        return "yellow"
    return "red"


def _latest_recovery(rec: pd.DataFrame, today: dt.date) -> float | None:
    if rec.empty:
        return None
    upto = rec[rec["date"].dt.date <= today]
    if upto.empty:
        return None
    last = upto.iloc[-1]
    # Nur als "heutige" Bereitschaft werten, wenn höchstens 1 Tag alt.
    if (today - last["date"].date()).days > 1:
        return None
    val = last["recovery_score"]
    return float(val) if pd.notna(val) else None


def build(today: dt.date | None = None) -> Recommendation:
    today = today or dt.date.today()
    rides = dataprep.prep_rides()
    rec = dataprep.prep_recovery()

    # --- Wochenkontext (Montag bis heute) ---
    week_start = today - dt.timedelta(days=today.weekday())
    if rides.empty:
        week, week_hours, week_km, week_rides = rides, 0.0, 0.0, 0
        med_speed = 24.0
    else:
        week = rides[(rides["date"] >= week_start) & (rides["date"] <= today)]
        week_hours = float(week["moving_h"].sum())
        week_km = float(week["distance_km"].sum())
        week_rides = int(len(week))
        med_speed = float(rides["avg_speed_kmh"].median() or 24.0)

    # Wochenziel: aus Schnitt der letzten 4 Wochen, mind. 2 h.
    if not rides.empty:
        last28 = rides[rides["date"] >= week_start - dt.timedelta(days=28)]
        chronic_weekly = float(last28["moving_h"].sum()) / 4.0
    else:
        chronic_weekly = 0.0
    target_hours = max(chronic_weekly, 2.0)
    progress = week_hours / target_hours if target_hours else 0.0

    # --- Bereitschaft ---
    score = _latest_recovery(rec, today)
    band = _band(score)

    # --- Intensitätsverteilung (polarisiert): harte Tage dieser Woche & zuletzt ---
    max_hr = zones.max_hr_from_data()
    rest_hr = zones.resting_hr_baseline()

    def _is_hard(row) -> bool:
        """Einheit im Schnitt in Z3+ (HRR ≥ 0,75) bzw. hoher Relative Effort."""
        hr = row.get("average_heartrate")
        if max_hr and pd.notna(hr):
            return zones.intensity_frac(hr, max_hr, rest_hr) >= 0.75
        ss = row.get("suffer_score")
        return bool(pd.notna(ss) and ss >= 120)

    hard_days_week = sum(1 for _, row in week.iterrows() if _is_hard(row)) if not week.empty else 0
    recent_hard = False
    if not rides.empty:
        recent = rides[rides["date"] >= today - dt.timedelta(days=2)]
        recent_hard = any(_is_hard(row) for _, row in recent.iterrows())

    rode_today = (not rides.empty) and (rides["date"] == today).any()

    # --- Entscheidungslogik ---
    reasons: list[str] = []
    if score is not None:
        reasons.append(f"Whoop-Recovery heute: {score:.0f} %.")
    else:
        reasons.append("Keine aktuelle Whoop-Recovery — neutrale Annahme.")
    reasons.append(
        f"Diese Woche bisher {week_hours:.1f} h / Ziel ~{target_hours:.1f} h "
        f"({progress*100:.0f} %)."
    )

    # Polarisiert: ~80 % locker (Z1–2), harte Reize dosiert (≈2×/Woche, ~20 %),
    # Z3-„Grauzone" meiden. Autoregulation über die Whoop-Recovery.
    POLARIZED_HARD_CAP = 2

    if rode_today:
        kind = "REST"
        reasons.append("Du bist heute bereits gefahren — Fokus auf Regeneration.")
    elif band == "red":
        kind = "RECOVERY" if progress < 1.2 else "REST"
        reasons.append("Erholung niedrig (rot): heute nur locker (Z1) oder Pause.")
    elif band == "yellow":
        if recent_hard:
            kind = "RECOVERY"
            reasons.append("Letzte Einheit war intensiv — heute regenerativ (Z1).")
        elif progress < 0.9:
            kind = "ENDURANCE"
            reasons.append("Erholung mittel & Woche noch dünn: ruhige Grundlage (Z2).")
        else:
            kind = "ENDURANCE" if progress < 1.3 else "REST"
            reasons.append("Erholung mittel: aerob bleiben (Z2), Volumen schon ok.")
    elif band == "green":
        if recent_hard:
            kind = "ENDURANCE"
            reasons.append("Top erholt, aber zuletzt hart — heute Grundlage (Z2) zum Verarbeiten.")
        elif hard_days_week >= POLARIZED_HARD_CAP:
            kind = "ENDURANCE"
            reasons.append(
                f"Schon {hard_days_week} harte Einheiten diese Woche — nach der "
                "80/20-Regel bleibt der Rest locker (Z2)."
            )
        elif progress > 1.2:
            kind = "ENDURANCE"
            reasons.append("Top erholt, Wochenvolumen aber hoch: aerob halten (Z2).")
        elif (score is None or score >= 70) and progress < 1.1:
            kind = "THRESHOLD"
            reasons.append(
                "Bestens erholt & Luft im Plan: gezielte harte Einheit (Z4-Schwelle) — "
                "polarisiert heißt, harte Tage wirklich hart zu fahren."
            )
        else:
            kind = "ENDURANCE"
            reasons.append("Gut erholt: solide Grundlage (Z2) baut die aerobe Basis.")
    else:  # unknown
        kind = "ENDURANCE" if progress < 1.1 else "RECOVERY"
        reasons.append("Ohne Erholungsdaten konservativ: ruhige Grundlage (Z2).")

    tpl = TEMPLATES[kind]

    # Dauer nach Volumenstand anpassen.
    base = tpl["base_min"]
    if kind not in ("REST",):
        if progress < 0.7:
            base = int(base * 1.2)
        elif progress > 1.2:
            base = int(base * 0.8)
    dur = (0, 0) if base == 0 else (int(base * 0.85), int(base * 1.15))

    # HF-Zone in bpm (Karvonen/HRR mit Ruhepuls, sonst %max).
    zlow = zhigh = znum = zlabel = None
    if tpl["zone"] and max_hr:
        z = zones.zone_for(tpl["zone"], max_hr, rest_hr)
        znum, zlabel, zlow, zhigh = z.number, z.label, z.low_bpm, z.high_bpm

    # Distanzschätzung aus Dauer × zonentypischem Tempo.
    if base == 0:
        dist = (0.0, 0.0)
    else:
        speed = med_speed * tpl["speed_factor"]
        d_mid = speed * (base / 60.0)
        dist = (round(d_mid * 0.9, 1), round(d_mid * 1.1, 1))

    return Recommendation(
        kind=kind,
        title=TITLES[kind],
        readiness_band=band,
        recovery_score=score,
        zone_number=znum,
        zone_label=zlabel,
        hr_low=zlow,
        hr_high=zhigh,
        cadence=tpl["cadence"],
        rpe=tpl["rpe"],
        duration_min=dur,
        distance_km=dist,
        week_hours=round(week_hours, 1),
        week_km=round(week_km, 1),
        week_rides=week_rides,
        target_hours=round(target_hours, 1),
        rationale=reasons,
    )
