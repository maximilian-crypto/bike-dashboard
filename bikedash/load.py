"""Trainingslast pro Einheit als **Banister-TRIMP** — HF-basiert, deterministisch,
selbst nachrechenbar (im Gegensatz zu Stravas Blackbox-„Relative Effort").

    TRIMP = Dauer[min] × HRR-Anteil × 0,64 × e^(k × HRR-Anteil)

mit HRR-Anteil = (Ø-HF − Ruhe) / (Max − Ruhe) und geschlechtsabhängigem k
(1,92 ♂ / 1,67 ♀). Die Exponentialgewichtung bildet ab, dass intensivere
Minuten überproportional zur Last beitragen — genau das, was ein simpler
Dauer×HF-Mittelwert verschluckt.

Quelle: Banister 1991; Morton, Fitz-Clarke & Banister 1990. Diese Last ist der
Baustein, auf dem das Form-Modell (`form.py`, CTL/ATL/TSB) und die
„harte-Einheit"-Erkennung in `recommend.py` sauber aufsetzen können.
"""

from __future__ import annotations

import math

# Geschlechtsabhängiger Exponentialfaktor der Banister-Formel.
TRIMP_K = {"m": 1.92, "f": 1.67}


def hrr_fraction(avg_hr: float, max_hr: float, rest_hr: float) -> float | None:
    """HRR-Anteil (Karvonen) einer mittleren HF, auf [0, 1] geklemmt."""
    if not avg_hr or not max_hr or not rest_hr or max_hr <= rest_hr:
        return None
    return min(max((avg_hr - rest_hr) / (max_hr - rest_hr), 0.0), 1.0)


def banister_trimp(
    duration_s: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    rest_hr: float | None,
    sex: str = "m",
) -> float | None:
    """Banister-TRIMP einer Einheit. Gibt None zurück, wenn HF/Dauer fehlen
    (dann muss der Aufrufer auf einen Ersatz zurückfallen)."""
    if not duration_s or duration_s <= 0:
        return None
    frac = hrr_fraction(avg_hr or 0.0, max_hr or 0.0, rest_hr or 0.0)
    if frac is None:
        return None
    k = TRIMP_K.get(sex, TRIMP_K["m"])
    minutes = duration_s / 60.0
    return minutes * frac * 0.64 * math.exp(k * frac)
