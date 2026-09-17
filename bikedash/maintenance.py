"""Verschleiß-/Wartungs-Tracker für Fahrrad-Komponenten.

Zählt die gefahrenen Kilometer je Bauteil (Kette, Reifen, Kassette …) auf Basis
der kumulierten Strava-Gesamtdistanz und warnt, wenn ein Wartungsintervall
erreicht ist. Jedes Bauteil merkt sich den **Kilometerstand beim letzten
Wechsel** (``installed_km``); der Verschleiß ist die Differenz zum aktuellen
Gesamtstand.

**Indoor-Kilometer zählen nicht wie Straßenkilometer.** Auf der Rolle ist das
Hinterrad ausgebaut, gebremst und geschaltet wird nicht, Dreck und Regen fehlen
— nur der Antrieb wird wirklich belastet. Jedes Bauteil hat deshalb einen
``indoor_factor``; der maßgebliche Kilometerstand ist
``outdoor_km + indoor_factor × indoor_km`` und damit **pro Bauteil
unterschiedlich**. ``installed_km`` wird in genau dieser Bauteil-Skala
gespeichert.

Persistenz läuft über den vorhandenen ``app_kv``-Schlüssel-Wert-Speicher
(eine JSON-Liste unter ``KV_KEY``) – nichts Neues am DB-Schema. Die Rechenlogik
ist rein und ohne DB testbar; nur ``load_state`` / ``save_state`` sprechen mit
dem Store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import store

KV_KEY = "maintenance_components"

# Anteil, zu dem ein Indoor-Kilometer wie ein Straßenkilometer zählt, wenn für
# ein Bauteil nichts Genaueres hinterlegt ist.
DEFAULT_INDOOR_FACTOR = 0.0

# Bauteil-Vorlagen mit typischen Wechselintervallen (km). Startwerte als grobe
# Praktiker-Richtwerte – jederzeit im Dashboard anpassbar.
#
# ``indoor_factor`` bezieht sich auf einen Direct-Drive-Aufbau (Hinterrad raus,
# Zwift Cog statt Kassette, virtuelles Schalten):
#   • Antrieb  – Kette läuft unter voller Last, aber sauber: anteilig
#   • Kassette – der Cog ersetzt sie, die Kassette des Rads ist gar nicht im
#                Eingriff: 0
#   • Reifen   – Hinterrad ausgebaut, Vorderrad steht still: 0
#   • Bremsen / Züge – auf der Rolle wird weder gebremst noch geschaltet: 0
#   • Lenkerband – km sind nicht der Treiber, aber Schweiß greift es an
DEFAULT_COMPONENTS: list[dict] = [
    {"id": "chain_lube",  "name": "Kette schmieren", "icon": "🛢️", "interval_km": 250,
     "indoor_factor": 0.7},
    {"id": "chain",       "name": "Kette",           "icon": "🔗", "interval_km": 3000,
     "indoor_factor": 0.6},
    {"id": "cassette",    "name": "Kassette",        "icon": "⚙️", "interval_km": 9000,
     "indoor_factor": 0.0},
    {"id": "tire_front",  "name": "Reifen vorn",     "icon": "🛞", "interval_km": 5000,
     "indoor_factor": 0.0},
    {"id": "tire_rear",   "name": "Reifen hinten",   "icon": "🛞", "interval_km": 3500,
     "indoor_factor": 0.0},
    {"id": "brake_pads",  "name": "Bremsbeläge",     "icon": "🛑", "interval_km": 2000,
     "indoor_factor": 0.0},
    {"id": "cables",      "name": "Züge & Hüllen",   "icon": "🕸️", "interval_km": 6000,
     "indoor_factor": 0.0},
    {"id": "bar_tape",    "name": "Lenkerband",      "icon": "🎀", "interval_km": 8000,
     "indoor_factor": 0.3},
]

# Ampel-Schwellen als Anteil des Intervalls.
WARN_FRAC = 0.8    # ab hier „bald fällig"

STATUS_OK = "ok"
STATUS_SOON = "soon"
STATUS_DUE = "due"


@dataclass
class ComponentStatus:
    id: str
    name: str
    icon: str
    interval_km: float
    installed_km: float
    wear_km: float          # seit letztem Wechsel gefahren (bauteil-gewichtet)
    remaining_km: float     # bis zur nächsten Wartung (negativ = überfällig)
    pct: float              # Verschleiß in [0, 1+] (Anteil des Intervalls)
    status: str             # ok | soon | due
    indoor_factor: float    # wie stark Indoor-km zählen (0 = gar nicht)
    odo_km: float           # maßgeblicher Kilometerstand in der Bauteil-Skala
    indoor_km_counted: float  # davon aus Indoor-Fahrten angerechnet


def default_state() -> list[dict]:
    """Frischer Zustand: alle Vorlagen mit Kilometerstand 0 beim Einbau."""
    return [{**c, "installed_km": 0.0} for c in DEFAULT_COMPONENTS]


def _sanitize(comp: dict) -> dict:
    return {
        "id": str(comp.get("id") or comp.get("name", "part")),
        "name": str(comp.get("name", "Bauteil")),
        "icon": str(comp.get("icon", "🔧")),
        "interval_km": max(1.0, float(comp.get("interval_km", 1000) or 1000)),
        "installed_km": max(0.0, float(comp.get("installed_km", 0.0) or 0.0)),
        "indoor_factor": min(max(float(
            comp.get("indoor_factor", DEFAULT_INDOOR_FACTOR)
            if comp.get("indoor_factor") is not None else DEFAULT_INDOOR_FACTOR
        ), 0.0), 1.0),
    }


def odometer(comp: dict, outdoor_km: float, indoor_km: float = 0.0) -> float:
    """Maßgeblicher Kilometerstand für dieses Bauteil.

    Straßenkilometer zählen voll, Rollenkilometer nur zum ``indoor_factor``.
    """
    c = _sanitize(comp)
    return float(outdoor_km) + c["indoor_factor"] * float(indoor_km)


def load_state() -> list[dict]:
    """Bauteil-Liste aus dem Store; fällt auf die Vorlagen zurück."""
    raw = store.get_kv(KV_KEY)
    if not raw:
        return default_state()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return default_state()
    if not isinstance(data, list) or not data:
        return default_state()
    return [_sanitize(c) for c in data if isinstance(c, dict)]


def save_state(state: list[dict]) -> None:
    store.set_kv(KV_KEY, json.dumps([_sanitize(c) for c in state], ensure_ascii=False))


def status_of(comp: dict, outdoor_km: float,
              indoor_km: float = 0.0) -> ComponentStatus:
    """Verschleiß-Status eines Bauteils beim aktuellen Kilometerstand.

    ``outdoor_km`` sind Straßenkilometer, ``indoor_km`` Rollenkilometer; wie
    stark letztere zählen, bestimmt der ``indoor_factor`` des Bauteils.
    """
    c = _sanitize(comp)
    interval = c["interval_km"]
    odo = odometer(c, outdoor_km, indoor_km)
    installed = min(c["installed_km"], odo)
    wear = max(0.0, odo - installed)
    remaining = interval - wear
    pct = wear / interval if interval > 0 else 0.0
    if pct >= 1.0:
        status = STATUS_DUE
    elif pct >= WARN_FRAC:
        status = STATUS_SOON
    else:
        status = STATUS_OK
    return ComponentStatus(
        id=c["id"], name=c["name"], icon=c["icon"], interval_km=interval,
        installed_km=installed, wear_km=round(wear, 1),
        remaining_km=round(remaining, 1), pct=pct, status=status,
        indoor_factor=c["indoor_factor"], odo_km=round(odo, 1),
        indoor_km_counted=round(c["indoor_factor"] * float(indoor_km), 1),
    )


def statuses(state: list[dict], outdoor_km: float,
             indoor_km: float = 0.0) -> list[ComponentStatus]:
    """Alle Bauteile bewerten, überfälligste zuerst (höchster Verschleiß)."""
    out = [status_of(c, outdoor_km, indoor_km) for c in state]
    return sorted(out, key=lambda s: s.pct, reverse=True)


def reset_component(state: list[dict], comp_id: str, outdoor_km: float,
                    indoor_km: float = 0.0) -> list[dict]:
    """Bauteil als frisch gewechselt markieren (installed_km = aktueller Stand).

    Der gespeicherte Stand ist der **bauteil-eigene** Kilometerstand, damit der
    Verschleiß danach wieder bei null beginnt.
    """
    new = []
    for c in state:
        c = _sanitize(c)
        if c["id"] == comp_id:
            c["installed_km"] = odometer(c, outdoor_km, indoor_km)
        new.append(c)
    return new


def reset_all(state: list[dict], outdoor_km: float,
              indoor_km: float = 0.0) -> list[dict]:
    """Alle Bauteile ab jetzt frisch tracken."""
    return [
        {**_sanitize(c), "installed_km": odometer(c, outdoor_km, indoor_km)}
        for c in state
    ]
