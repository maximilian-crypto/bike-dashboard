"""Saisonplan: progressive Überlast mit Richtung auf ein Zieldatum.

Die Tagesempfehlung in `recommend.py` ist **reaktiv** — sie schaut auf Erholung
und Form und entscheidet, ob heute etwas geht. Was ihr fehlt, ist eine
*Richtung*: das Wochenziel war bisher schlicht der Schnitt der letzten vier
Wochen. Wer 1 h/Woche fährt, bekommt für immer 1 h/Woche vorgeschlagen — ein
Plateau per Konstruktion.

Dieses Modul liefert die fehlende Ebene: eine **Sollkurve der Wochenlast** bis
zum Saisonstart. Beide Ebenen greifen ineinander:

    Saisonplan  → wie viel Last diese Woche anstehen sollte  (Richtung)
    Whoop/Form  → ob heute davon etwas geliefert wird        (Sicherheit)

Getroffene Entscheidungen
-------------------------
1. **Relative Steigerung (%/Woche), nicht absolute CTL-Rampe.** Der übliche
   Richtwert „+3 bis +5 CTL pro Woche" stammt von trainierten Fahrern mit
   CTL 50+. Wer bei CTL 8 startet, für den sind +4 eine Verdreifachung der
   Wochenlast. Deshalb steigern wir prozentual — das skaliert am Einstieg sanft
   und später von selbst kräftiger.
2. **Sicherheitsdeckel über die CTL-Rampe.** Sobald die prozentuale Steigerung
   in absoluten Zahlen zu schnell wird, greift `MAX_CTL_RAMP`.
3. **Entlastungswoche als fester Takt**, nicht nach Gefühl — jede vierte Woche.
   Anpassung passiert in der Erholung, nicht im Reiz.
4. **Realitäts-Klammer.** Nach Krankheit oder Pause würde eine reine
   Sollkurve einen unmöglichen Sprung verlangen. Die Zielwoche liegt deshalb nie
   über `CATCHUP_CAP` × der besten der letzten drei Wochen.
5. **Plananker in `app_kv`**, damit die Kurve über Läufe stabil bleibt und der
   Plan nicht dem rollenden Mittelwert hinterherläuft (was das Plateau wieder
   einführen würde).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field

import pandas as pd

from . import config, form, store

KV_KEY = "season_plan"

# Voreingestelltes Saisonziel, überschreibbar via [athlete] season_start.
DEFAULT_SEASON_START = dt.date(2027, 3, 1)

WEEKLY_RAMP = 0.10       # +10 % Wochenlast je Aufbauwoche
DELOAD_EVERY = 4         # jede vierte Woche ist Entlastung
DELOAD_FACTOR = 0.65     # … auf 65 % der Sollkurve
MAX_CTL_RAMP = 5.0       # harter Deckel: nie mehr als +5 CTL pro Woche fordern
CATCHUP_CAP = 1.30       # nie mehr als 130 % der besten der letzten drei Wochen
MIN_WEEKLY_LOAD = 30.0   # Untergrenze, damit ein Neustart nicht bei 0 klebt

# Grobe Umrechnung Last -> Stunden, nur für die Anzeige. Eine ruhige
# Grundlagenstunde liegt bei ~60 TSS; harte Einheiten liegen darüber.
TSS_PER_HOUR = 60.0

PHASE_BASIS = "BASIS"
PHASE_AUFBAU = "AUFBAU"
PHASE_FORM = "FORM"
PHASE_SAISON = "SAISON"

PHASE_LABELS = {
    PHASE_BASIS: "Grundlage",
    PHASE_AUFBAU: "Aufbau",
    PHASE_FORM: "Formaufbau",
    PHASE_SAISON: "Saison",
}

# Ab wie vielen Restwochen welche Phase gilt.
PHASE_AUFBAU_FROM = 12   # weniger als 12 Wochen bis Saisonstart -> Aufbau
PHASE_FORM_FROM = 4      # weniger als 4 Wochen -> Formaufbau/Anspitzen


@dataclass
class SeasonPlan:
    phase: str
    phase_label: str
    week_index: int          # Woche seit Planstart, 0-basiert
    weeks_to_go: int         # volle Wochen bis Saisonstart
    is_deload: bool
    target_load: float       # Ziel-Wochenlast (TSS)
    target_hours: float      # daraus abgeleitet, nur zur Orientierung
    baseline_load: float     # Wochenlast bei Planstart
    current_ctl: float | None
    hard_days_max: int       # erlaubte harte Einheiten in dieser Woche
    rationale: list[str] = field(default_factory=list)


def season_start_from_config() -> dt.date:
    """Saisonstart aus der Config, sonst der Vorgabewert."""
    cfg = config.load_config_raw()
    config._overlay_env(cfg)
    raw = config.athlete(cfg).get("season_start")
    if not raw:
        return DEFAULT_SEASON_START
    try:
        return dt.date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return DEFAULT_SEASON_START


# ---------------------------------------------------------------------------
# Plananker  (Startdatum + Ausgangslast)
# ---------------------------------------------------------------------------

def load_anchor() -> tuple[dt.date, float] | None:
    raw = store.get_kv(KV_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return dt.date.fromisoformat(data["start"]), float(data["baseline_load"])
    except (ValueError, TypeError, KeyError):
        return None


def save_anchor(start: dt.date, baseline_load: float) -> None:
    store.set_kv(KV_KEY, json.dumps(
        {"start": start.isoformat(), "baseline_load": round(float(baseline_load), 1)}
    ))


def clear_anchor() -> None:
    store.delete_kv(KV_KEY)


# ---------------------------------------------------------------------------
# Rechenkern (rein, ohne DB)
# ---------------------------------------------------------------------------

def is_deload_week(week_index: int) -> bool:
    """Jede vierte Woche ist Entlastung — die erste Planwoche nie."""
    return week_index > 0 and (week_index + 1) % DELOAD_EVERY == 0


def phase_for(weeks_to_go: int) -> str:
    if weeks_to_go <= 0:
        return PHASE_SAISON
    if weeks_to_go < PHASE_FORM_FROM:
        return PHASE_FORM
    if weeks_to_go < PHASE_AUFBAU_FROM:
        return PHASE_AUFBAU
    return PHASE_BASIS


def hard_days_for(phase: str) -> int:
    """Erlaubte harte Einheiten pro Woche. In der Grundlage bewusst wenig —
    der Ruhepuls fällt durch Umfang, nicht durch Intensität."""
    return {PHASE_BASIS: 1, PHASE_AUFBAU: 2, PHASE_FORM: 2, PHASE_SAISON: 2}[phase]


def ramp_target(baseline_load: float, week_index: int) -> float:
    """Sollkurve ohne Deckelung: prozentuale Steigerung je Aufbauwoche.

    Entlastungswochen zählen nicht als Steigerungsschritt — sonst würde der
    Plan über den Deload hinweg weiterwachsen und die Entlastung auffressen.
    """
    build_weeks = sum(1 for w in range(week_index) if not is_deload_week(w))
    target = max(baseline_load, MIN_WEEKLY_LOAD) * (1.0 + WEEKLY_RAMP) ** build_weeks
    if is_deload_week(week_index):
        target *= DELOAD_FACTOR
    return target


def ctl_ceiling(current_ctl: float | None) -> float | None:
    """Wochenlast, die die CTL um höchstens `MAX_CTL_RAMP` anhebt.

    CTL ist ein 42-Tage-EWMA; bei konstanter Tageslast L gilt näherungsweise
    ΔCTL je Woche ≈ (L − CTL) / 6. Umgestellt nach der Wochenlast 7·L.
    """
    if current_ctl is None:
        return None
    return 7.0 * (current_ctl + 6.0 * MAX_CTL_RAMP)


def recent_best_week(weekly_loads: list[float]) -> float | None:
    """Beste der letzten (bis zu) drei abgeschlossenen Wochen."""
    recent = [w for w in weekly_loads[-3:] if w > 0]
    return max(recent) if recent else None


# ---------------------------------------------------------------------------
# Zusammenbau
# ---------------------------------------------------------------------------

def weekly_loads(rides: pd.DataFrame, today: dt.date) -> list[float]:
    """Wochensummen der Last bis einschließlich der letzten *vollen* Woche."""
    if rides.empty or "load" not in rides.columns:
        return []
    this_monday = today - dt.timedelta(days=today.weekday())
    past = rides[rides["date"] < this_monday]
    if past.empty:
        return []
    # closed/label="left": Wochen laufen von Montag bis Sonntag. Ohne das
    # gruppiert pandas rechtsseitig und zerschneidet jede Trainingswoche.
    s = past.set_index("start")["load"].resample(
        "W-MON", closed="left", label="left").sum()
    return [float(v) for v in s.tolist()]


def build(rides: pd.DataFrame, today: dt.date | None = None,
          season_start: dt.date | None = None) -> SeasonPlan:
    """Wochenziel für die laufende Woche."""
    today = today or dt.date.today()
    season_start = season_start or season_start_from_config()

    loads = weekly_loads(rides, today)
    chronic = (sum(loads[-4:]) / len(loads[-4:])) if loads else 0.0

    anchor = load_anchor()
    if anchor is None:
        this_monday = today - dt.timedelta(days=today.weekday())
        baseline = max(chronic, MIN_WEEKLY_LOAD)
        save_anchor(this_monday, baseline)
        start, baseline_load = this_monday, baseline
    else:
        start, baseline_load = anchor

    week_index = max(0, (today - start).days // 7)
    weeks_to_go = max(0, (season_start - today).days // 7)
    phase = phase_for(weeks_to_go)
    deload = is_deload_week(week_index)

    current_ctl = None
    if not rides.empty and "load" in rides.columns:
        fdf = form.compute(rides[["start", "load"]])
        upto = fdf[fdf["date"].dt.date <= today] if not fdf.empty else fdf
        if not upto.empty:
            current_ctl = float(upto.iloc[-1]["ctl"])

    reasons: list[str] = []
    target = ramp_target(baseline_load, week_index)
    reasons.append(
        f"Planwoche {week_index + 1}, Phase „{PHASE_LABELS[phase]}“ — "
        f"noch {weeks_to_go} Wochen bis zum Saisonstart."
    )
    if deload:
        reasons.append(
            f"Entlastungswoche (jede {DELOAD_EVERY}.): Ziel auf "
            f"{DELOAD_FACTOR:.0%} — Anpassung passiert in der Erholung."
        )

    ceiling = ctl_ceiling(current_ctl)
    if ceiling is not None and target > ceiling:
        target = ceiling
        reasons.append(
            f"Gedeckelt auf max. +{MAX_CTL_RAMP:.0f} CTL pro Woche — "
            "schneller ist kein Gewinn, sondern Verletzungsrisiko."
        )

    best = recent_best_week(loads)
    if best is not None and not deload:
        cap = best * CATCHUP_CAP
        if target > cap:
            target = cap
            reasons.append(
                f"An die Realität angepasst: höchstens {CATCHUP_CAP:.0%} deiner "
                "besten der letzten drei Wochen — nach einer Pause wird nicht "
                "aufgeholt, sondern wieder herangeführt."
            )

    target = max(target, MIN_WEEKLY_LOAD * (DELOAD_FACTOR if deload else 1.0))

    return SeasonPlan(
        phase=phase,
        phase_label=PHASE_LABELS[phase],
        week_index=week_index,
        weeks_to_go=weeks_to_go,
        is_deload=deload,
        target_load=round(target, 1),
        target_hours=round(target / TSS_PER_HOUR, 1),
        baseline_load=round(baseline_load, 1),
        current_ctl=round(current_ctl, 1) if current_ctl is not None else None,
        hard_days_max=hard_days_for(phase),
        rationale=reasons,
    )


def projection(baseline_load: float, weeks: int,
               current_ctl: float | None = None) -> list[dict]:
    """Vorschau der Sollkurve — für die Darstellung im Dashboard.

    Rein rechnerisch, ohne die Realitäts-Klammer: zeigt, wohin der Plan führt,
    wenn er eingehalten wird.
    """
    out = []
    ctl = current_ctl
    for w in range(weeks):
        target = ramp_target(baseline_load, w)
        ceiling = ctl_ceiling(ctl)
        if ceiling is not None and target > ceiling:
            target = ceiling
        if ctl is not None:
            ctl = ctl + (target / 7.0 - ctl) / 6.0
        out.append({
            "week": w + 1,
            "target_load": round(target, 1),
            "target_hours": round(target / TSS_PER_HOUR, 1),
            "is_deload": is_deload_week(w),
            "ctl": round(ctl, 1) if ctl is not None else None,
        })
    return out
