"""Leistungszonen und ausführbare Einheiten-Struktur (Watt statt Herzfrequenz).

Warum das neben `zones.py` (Herzfrequenz) existiert: **drinnen ist Watt die
richtige Währung.** Die Herzfrequenz hinkt dem Reiz ein bis zwei Minuten
hinterher, driftet über die Einheit mit der Hitze nach oben und macht kurze
Intervalle praktisch unsteuerbar. Ein Smart-Trainer misst die Leistung sofort
und exakt — draußen ohne Powermeter bleibt die Herzfrequenz das Mittel der Wahl,
drinnen nicht.

Zonen nach Anteil der FTP (Allen & Coggan). Die Untergrenze von Z1 ist bewusst
**nicht** 0: als *Klassifizierung* ist „alles unter 55 %" korrekt, als
*Vorgabe* wäre „fahre 0 bis 94 Watt" unbrauchbar. Deshalb ist Z1 hier auf ein
sinnvoll fahrbares Band eingeengt.

Die Struktur (`structure()`) übersetzt eine Tagesempfehlung in Blöcke, die man
auf der Rolle direkt abfahren kann — Einfahren, Hauptteil bzw. Intervalle,
Ausfahren. Damit braucht es keinen Workout-Import: die Vorgabe ist so konkret,
dass sie sich in jedem freien Ritt umsetzen lässt.
"""

from __future__ import annotations

from dataclasses import dataclass

# (Nummer, Bezeichnung, Anteil FTP von, bis) — Z1 als fahrbares Band, s. o.
POWER_ZONE_BOUNDS: list[tuple[int, str, float, float]] = [
    (1, "Z1 · Erholung", 0.45, 0.55),
    (2, "Z2 · Grundlage", 0.56, 0.75),
    (3, "Z3 · Tempo", 0.76, 0.90),
    (4, "Z4 · Schwelle", 0.91, 1.05),
    (5, "Z5 · VO2max", 1.06, 1.20),
]

# Intervall-Bauplan je Einheitentyp: (Dauer Intervall, Dauer Pause, Zielzone,
# Pausenzone). None = durchgehende Dauereinheit in der Zielzone.
INTERVALS: dict[str, tuple[int, int, int, int] | None] = {
    "RECOVERY": None,
    "ENDURANCE": None,
    "TEMPO": (12, 5, 3, 1),
    "THRESHOLD": (8, 4, 4, 1),
}

# Ein- und Ausfahren je Einheitentyp (Minuten).
WARMUP_MIN = {"RECOVERY": 5, "ENDURANCE": 10, "TEMPO": 12, "THRESHOLD": 15}
COOLDOWN_MIN = {"RECOVERY": 5, "ENDURANCE": 8, "TEMPO": 10, "THRESHOLD": 10}

MIN_REPS = 2


@dataclass
class PowerZone:
    number: int
    label: str
    low_w: int
    high_w: int


@dataclass
class Block:
    """Ein abfahrbarer Abschnitt der Einheit."""
    label: str
    minutes: int
    low_w: int
    high_w: int
    zone: int
    cadence: str | None = None


def zones(ftp: float | None) -> list[PowerZone]:
    """Die fünf Leistungszonen in Watt. Ohne FTP gibt es nichts zu rechnen."""
    if not ftp or ftp <= 0:
        return []
    return [
        PowerZone(num, label, int(round(lo * ftp)), int(round(hi * ftp)))
        for num, label, lo, hi in POWER_ZONE_BOUNDS
    ]


def zone_for(number: int | None, ftp: float | None) -> PowerZone | None:
    if not number or not (1 <= number <= len(POWER_ZONE_BOUNDS)):
        return None
    zs = zones(ftp)
    return zs[number - 1] if zs else None


def structure(kind: str, duration_min: int, ftp: float | None,
              cadence: str | None = None) -> list[Block]:
    """Tagesempfehlung als abfahrbare Blöcke.

    Die Intervallzahl ergibt sich aus der verfügbaren Hauptzeit, nicht aus einer
    festen Vorgabe — so passt die Einheit zum Wochenziel des Saisonplans, statt
    es zu sprengen. Reicht die Zeit nicht für `MIN_REPS` Intervalle, wird daraus
    eine Dauereinheit in derselben Zone: lieber ein sauberer Dauerreiz als zwei
    abgehackte Intervalle.
    """
    if not ftp or ftp <= 0 or duration_min <= 0 or kind not in INTERVALS:
        return []

    warm, cool = WARMUP_MIN[kind], COOLDOWN_MIN[kind]
    plan = INTERVALS[kind]
    z1 = zone_for(1, ftp)
    assert z1 is not None  # ftp > 0 ist oben geprüft

    # Bei sehr kurzen Einheiten Ein-/Ausfahren anteilig kürzen, nie ganz weg.
    if warm + cool >= duration_min:
        warm = max(3, int(duration_min * 0.25))
        cool = max(3, int(duration_min * 0.2))
    main_min = max(0, duration_min - warm - cool)

    blocks = [Block("Einfahren", warm, z1.low_w, z1.high_w, 1, cadence)]

    if plan and main_min > 0:
        work_min, rest_min, work_zone, rest_zone = plan
        reps = int((main_min + rest_min) // (work_min + rest_min))
        if reps >= MIN_REPS:
            wz = zone_for(work_zone, ftp)
            rz = zone_for(rest_zone, ftp)
            assert wz is not None and rz is not None
            for i in range(reps):
                blocks.append(Block(f"Intervall {i + 1}/{reps}", work_min,
                                    wz.low_w, wz.high_w, work_zone, cadence))
                if i < reps - 1:
                    blocks.append(Block("Pause", rest_min,
                                        rz.low_w, rz.high_w, rest_zone, None))
        else:
            plan = None   # zu wenig Zeit → Dauereinheit, siehe Docstring

    if not plan and main_min > 0:
        zone_num = {"RECOVERY": 1, "ENDURANCE": 2, "TEMPO": 3, "THRESHOLD": 4}[kind]
        mz = zone_for(zone_num, ftp)
        assert mz is not None
        blocks.append(Block("Hauptteil", main_min, mz.low_w, mz.high_w,
                            zone_num, cadence))

    blocks.append(Block("Ausfahren", cool, z1.low_w, z1.high_w, 1, None))
    return blocks


def total_minutes(blocks: list[Block]) -> int:
    return sum(b.minutes for b in blocks)


def describe(blocks: list[Block]) -> str:
    """Einzeiler fürs Handy: „12' ein · 4×8' @ 155–179 W · 10' aus"."""
    if not blocks:
        return ""
    parts: list[str] = []
    work = [b for b in blocks if b.label.startswith("Intervall")]
    if work:
        b = work[0]
        parts.append(f"{blocks[0].minutes}' ein")
        parts.append(f"{len(work)}×{b.minutes}' @ {b.low_w}–{b.high_w} W")
        parts.append(f"{blocks[-1].minutes}' aus")
    else:
        main = next((b for b in blocks if b.label == "Hauptteil"), None)
        if main:
            parts.append(f"{blocks[0].minutes}' ein")
            parts.append(f"{main.minutes}' @ {main.low_w}–{main.high_w} W")
            parts.append(f"{blocks[-1].minutes}' aus")
    return " · ".join(parts)
