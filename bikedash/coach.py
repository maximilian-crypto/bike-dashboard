"""KI-Coach: beantwortet Fragen zu den eigenen Daten über die Claude API.

Stellt aus den lokalen Daten eine kompakte Zusammenfassung zusammen und gibt
sie Claude als Kontext mit. Antworten sind Trainingsberatung, kein Arztersatz.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import config, dataprep, form, recommend, weather, windlab, zones

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = (
    "Du bist ein erfahrener, motivierender Radsport-Trainer. Du berätst den "
    "Nutzer auf Deutsch, knapp und konkret, immer gestützt auf seine echten "
    "Daten (unten als KONTEXT). Nenne konkrete Zahlen aus den Daten, gib "
    "umsetzbare Empfehlungen (HF-Zonen, Dauer, Intensität, Erholung). Sei "
    "ehrlich, aber ermutigend. Du gibst Trainings-, keine medizinischen "
    "Ratschläge — bei Gesundheitssorgen verweise an Fachleute."
)


class CoachError(RuntimeError):
    pass


def _client(cfg: dict[str, Any]):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise CoachError("Das Paket 'anthropic' fehlt (pip install anthropic).") from exc

    section = cfg.get("coach", {})
    api_key = str(section.get("api_key", "")).strip()
    if api_key and not api_key.startswith("DEIN"):
        return anthropic.Anthropic(api_key=api_key)
    # Sonst aus der Umgebung (ANTHROPIC_API_KEY).
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return anthropic.Anthropic()
    raise CoachError(
        "Kein Anthropic-API-Key. Trage ihn in der Einrichtung unter "
        "[coach] api_key ein (oder setze ANTHROPIC_API_KEY)."
    )


def model_for(cfg: dict[str, Any]) -> str:
    return str(cfg.get("coach", {}).get("model", DEFAULT_MODEL) or DEFAULT_MODEL)


def build_summary() -> str:
    """Kompakte Daten-Zusammenfassung als Kontext für den Coach."""
    lines: list[str] = []
    today = dt.date.today()
    rides = dataprep.prep_rides()
    rec = dataprep.prep_recovery()

    if rides.empty:
        return "Noch keine Fahrtdaten vorhanden."

    # Letzte 4 Wochen
    last28 = rides[rides["date"] >= today - dt.timedelta(days=28)]
    lines.append(
        f"Letzte 4 Wochen: {len(last28)} Fahrten, {last28['distance_km'].sum():.0f} km, "
        f"{last28['moving_h'].sum():.1f} h, {last28['elev_m'].sum():.0f} Hm."
    )
    # Gesamt
    lines.append(
        f"Gesamt erfasst: {len(rides)} Fahrten seit {rides['date'].min()}."
    )

    # Letzte 5 Fahrten
    lines.append("Letzte Fahrten:")
    for _, r in rides.sort_values("start", ascending=False).head(5).iterrows():
        hr = f", {r['average_heartrate']:.0f} bpm" if r["average_heartrate"] == r["average_heartrate"] else ""
        lines.append(
            f"  - {r['date']}: {r['name']} — {r['distance_km']:.0f} km, "
            f"{r['avg_speed_kmh']:.1f} km/h, {r['elev_m']:.0f} Hm{hr}"
        )

    # Erholung
    if not rec.empty:
        recent = rec.tail(7)
        if recent["recovery_score"].notna().any():
            lines.append(
                f"Whoop-Recovery (7-Tage-Schnitt): {recent['recovery_score'].mean():.0f} %, "
                f"Ruhepuls {recent['resting_heart_rate'].mean():.0f} bpm, "
                f"HRV {recent['hrv_rmssd_milli'].mean():.0f} ms."
            )

    # Form
    fdf = form.compute(rides)
    if len(fdf) >= 7:
        cur = fdf.iloc[-1]
        status, _ = form.interpret(cur["tsb"])
        lines.append(
            f"Form: Fitness(CTL) {cur['ctl']:.0f}, Ermüdung(ATL) {cur['atl']:.0f}, "
            f"Form(TSB) {cur['tsb']:+.0f} ({status})."
        )

    # HF-Zonen (Karvonen/HRR wie in Whoop)
    mhr = zones.max_hr_from_data()
    rhr = zones.resting_hr_baseline()
    if mhr:
        zs = ", ".join(f"{z.label.split(' ')[0]} {z.low_bpm}-{z.high_bpm}"
                       for z in zones.zones(mhr, rhr))
        rest_txt = f", Ruhe {rhr}" if rhr else ""
        lines.append(f"HF-Zonen ({zones.method_label(rhr)}, Max {mhr}{rest_txt}): {zs}.")

    # Wind-Malus
    fit = windlab.analyze()
    if fit is not None:
        lines.append(
            f"Gegenwind-Malus (flach): ~{-fit.slope*10:.1f} km/h pro 10 km/h Gegenwind."
        )

    # Heutige Empfehlung
    rc = recommend.build(today=today)
    zone = f"Z{rc.zone_number} {rc.hr_low}-{rc.hr_high} bpm" if rc.hr_low else "—"
    lines.append(
        f"Heutige Empfehlung: {rc.title} (Bereitschaft {rc.readiness_band}), "
        f"Zone {zone}, Trittfrequenz {rc.cadence}, RPE {rc.rpe}."
    )
    return "\n".join(lines)


def _messages(question: str, history: list[dict[str, str]], summary: str):
    msgs: list[dict[str, Any]] = []
    for turn in history:
        msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({
        "role": "user",
        "content": f"KONTEXT (meine aktuellen Daten):\n{summary}\n\nFrage: {question}",
    })
    return msgs


def ask(cfg: dict[str, Any], question: str, history: list[dict[str, str]] | None = None) -> str:
    client = _client(cfg)
    summary = build_summary()
    try:
        resp = client.messages.create(
            model=model_for(cfg),
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=_messages(question, history or [], summary),
        )
    except Exception as exc:  # noqa: BLE001  (anthropic-Fehlerklassen unterschiedlich)
        raise CoachError(f"Anthropic-Fehler: {exc}") from exc
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def weekly_review(cfg: dict[str, Any]) -> str:
    return ask(
        cfg,
        "Schreibe mir einen motivierenden, ehrlichen Wochenrückblick: Wie war "
        "mein Training, wo stehe ich bei Form und Erholung, und worauf sollte "
        "ich nächste Woche achten? Maximal 8 Sätze.",
    )
