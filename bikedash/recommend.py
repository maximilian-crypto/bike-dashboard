"""Tagesempfehlung: leitet aus Wochenvolumen + Whoop-Erholung die heutige
Einheit ab (Sessiontyp, Dauer, HF-Zone in bpm, Trittfrequenz, Anstrengung).

Bewusst transparent & nachvollziehbar gehalten — jede Entscheidung kommt mit
einer Begründung, die im Dashboard angezeigt wird.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from . import config, dataprep, form, guard, power, season, zones

# Form-Schwellen (TSB = CTL − ATL). Praktiker-Heuristik (Allen/Coggan) — bewusst
# als kalibrierbare Startwerte, NICHT als hart validierte Grenzen (siehe Doku).
TSB_DEEP_FATIGUE = -30.0   # darunter: keine harte Einheit, Erholung/Deload
TSB_HARD_FLOOR = -20.0     # harte Einheit nur, wenn TSB darüber liegt
TSB_TEMPO_CEIL = -10.0     # darüber echte Intervalle, dazwischen dosierter Z3-Tempo-Reiz
                           # (4×4 hat nur 16 harte Minuten — verträgt leichte Ermüdung)

# Ab wann eine Einheit als „hart" zählt, wenn Wattdaten da sind: Intensity
# Factor (NP/FTP). Eine 4×4-Einheit mit Ein-/Ausfahren landet bei ~0,85,
# lockere Grundlage bei ~0,65–0,70.
HARD_IF = 0.80
# So viele Tage ohne harten Reiz, dann gibt es auch bei gelber Recovery einen
# dosierten Tempo-Reiz — sonst bleibt die Woche bei gelb dauerhaft Z2.
INTENSITY_GAP_DAYS = 10
YELLOW_GAP_MIN_SCORE = 50.0

# Sessiontyp-Vorlagen: (Ziel-Zone, Basisdauer min, Trittfrequenz, RPE 1-10, Tempofaktor)
TEMPLATES = {
    "REST":      dict(zone=None, base_min=0,  cadence="–",       rpe="–",   speed_factor=0.0),
    "RECOVERY":  dict(zone=1,    base_min=40, cadence="85–95",   rpe="2–3", speed_factor=0.82),
    "ENDURANCE": dict(zone=2,    base_min=90, cadence="85–95",   rpe="3–4", speed_factor=0.92),
    "TEMPO":     dict(zone=3,    base_min=75, cadence="85–100",  rpe="5–6", speed_factor=1.05),
    "THRESHOLD": dict(zone=4,    base_min=70, cadence="85–100",  rpe="7–8", speed_factor=1.00),
    # 4×4 nach Helgerud et al. (2007): 4 min bei 90–95 % HFmax, 3 min locker.
    # Feste Struktur — die Dauer wird nicht ans Wochenvolumen angepasst.
    "VO2MAX":    dict(zone=5,    base_min=52, cadence="90–105",  rpe="8–9", speed_factor=1.00),
}

TITLES = {
    "REST": "Ruhetag",
    "RECOVERY": "Lockerer Erholungs-Spin",
    "ENDURANCE": "Grundlagenausdauer (Z2)",
    "TEMPO": "Tempo-Einheit (Z3)",
    "THRESHOLD": "Schwellen-Intervalle (Z4)",
    "VO2MAX": "4×4-Intervalle (Z5)",
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
    tsb: float | None = None
    rationale: list[str] = field(default_factory=list)
    # Saisonplan-Kontext (siehe season.py)
    week_load: float = 0.0
    target_load: float = 0.0
    # Wattvorgaben (nur mit hinterlegter FTP) — drinnen die steuerbare Groesse
    ftp: int | None = None
    power_low: int | None = None
    power_high: int | None = None
    power_plan: list[dict] = field(default_factory=list)
    power_summary: str | None = None
    phase: str | None = None
    phase_label: str | None = None
    weeks_to_go: int | None = None
    is_deload: bool = False
    # Schutzgeländer gegen Überlastung (siehe guard.py)
    guard_level: str = "ok"         # ok | caution | stop
    warnings: list[str] = field(default_factory=list)
    acwr: float | None = None
    streak_days: int = 0

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


def _current_tsb(rides: pd.DataFrame, today: dt.date) -> float | None:
    """Form (TSB) zum aktuellen Tag aus dem Banister-Modell.

    `form.compute` liefert die Kurve bis zum letzten Fahrttag; wir nehmen den
    jüngsten Wert ≤ heute. Liegt der letzte Ride länger zurück, unterschätzt das
    die zwischenzeitliche Erholung leicht — für ein Ermüdungs-Gate konservativ ok.
    """
    if rides.empty or "load" not in rides.columns:
        return None
    fdf = form.compute(rides[["start", "load"]])
    if fdf.empty:
        return None
    upto = fdf[fdf["date"].dt.date <= today]
    if upto.empty:
        return None
    return float(upto.iloc[-1]["tsb"])


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

    # Wochenziel kommt aus dem Saisonplan — gesteuert wird über die **Last**
    # (TSS), nicht über Stunden: 2 h Grundlage und 2 h Intervalle sind nicht
    # derselbe Reiz. Die Stundenzahl ist nur noch die Übersetzung fürs Auge.
    plan = season.build(rides, today)
    week_load = float(week["load"].sum()) if not week.empty else 0.0
    target_load = plan.target_load
    target_hours = plan.target_hours
    progress = week_load / target_load if target_load else 0.0

    # --- Bereitschaft ---
    score = _latest_recovery(rec, today)
    band = _band(score)

    # --- Intensitätsverteilung (polarisiert): harte Tage dieser Woche & zuletzt ---
    max_hr = zones.max_hr_from_data()
    rest_hr = zones.resting_hr_baseline()
    lthr = zones.lthr_from_config()   # falls Feldtest-Wert hinterlegt: Zonen daran ankern

    ftp = config.ftp_from_config()

    def _is_hard(row) -> bool:
        """Harte Einheit? Mit echten Wattdaten über den Intensity Factor — der
        Durchschnittspuls verwässert Intervalle, weil Ein-/Ausfahren und Pausen
        mitzählen. Sonst im Schnitt Z3+ (HRR ≥ 0,75) bzw. hoher Relative Effort."""
        np_w = row.get("weighted_average_watts")
        if ftp and row.get("load_source") == "power" and pd.notna(np_w):
            return np_w / ftp >= HARD_IF
        hr = row.get("average_heartrate")
        if max_hr and pd.notna(hr):
            return zones.intensity_frac(hr, max_hr, rest_hr) >= 0.75
        ss = row.get("suffer_score")
        return bool(pd.notna(ss) and ss >= 120)

    hard_days_week = sum(1 for _, row in week.iterrows() if _is_hard(row)) if not week.empty else 0
    recent_hard = False
    days_since_hard: int | None = None
    if not rides.empty:
        recent = rides[rides["date"] >= today - dt.timedelta(days=2)]
        recent_hard = any(_is_hard(row) for _, row in recent.iterrows())
        hard_dates = [row["date"] for _, row in rides.iterrows()
                      if row["date"] < today and _is_hard(row)]
        if hard_dates:
            days_since_hard = (today - max(hard_dates)).days
    gap = days_since_hard is None or days_since_hard >= INTENSITY_GAP_DAYS

    rode_today = (not rides.empty) and (rides["date"] == today).any()

    # --- Form/Ermüdung (Banister TSB) als zusätzliche Steuerebene ---
    tsb = _current_tsb(rides, today)

    # --- Entscheidungslogik ---
    reasons: list[str] = []
    if score is not None:
        reasons.append(f"Whoop-Recovery heute: {score:.0f} %.")
    else:
        reasons.append("Keine aktuelle Whoop-Recovery — neutrale Annahme.")
    reasons.append(
        f"Diese Woche bisher {week_load:.0f} / Ziel {target_load:.0f} Last "
        f"({progress*100:.0f} %, ≈ {target_hours:.1f} h)."
    )
    reasons.extend(plan.rationale)
    if tsb is not None:
        reasons.append(f"Form (TSB) aktuell {tsb:+.0f}.")

    # Polarisiert: ~80 % locker (Z1–2), harte Reize dosiert, Z3-„Grauzone"
    # meiden. Wie viele harte Einheiten die Woche verträgt, gibt die Phase des
    # Saisonplans vor — in der Grundlage bewusst nur eine.
    POLARIZED_HARD_CAP = plan.hard_days_max

    if rode_today:
        kind = "REST"
        reasons.append("Du bist heute bereits gefahren — Fokus auf Regeneration.")
    elif tsb is not None and tsb < TSB_DEEP_FATIGUE:
        kind = "RECOVERY" if progress < 1.2 else "REST"
        reasons.append(
            f"Form stark im Minus (TSB {tsb:+.0f} < {TSB_DEEP_FATIGUE:.0f}) — "
            "akkumulierte Ermüdung, heute nur locker (Z1) oder Deload."
        )
    elif band == "red":
        kind = "RECOVERY" if progress < 1.2 else "REST"
        reasons.append("Erholung niedrig (rot): heute nur locker (Z1) oder Pause.")
    elif band == "yellow":
        if recent_hard:
            kind = "RECOVERY"
            reasons.append("Letzte Einheit war intensiv — heute regenerativ (Z1).")
        elif (gap and score >= YELLOW_GAP_MIN_SCORE and hard_days_week < POLARIZED_HARD_CAP
              and (tsb is None or tsb > TSB_TEMPO_CEIL)):
            kind = "TEMPO"
            since = (f"seit {days_since_hard} Tagen" if days_since_hard is not None
                     else "bisher")
            reasons.append(
                f"Erholung mittel, aber {since} kein harter Reiz — dosiertes Tempo (Z3), "
                "damit die Intensität nicht ganz einschläft."
            )
        elif progress < 0.9:
            kind = "ENDURANCE"
            reasons.append("Erholung mittel & Woche noch dünn: ruhige Grundlage (Z2).")
        else:
            kind = "ENDURANCE" if progress < 1.3 else "REST"
            reasons.append("Erholung mittel: aerob bleiben (Z2), Volumen schon ok.")
    elif band == "green":
        # Die harte Einheit hängt bewusst NICHT am Wochenziel: bei kleinem
        # Umfang bringt Intensität den Reiz (Milanović et al. 2015), und wer
        # über dem Ziel liegt, bekäme sonst nie Intervalle. Gegen Überlastung
        # schützen TSB, das Kontingent harter Tage und guard.py.
        if recent_hard:
            kind = "ENDURANCE"
            reasons.append("Top erholt, aber zuletzt hart — heute Grundlage (Z2) zum Verarbeiten.")
        elif hard_days_week >= POLARIZED_HARD_CAP:
            kind = "ENDURANCE"
            reasons.append(
                f"Schon {hard_days_week} harte Einheit{'en' if hard_days_week != 1 else ''} "
                f"diese Woche (Phase erlaubt {POLARIZED_HARD_CAP}) — der Rest bleibt locker (Z2)."
            )
        elif (score is None or score >= 70) and (tsb is None or tsb > TSB_HARD_FLOOR):
            if tsb is not None and tsb <= TSB_TEMPO_CEIL:
                kind = "TEMPO"
                reasons.append(
                    f"Grünes Licht, Form aber merklich ermüdet (TSB {tsb:+.0f}) — "
                    "dosierter Tempo-Reiz (Z3) statt voller Intervalle."
                )
            elif plan.phase == season.PHASE_BASIS or hard_days_week == 0:
                kind = "VO2MAX"
                reasons.append(
                    "Bestens erholt & harte Einheit frei: 4×4 min nahe Maximalpuls. "
                    "Das Protokoll mit der besten Studienlage für Schlagvolumen und "
                    "VO2max (Helgerud et al. 2007) — kurz, hart, wirksam."
                )
            else:
                kind = "THRESHOLD"
                reasons.append(
                    "Zweite harte Einheit der Woche: Schwellen-Intervalle (Z4) für "
                    "die Dauerleistung — ergänzt die 4×4 vom Wochenanfang."
                )
            if days_since_hard is not None and days_since_hard >= INTENSITY_GAP_DAYS:
                reasons.append(f"Letzter harter Reiz vor {days_since_hard} Tagen.")
        elif score is None or score >= 70:
            kind = "ENDURANCE"
            reasons.append(
                f"Erholt, aber Form ermüdet (TSB {tsb:+.0f} ≤ {TSB_HARD_FLOOR:.0f}) — "
                "heute aerob (Z2) statt harter Reiz, damit die Ermüdung abbaut."
            )
        else:
            kind = "ENDURANCE"
            reasons.append("Gut erholt: solide Grundlage (Z2) baut die aerobe Basis.")
    else:  # unknown
        kind = "ENDURANCE" if progress < 1.1 else "RECOVERY"
        reasons.append("Ohne Erholungsdaten konservativ: ruhige Grundlage (Z2).")

    # Schutzgeländer: deckelt die Einheit, wenn sich Last ungesund aufschaukelt
    # (Lastsprung, zu viele Tage am Stück, gehäuft rote Recovery). Greift auch
    # bei grüner Recovery — und hebt nie an.
    g = guard.check(rides, rec, today)
    capped = g.apply(kind)
    if capped != kind:
        reasons.append(f"Schutzgeländer: {TITLES[kind]} → {TITLES[capped]}.")
        kind = capped

    tpl = TEMPLATES[kind]

    # Dauer nach Volumenstand anpassen.
    base = tpl["base_min"]
    if kind not in ("REST", "VO2MAX"):
        if progress < 0.7:
            base = int(base * 1.2)
        elif progress > 1.2:
            base = int(base * 0.8)
    dur = (0, 0) if base == 0 else (int(base * 0.85), int(base * 1.15))
    if kind == "VO2MAX":
        dur = (50, 55)   # feste 4×4-Struktur: 15' ein, 25' Intervalle, 10' aus

    # HF-Zone in bpm (Priorität: LTHR-Schwellenzonen → Karvonen/HRR → %max).
    zlow = zhigh = znum = zlabel = None
    if tpl["zone"] and (max_hr or lthr):
        z = zones.zone_for(tpl["zone"], max_hr, rest_hr, lthr)
        znum, zlabel, zlow, zhigh = z.number, z.label, z.low_bpm, z.high_bpm

    # Wattvorgabe + abfahrbare Struktur. Drinnen ist Leistung die steuerbare
    # Groesse: die Herzfrequenz hinkt dem Reiz hinterher und driftet mit der
    # Hitze. Ohne hinterlegte FTP bleibt alles leer und es aendert sich nichts.
    p_low = p_high = None
    p_blocks: list[dict] = []
    p_summary = None
    if ftp and tpl["zone"]:
        pz = power.zone_for(tpl["zone"], ftp)
        if pz:
            p_low, p_high = pz.low_w, pz.high_w
        mid = int(sum(dur) / 2) if dur[1] else 0
        blocks = power.structure(kind, mid, ftp, tpl["cadence"])
        p_blocks = [
            {"label": b.label, "minutes": b.minutes, "low_w": b.low_w,
             "high_w": b.high_w, "zone": b.zone, "cadence": b.cadence}
            for b in blocks
        ]
        p_summary = power.describe(blocks) or None

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
        tsb=round(tsb, 1) if tsb is not None else None,
        rationale=reasons,
        guard_level=g.level,
        warnings=g.warnings,
        acwr=g.acwr,
        streak_days=g.streak_days,
        week_load=round(week_load, 1),
        target_load=round(target_load, 1),
        phase=plan.phase,
        phase_label=plan.phase_label,
        weeks_to_go=plan.weeks_to_go,
        is_deload=plan.is_deload,
        ftp=ftp,
        power_low=p_low,
        power_high=p_high,
        power_plan=p_blocks,
        power_summary=p_summary,
    )
