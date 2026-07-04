"""HF-Zonen nach Whoops Modell — Karvonen / Herzfrequenzreserve (HRR).

Whoop berechnet die Zonen NICHT aus reinem %-der-Max-HF, sondern über die
Herzfrequenzreserve (Karvonen):

    Ziel-HF = Ruhepuls + Intensität × (Max-HF − Ruhepuls)

Das berücksichtigt den individuellen Ruhepuls und liefert deutlich höhere,
realistischere Zonen als das %max-Modell. Whoop aktualisiert die Zonen zudem
monatlich anhand des Ruhepulses. Max-HF holen wir aus Whoop (aus ~1 Jahr Daten),
den Ruhepuls aus den Recovery-Daten. Fehlt der Ruhepuls, fällt die Berechnung
auf %-der-Max-HF zurück.

Quelle: WHOOP – "Why WHOOP Uses Heart Rate Reserve (HRR)".
"""

from __future__ import annotations

from dataclasses import dataclass

from . import store

# Whoop-Zonengrenzen als Anteil der Herzfrequenzreserve (HRR).
ZONE_BOUNDS = [
    (1, "Z1 · Erholung", 0.40, 0.60),
    (2, "Z2 · Grundlage", 0.60, 0.70),
    (3, "Z3 · Tempo", 0.70, 0.80),
    (4, "Z4 · Schwelle", 0.80, 0.90),
    (5, "Z5 · Maximal", 0.90, 1.00),
]


@dataclass
class Zone:
    number: int
    label: str
    low_bpm: int
    high_bpm: int


def max_hr_from_data() -> int | None:
    """Max-HF: bevorzugt Whoop-Wert, sonst höchste gemessene HF aus Strava."""
    whoop_max = store.get_state("whoop_max_hr")
    if whoop_max:
        try:
            return int(round(float(whoop_max)))
        except ValueError:
            pass
    df = store.read_table("strava_activities")
    if not df.empty and df["max_heartrate"].notna().any():
        return int(round(df["max_heartrate"].max()))
    return None


def resting_hr_baseline() -> int | None:
    """Median-Ruhepuls der letzten ~30 Whoop-Recovery-Tage."""
    df = store.read_table("whoop_recovery")
    if df.empty or df["resting_heart_rate"].notna().sum() == 0:
        return None
    vals = df.dropna(subset=["resting_heart_rate"]).tail(30)["resting_heart_rate"]
    return int(round(vals.median()))


def _bpm(frac: float, max_hr: int, rest_hr: int | None) -> int:
    if rest_hr and max_hr > rest_hr:
        return int(round(rest_hr + frac * (max_hr - rest_hr)))
    return int(round(max_hr * frac))


def zones(max_hr: int, rest_hr: int | None = None) -> list[Zone]:
    """5 HF-Zonen. Mit Ruhepuls → Karvonen/HRR, sonst → %max-HF."""
    return [
        Zone(num, label, _bpm(lo, max_hr, rest_hr), _bpm(hi, max_hr, rest_hr))
        for num, label, lo, hi in ZONE_BOUNDS
    ]


def zone_for(num: int, max_hr: int, rest_hr: int | None = None) -> Zone:
    return zones(max_hr, rest_hr)[num - 1]


def intensity_frac(hr: float, max_hr: int, rest_hr: int | None = None) -> float:
    """Relative Intensität einer HF: HRR-Anteil (mit Ruhepuls) bzw. %max."""
    if rest_hr and max_hr > rest_hr:
        return (hr - rest_hr) / (max_hr - rest_hr)
    return hr / max_hr if max_hr else 0.0


def method_label(rest_hr: int | None = None) -> str:
    return "Karvonen/HRR" if rest_hr else "%max-HF"


def source_note() -> str:
    src = "Whoop (Jahresdaten)" if store.get_state("whoop_max_hr") else "geschätzt aus Strava"
    rest = resting_hr_baseline()
    method = "Karvonen/HRR" if rest else "%max"
    return f"{src} · {method}"
