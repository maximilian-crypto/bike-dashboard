"""Verschleiß-/Wartungs-Tracker für Fahrrad-Komponenten.

Zählt die gefahrenen Kilometer je Bauteil (Kette, Reifen, Kassette …) auf Basis
der kumulierten Strava-Gesamtdistanz und warnt, wenn ein Wartungsintervall
erreicht ist. Jedes Bauteil merkt sich den **Kilometerstand beim letzten
Wechsel** (``installed_km``); der Verschleiß ist die Differenz zum aktuellen
Gesamtstand.

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

# Bauteil-Vorlagen mit typischen Wechselintervallen (km). Startwerte als grobe
# Praktiker-Richtwerte – jederzeit im Dashboard anpassbar.
DEFAULT_COMPONENTS: list[dict] = [
    {"id": "chain_lube",  "name": "Kette schmieren", "icon": "🛢️", "interval_km": 250},
    {"id": "chain",       "name": "Kette",           "icon": "🔗", "interval_km": 3000},
    {"id": "cassette",    "name": "Kassette",        "icon": "⚙️", "interval_km": 9000},
    {"id": "tire_front",  "name": "Reifen vorn",     "icon": "🛞", "interval_km": 5000},
    {"id": "tire_rear",   "name": "Reifen hinten",   "icon": "🛞", "interval_km": 3500},
    {"id": "brake_pads",  "name": "Bremsbeläge",     "icon": "🛑", "interval_km": 2000},
    {"id": "cables",      "name": "Züge & Hüllen",   "icon": "🕸️", "interval_km": 6000},
    {"id": "bar_tape",    "name": "Lenkerband",      "icon": "🎀", "interval_km": 8000},
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
    wear_km: float          # seit letztem Wechsel gefahren
    remaining_km: float     # bis zur nächsten Wartung (negativ = überfällig)
    pct: float              # Verschleiß in [0, 1+] (Anteil des Intervalls)
    status: str             # ok | soon | due


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
    }


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


def status_of(comp: dict, total_km: float) -> ComponentStatus:
    """Verschleiß-Status eines Bauteils beim aktuellen Gesamtkilometerstand."""
    c = _sanitize(comp)
    interval = c["interval_km"]
    installed = min(c["installed_km"], float(total_km))
    wear = max(0.0, float(total_km) - installed)
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
    )


def statuses(state: list[dict], total_km: float) -> list[ComponentStatus]:
    """Alle Bauteile bewerten, überfälligste zuerst (höchster Verschleiß)."""
    out = [status_of(c, total_km) for c in state]
    return sorted(out, key=lambda s: s.pct, reverse=True)


def reset_component(state: list[dict], comp_id: str, total_km: float) -> list[dict]:
    """Bauteil als frisch gewechselt markieren (installed_km = aktueller Stand)."""
    new = []
    for c in state:
        c = _sanitize(c)
        if c["id"] == comp_id:
            c["installed_km"] = float(total_km)
        new.append(c)
    return new


def reset_all(state: list[dict], total_km: float) -> list[dict]:
    """Alle Bauteile ab jetzt frisch tracken."""
    return [{**_sanitize(c), "installed_km": float(total_km)} for c in state]
