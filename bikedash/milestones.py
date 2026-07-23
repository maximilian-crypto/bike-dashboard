"""Distanz-Meilensteine & Orden aus der kumulierten Strava-Gesamtdistanz.

Im Stil der „Walk to Mordor"-Apps, aber mit mehr Abwechslung: Jede berühmte
Distanz (Radsport, Geografie, Sci-Fi, Fantasy, Astronomie) wird zu einem **Orden**,
sobald deine aufsummierte Fahrleistung sie überschreitet. Zwischen den benannten
Orden liegen generische **Nahziele** alle ~40 km (mit deterministischer Varianz),
damit das nächste Ziel nie zu weit weg ist.

Die Logik ist rein und deterministisch (keine DB, kein Netz) – der Aufrufer
reicht nur die Gesamtkilometer herein. So ist sie leicht testbar und lässt sich
sowohl im Dashboard als auch in ``build_today.py`` (für die Ride-PWA) nutzen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Themen der Orden – für Filter/Legende im Dashboard.
THEMES = {
    "geo": "Radsport & Geografie",
    "scifi": "Sci-Fi",
    "fantasy": "Fantasy",
    "astro": "Astronomie",
}

# Kuratierter Orden-Katalog: (km, Name, Emoji, Thema, Kurzbeschreibung).
# Werte sind bewusst „gut genug" recherchiert und teils mit ca. gekennzeichnet;
# es geht um Motivation und Augenzwinkern, nicht um Vermessungsgenauigkeit.
_CATALOG: list[tuple[float, str, str, str, str]] = [
    (0.4,      "Ein Shai-Hulud",            "🪱", "scifi",   "Die Länge eines ausgewachsenen Sandwurms von Arrakis."),
    (1.6,      "Imperialer Sternzerstörer", "🚀", "scifi",   "Kiel bis Bug eines Sternzerstörers – 1,6 km Kampfmacht."),
    (8.8,      "Höhe des Mount Everest",    "🏔️", "astro",   "So hoch ist der höchste Berg der Erde – nur eben senkrecht."),
    (42.195,   "Marathon-Distanz",          "🏃", "geo",     "Die klassischen 42,195 km von Marathon nach Athen."),
    (45.0,     "Rover Opportunity",         "🔴", "scifi",   "Die Gesamtstrecke des Mars-Rovers Opportunity."),
    (50.0,     "Länge von Rama",            "🛸", "scifi",   "Der Zylinderweltraumkörper aus Arthur C. Clarkes Rendezvous mit Rama."),
    (88.0,     "10× Mount Everest",         "⛰️", "astro",   "Zehn Everests aufeinandergestapelt."),
    (98.0,     "Nord-Ostsee-Kanal",         "🌊", "geo",     "Von Kiel-Holtenau bis Brunsbüttel."),
    (100.0,    "Metrisches Century",        "💯", "geo",     "Die ersten 100 Kilometer – ein Radsport-Klassiker."),
    (117.0,    "Hadrianswall",              "🧱", "geo",     "Roms Nordgrenze quer durch Britannien."),
    (120.0,    "Durchmesser Todesstern",    "⭐", "scifi",   "Der erste Todesstern, einmal quer (~120 km)."),
    (160.9,    "Imperiales Century",        "🇺🇸", "geo",     "160,9 km – die 100 Meilen am Stück."),
    (227.0,    "Ötztaler Radmarathon",      "🚵", "geo",     "Der legendäre Alpen-Marathon: 227 km, 5.500 Höhenmeter."),
    (257.0,    "Paris–Roubaix",             "🪨", "geo",     "Die Hölle des Nordens über das Kopfsteinpflaster."),
    (273.0,    "Uferlänge des Bodensees",   "🏞️", "geo",     "Einmal komplett um den Bodensee herum."),
    (298.0,    "Mailand–Sanremo",           "🇮🇹", "geo",     "La Primavera – der längste Klassiker im Profikalender."),
    (408.0,    "Flughöhe der ISS",          "🛰️", "astro",   "So hoch über dir kreist die Internationale Raumstation."),
    (483.0,    "Die Mauer",                 "🧊", "fantasy", "300 Meilen Eis, die den Norden von Westeros trennen."),
    (640.0,    "Deutschland (West–Ost)",    "🧭", "geo",     "Einmal quer durch die Republik in der Breite."),
    (876.0,    "Deutschland (Nord–Süd)",    "🇩🇪", "geo",     "Von List auf Sylt bis Oberstdorf im Allgäu."),
    (1200.0,   "Paris–Brest–Paris",         "🚴", "geo",     "Der Ur-Brevet: 1.200 km am Stück, seit 1891."),
    (1233.0,   "Länge des Rheins",          "🌊", "geo",     "Von den Alpen bis zur Nordsee."),
    (2172.0,   "Auenland → Schicksalsberg", "💍", "fantasy", "Frodos Weg vom Auenland bis nach Mordor (ca. 2.172 km)."),
    (2850.0,   "Länge der Donau",           "🏞️", "geo",     "Vom Schwarzwald bis ans Schwarze Meer."),
    (3500.0,   "Tour de France",            "🏆", "geo",     "Die Gesamtdistanz einer ganzen Grande Boucle."),
    (6650.0,   "Länge des Nils",            "🏜️", "astro",   "Der längste Fluss der Erde."),
    (12756.0,  "Erddurchmesser",            "🌍", "astro",   "Einmal quer durch den Planeten."),
    (21196.0,  "Chinesische Mauer",         "🐉", "geo",     "Die gesamte kartierte Länge der Großen Mauer."),
    (31415.0,  "Umfang eines Halo-Rings",   "💫", "scifi",   "Einmal rund um einen Halo (~10.000 km Durchmesser)."),
    (40075.0,  "Erdumfang am Äquator",      "🌐", "astro",   "Einmal komplett um die Erde herum."),
    (384400.0, "Erde → Mond",               "🌕", "astro",   "Die ultimative Distanz: bis zum Mond."),
]

GENERIC_STEP_KM = 40.0    # mittlerer Abstand der Nahziele
GENERIC_VARIANCE = 0.4    # ± dieser Anteil (deterministische „Zufalls"-Streuung)
_NEAR_NAMED_KM = 9.0      # Nahziele so nah an einem Orden werden unterdrückt


@dataclass(frozen=True)
class Badge:
    km: float
    name: str
    icon: str
    theme: str
    blurb: str


@dataclass
class Target:
    """Ein anstehendes Ziel (Orden oder generisches Nahziel)."""
    km: float
    label: str
    icon: str
    kind: str            # "orden" | "step"
    remaining_km: float
    progress: float      # 0..1 – Fortschritt seit dem vorigen Meilenstein
    blurb: str = ""


@dataclass
class MilestoneView:
    total_km: float
    badges_total: int
    earned: list[Badge]              # freigeschaltete Orden, jüngster zuerst
    upcoming_badges: list[Badge]     # noch offene Orden, nächster zuerst
    next_targets: list[Target]       # gemischte Nahziele (Orden + Schritte), aufsteigend
    latest: Badge | None = None      # zuletzt freigeschalteter Orden
    catalog: list[Badge] = field(default_factory=list)


def _catalog() -> list[Badge]:
    return [Badge(km, name, icon, theme, blurb)
            for km, name, icon, theme, blurb in _CATALOG]


def _jitter(i: int) -> float:
    """Deterministischer Pseudo-Zufall in [-1, 1) aus dem Index (stabil über Läufe)."""
    h = math.sin((i + 1) * 12.9898) * 43758.5453
    return (h - math.floor(h)) * 2.0 - 1.0


def generic_milestones(up_to_km: float) -> list[float]:
    """Aufsteigende, generische Meilensteine bis ``up_to_km`` (auf 5 km gerundet).

    Abstände schwanken deterministisch um ``GENERIC_STEP_KM`` (±Varianz), die
    Werte sind auf „schöne" 5-km-Schritte gerundet und streng monoton steigend.
    """
    out: list[float] = []
    cum = 0.0
    i = 0
    guard = 0
    while cum <= up_to_km and guard < 100000:
        gap = GENERIC_STEP_KM * (1.0 + GENERIC_VARIANCE * _jitter(i))
        cum += max(gap, 5.0)
        nice = round(cum / 5.0) * 5.0
        if not out or nice > out[-1]:
            out.append(nice)
        i += 1
        guard += 1
    return out


def _next_generic(total_km: float, count: int) -> list[float]:
    """Die nächsten ``count`` generischen Meilensteine oberhalb ``total_km``."""
    horizon = total_km + GENERIC_STEP_KM * (count + 2) * (1 + GENERIC_VARIANCE)
    return [m for m in generic_milestones(horizon) if m > total_km][:count]


def compute(total_km: float, *, themes: set[str] | None = None,
            n_targets: int = 3) -> MilestoneView:
    """Baut die Meilenstein-Ansicht aus der Gesamtdistanz.

    ``themes`` filtert optional die Orden (None = alle). ``n_targets`` steuert,
    wie viele kommende Nahziele (Orden + generische Schritte gemischt) geliefert
    werden.
    """
    total_km = max(0.0, float(total_km))
    catalog = _catalog()
    if themes:
        cat = [b for b in catalog if b.theme in themes]
    else:
        cat = catalog

    earned = [b for b in cat if b.km <= total_km]
    upcoming = [b for b in cat if b.km > total_km]
    earned_recent = sorted(earned, key=lambda b: b.km, reverse=True)
    upcoming_sorted = sorted(upcoming, key=lambda b: b.km)

    # „Voriger Meilenstein" = Untergrenze für die Fortschrittsbalken.
    prev_named = max((b.km for b in cat if b.km <= total_km), default=0.0)

    # Kandidaten fürs nächste Ziel: kommende Orden + generische Schritte mischen.
    named_targets = [
        Target(km=b.km, label=b.name, icon=b.icon, kind="orden",
               remaining_km=b.km - total_km, progress=0.0, blurb=b.blurb)
        for b in upcoming_sorted[:n_targets + 2]
    ]
    named_kms = [b.km for b in upcoming_sorted]
    step_targets = [
        Target(km=m, label=f"{int(round(m)):,} km".replace(",", "."),
               icon="🎯", kind="step", remaining_km=m - total_km, progress=0.0)
        for m in _next_generic(total_km, n_targets + 3)
        # generische Schritte nah an einem Orden weglassen (kein Doppel-Ziel)
        if all(abs(m - nk) > _NEAR_NAMED_KM for nk in named_kms)
    ]

    merged = sorted(named_targets + step_targets, key=lambda t: t.km)[:n_targets]
    # Fortschritt je Ziel: seit dem jeweils vorausgehenden Meilenstein.
    lower = prev_named
    for t in merged:
        span = t.km - lower
        t.progress = 0.0 if span <= 0 else max(0.0, min(1.0, (total_km - lower) / span))
        lower = t.km

    return MilestoneView(
        total_km=round(total_km, 1),
        badges_total=len(cat),
        earned=earned_recent,
        upcoming_badges=upcoming_sorted,
        next_targets=merged,
        latest=earned_recent[0] if earned_recent else None,
        catalog=catalog,
    )
