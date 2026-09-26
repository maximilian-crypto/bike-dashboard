"""Energie fürs Workout: wie viel zusätzlich essen — in Cola, Maoam und Toast.

Die Frage, die das Modul beantwortet, ist nicht „wie viel habe ich verbrannt?",
sondern **„wie viel muss ich extra reinholen, damit das Training mich nicht
leer macht?"**. Deshalb:

- **Nur der Mehrverbrauch zählt.** Vom Brutto-Umsatz der Einheit wird abgezogen,
  was der Körper in derselben Zeit ohnehin verbraucht hätte (1 MET). Das Ergebnis
  kommt *oben drauf* auf die normalen Mahlzeiten — es ersetzt keine.
- **Aufgeteilt nach Zeitpunkt** (vorher / unterwegs / danach) und übersetzt in
  Portionen, die man zu Hause hat. Eine nackte Kalorienzahl hilft niemandem, der
  mit leerem Magen vor dem Rad steht.
- **Nie „verdienen", immer „tanken".** Das Modul rechnet nie aus, was man sich
  durch Training erarbeitet hat, und schlägt nie weniger Essen vor. Ruhetage
  bekommen keinen Extra-Wert, aber den Hinweis, dass normale Mahlzeiten auch dann
  zählen — Anpassung passiert in der Erholung, und die braucht Energie.

Schätzung, in dieser Reihenfolge:
1. **Wattplan** (mit FTP): mechanische Arbeit in kJ. Bei ~24 % Brutto-
   Wirkungsgrad entspricht 1 kJ am Pedal ziemlich genau 1 kcal Umsatz — die
   bekannte Faustregel, hier ausgerechnet statt angenommen.
2. **MET-Wert** je Einheitentyp (Compendium of Physical Activities) × Gewicht ×
   Dauer, wenn keine FTP hinterlegt ist.

Für bereits gefahrene Einheiten nimmt ``done_today`` Stravas ``kilojoules``
(bei Powermeter gemessen, sonst Stravas Schätzung), ersatzweise wieder MET.

Genauigkeit: ±20 %. Das reicht, um zu wissen, ob es eine Dose Cola oder drei
sind — und nur das ist die Frage.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from . import config

GROSS_EFFICIENCY = 0.24      # Anteil der Stoffwechselenergie, der am Pedal ankommt
KJ_PER_KCAL = 4.184
DEFAULT_WEIGHT_KG = 75.0     # ohne hinterlegtes Gewicht
REST_MET = 1.0               # was der Körper in der Zeit sowieso verbraucht hätte

# Brutto-MET je Einheitentyp, falls kein Wattplan da ist (Compendium 2011:
# Rad/Ergometer locker ≈ 4, moderat ≈ 6–7, zügig ≈ 8, Rennen 10+). Bewusst im
# unteren Bereich der Spannen: „hart" heißt hier Schwelle des Athleten, nicht
# Renntempo — die Wattrechnung mit FTP 170 landet in derselben Größenordnung.
MET = {"RECOVERY": 4.0, "ENDURANCE": 6.0, "TEMPO": 7.5, "THRESHOLD": 8.5}
MET_UNKNOWN = 7.0            # bereits gefahrene Einheit ohne kJ-Angabe

# Kohlenhydrate unterwegs: ab ~60 min sinnvoll, 30–60 g/h ist die gängige
# Empfehlung für Einheiten bis ca. 2,5 h. Wir planen mit der Mitte.
DURING_FROM_MIN = 60
DURING_CARBS_G_PER_H = 45
KCAL_PER_G_CARB = 4.0
BEFORE_SHARE = 0.3           # Anteil des Mehrbedarfs, der vor die Einheit gehört


@dataclass(frozen=True)
class Food:
    key: str
    name: str
    portion: str             # Einzahl, wie man sie abzählt
    portion_plural: str
    kcal: float
    carbs_g: float
    icon: str


# Nährwerte pro Portion (Herstellerangaben bzw. BLS-Mittelwerte, gerundet).
# Toast: eine Scheibe (25 g) mit einem Teelöffel Honig oder Marmelade.
FOODS: dict[str, Food] = {f.key: f for f in [
    Food("cola", "Cola", "Dose", "Dosen", 139, 35, "🥤"),   # 0,33 l
    Food("maoam", "Maoam Bloxx", "Stück", "Stück", 85, 18, "🍬"),
    Food("toast", "Toast mit Honig", "Scheibe", "Scheiben", 110, 22, "🍞"),
    Food("banana", "Banane", "Banane", "Bananen", 105, 24, "🍌"),
]}

# Was passt wann? Vorher: etwas mit Substanz, das nicht schwer liegt. Unterwegs:
# flüssig oder kaubar mit einer Hand. Danach: echtes Essen.
PHASE_FOODS = {
    "before": ("toast", "banana"),
    "during": ("cola", "maoam"),
    "after": ("toast", "cola"),
}

BASE_MEALS_NOTE = (
    "Die Werte kommen **oben drauf** auf deine normalen Mahlzeiten — sie ersetzen "
    "keine. Wer über den Tag zu wenig isst, fährt schon mit Defizit los."
)
LOW_FUEL_NOTE = (
    "Heute kaum gegessen und fühlst dich schwach? Erst die Vorher-Portion essen "
    "und 20–30 min warten. Wird's nicht besser: kürzere Variante oder Pause — "
    "Training auf leerem Tank baut dich ab statt auf."
)
REST_NOTE = (
    "Ruhetag: kein Extra nötig — aber normale Mahlzeiten zählen heute genauso. "
    "Stärker wirst du in der Erholung, und die läuft nur mit Energie."
)


@dataclass
class Portion:
    key: str
    icon: str
    count: float
    label: str               # „2 Scheiben Toast mit Honig"


@dataclass
class Phase:
    key: str                 # before | during | after
    title: str
    kcal: int
    carbs_g: int
    hint: str
    portions: list[Portion] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " oder ".join(p.label for p in self.portions)


@dataclass
class FuelPlan:
    kind: str
    duration_min: int
    kcal_extra: int                  # Mehrbedarf, schon um den Ruheumsatz bereinigt
    kcal_range: tuple[int, int]
    source: str                      # power | met | ride | none
    weight_kg: float
    weight_known: bool
    phases: list[Phase] = field(default_factory=list)
    equivalents: list[Portion] = field(default_factory=list)   # Gesamtmenge
    notes: list[str] = field(default_factory=list)
    done_today_kcal: int | None = None

    @property
    def available(self) -> bool:
        return self.kcal_extra > 0

    def short(self) -> str:
        """Eine Zeile für Handy-Banner und Push."""
        if not self.available:
            return ""
        eq = " / ".join(p.label for p in self.equivalents[:3])
        return f"Extra essen: ≈ {self.kcal_extra} kcal ({eq})"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kcal_range"] = list(self.kcal_range)
        d["short"] = self.short()
        for ph, src in zip(d["phases"], self.phases):
            ph["text"] = src.text
        return d


# ===========================================================================
# Reine Rechenbausteine
# ===========================================================================

def kcal_from_kj(kj: float) -> float:
    """Mechanische Arbeit (kJ am Pedal) → Stoffwechselumsatz (kcal)."""
    return kj / (GROSS_EFFICIENCY * KJ_PER_KCAL)


def rest_kcal(minutes: float, weight_kg: float) -> float:
    """Was der Körper in derselben Zeit auch auf dem Sofa verbraucht hätte."""
    return REST_MET * weight_kg * minutes / 60.0


def plan_kj(power_plan: list[dict]) -> float:
    """Arbeit eines Wattplans in kJ, gerechnet mit der Mitte jedes Bands."""
    return sum(b["minutes"] * 60 * (b["low_w"] + b["high_w"]) / 2
               for b in power_plan) / 1000.0


def gross_kcal(kind: str, minutes: float, weight_kg: float,
               power_plan: list[dict] | None = None) -> tuple[float, str]:
    """Brutto-Umsatz einer geplanten Einheit und die Quelle der Schätzung."""
    if power_plan:
        return kcal_from_kj(plan_kj(power_plan)), "power"
    met = MET.get(kind)
    if met is None or minutes <= 0:
        return 0.0, "none"
    return met * weight_kg * minutes / 60.0, "met"


def portions(kcal: float, food: Food) -> float:
    """Portionen in halben Schritten, aufgerundet — lieber etwas zu viel.

    Ab einer Portion wird auf halbe gerundet (halbe Dose, halber Toast geht);
    darunter bleibt es bei einer halben, damit nie „0" dasteht.
    """
    if kcal <= 0:
        return 0.0
    return max(0.5, math.ceil(kcal / food.kcal * 2) / 2)


def _fmt_count(n: float) -> str:
    if n == int(n):
        return str(int(n))
    return f"{int(n)}½" if n > 1 else "½"


def portion(kcal: float, key: str) -> Portion:
    f = FOODS[key]
    n = portions(kcal, f)
    unit = f.portion if n <= 1 else f.portion_plural
    if key == "maoam":
        label = f"{_fmt_count(n)} {f.name}"
    elif key == "banana":
        label = f"{_fmt_count(n)} {unit}"
    else:
        label = f"{_fmt_count(n)} {unit} {f.name}"
    return Portion(key, f.icon, n, label)


def split(kcal_extra: float, minutes: float) -> dict[str, float]:
    """Verteilt den Mehrbedarf auf vorher / unterwegs / danach.

    Unterwegs nur ab ``DURING_FROM_MIN`` — kürzere Einheiten schafft der
    Glykogenspeicher, *wenn* vorher gegessen wurde. Unterwegs höchstens die
    Hälfte: der Rest gehört in eine richtige Mahlzeit danach.
    """
    if kcal_extra <= 0:
        return {"before": 0.0, "during": 0.0, "after": 0.0}
    before = kcal_extra * BEFORE_SHARE
    during = 0.0
    if minutes >= DURING_FROM_MIN:
        during = min(DURING_CARBS_G_PER_H * KCAL_PER_G_CARB * minutes / 60.0,
                     kcal_extra * 0.5)
    after = max(0.0, kcal_extra - before - during)
    return {"before": before, "during": during, "after": after}


PHASE_TEXT = {
    "before": ("Vorher", "30–90 min vor dem Start"),
    "during": ("Unterwegs", "ab der ersten halben Stunde, in Schlucken bzw. Stücken"),
    "after": ("Danach", "innerhalb von 1–2 h, gern mit der nächsten Mahlzeit"),
}


def _phases(parts: dict[str, float]) -> list[Phase]:
    out: list[Phase] = []
    for key in ("before", "during", "after"):
        kcal = parts.get(key, 0.0)
        if kcal <= 0:
            continue
        title, hint = PHASE_TEXT[key]
        ps = [portion(kcal, k) for k in PHASE_FOODS[key]]
        carbs = ps[0].count * FOODS[ps[0].key].carbs_g
        out.append(Phase(key, title, int(round(kcal)), int(round(carbs)), hint, ps))
    return out


def build_plan(kind: str, duration_min: int, weight_kg: float | None = None,
               power_plan: list[dict] | None = None,
               done_today_kcal: float | None = None) -> FuelPlan:
    """Rein, ohne Datenbank: Mehrbedarf + Aufteilung + Portionen."""
    weight_known = bool(weight_kg and weight_kg > 0)
    w = float(weight_kg) if weight_known else DEFAULT_WEIGHT_KG
    notes: list[str] = []

    # Schon gefahren: dann zählt, was die Fahrt wirklich gekostet hat — und
    # alles davon gehört ins „Danach".
    if kind == "REST" and done_today_kcal and done_today_kcal > 0:
        extra = float(done_today_kcal)
        parts = {"before": 0.0, "during": 0.0, "after": extra}
        plan = FuelPlan(kind, 0, int(round(extra)), _range(extra), "ride", w,
                        weight_known, _phases(parts),
                        [portion(extra, k) for k in ("cola", "maoam", "toast")],
                        [f"Deine Fahrt heute hat rund {int(round(extra))} kcal "
                         "zusätzlich gekostet — die gehören heute noch auf den Teller.",
                         BASE_MEALS_NOTE],
                        int(round(extra)))
        return plan

    if kind == "REST" or duration_min <= 0:
        return FuelPlan(kind, 0, 0, (0, 0), "none", w, weight_known, notes=[REST_NOTE])

    gross, source = gross_kcal(kind, duration_min, w, power_plan)
    extra = max(0.0, gross - rest_kcal(duration_min, w))
    parts = split(extra, duration_min)

    notes.append(BASE_MEALS_NOTE)
    notes.append(LOW_FUEL_NOTE)
    if duration_min < DURING_FROM_MIN:
        notes.append("Unter einer Stunde musst du unterwegs nichts essen — wenn "
                     "du vorher getankt hast. Eine Cola in der Trinkflasche schadet "
                     "trotzdem nicht, falls die Beine leer werden.")
    if source == "met":
        notes.append("Ohne FTP grob über typische Werte je Einheitentyp geschätzt.")
    if not weight_known:
        notes.append(f"Ohne hinterlegtes Gewicht mit {DEFAULT_WEIGHT_KG:.0f} kg gerechnet "
                     "(Einrichtung → Körpergewicht).")

    return FuelPlan(kind, int(duration_min), int(round(extra)), _range(extra), source,
                    w, weight_known, _phases(parts),
                    [portion(extra, k) for k in ("cola", "maoam", "toast")], notes)


def _range(kcal: float) -> tuple[int, int]:
    """±20 % — auf 10 kcal gerundet, damit keine Scheingenauigkeit entsteht."""
    return (int(round(kcal * 0.8 / 10) * 10), int(round(kcal * 1.2 / 10) * 10))


# ===========================================================================
# Anbindung an die Daten
# ===========================================================================

def weight_kg() -> float | None:
    cfg = config.load_config_raw()
    config._overlay_env(cfg)
    try:
        w = float(config.athlete(cfg).get("weight_kg"))
    except (TypeError, ValueError):
        return None
    return w if w > 0 else None


def ride_extra_kcal(row: Any, weight: float) -> float:
    """Mehrverbrauch einer gefahrenen Einheit (Strava-kJ, sonst MET)."""
    minutes = float(row.get("moving_time_s") or 0) / 60.0
    kj = row.get("kilojoules")
    if kj is not None and pd.notna(kj) and kj > 0:
        gross = kcal_from_kj(float(kj))
    else:
        gross = MET_UNKNOWN * weight * minutes / 60.0
    return max(0.0, gross - rest_kcal(minutes, weight))


def done_today(rides: pd.DataFrame, today: dt.date, weight: float) -> float:
    if rides.empty or "date" not in rides.columns:
        return 0.0
    todays = rides[rides["date"] == today]
    return float(sum(ride_extra_kcal(r, weight) for _, r in todays.iterrows()))


def for_recommendation(rc: Any, today: dt.date | None = None,
                       rides: pd.DataFrame | None = None) -> FuelPlan:
    """FuelPlan zur heutigen Empfehlung — gleiche Rechnung für Dashboard,
    today.json und Morgen-Report."""
    today = today or dt.date.today()
    w = weight_kg()
    done = None
    if rc.kind == "REST":
        if rides is None:
            from . import dataprep
            rides = dataprep.prep_rides()
        done = done_today(rides, today, w or DEFAULT_WEIGHT_KG) or None
    mid = int(sum(rc.duration_min) / 2) if rc.duration_min[1] else 0
    return build_plan(rc.kind, mid, w, rc.power_plan or None, done)
