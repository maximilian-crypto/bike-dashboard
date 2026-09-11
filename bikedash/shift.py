"""Gangempfehlung (Shift) aus Puls UND Kadenz relativ zum Tagesziel.

Bisher entschied die Ride-PWA allein über die Kadenz: zu langsam treten ->
leichterer Gang, zu schnell -> schwererer Gang. Das ignoriert, *warum* an einem
Tag getreten wird. An einem Z2-Grundlagentag ist eine Kadenz von 90 zwar formal
im Zielband, bei 185 bpm ist die Einheit aber trotzdem falsch — dann muss die
Empfehlung "runter" lauten, nicht "halten". Umgekehrt gilt bei Puls unter dem
Zielband: schwererer Gang statt "alles gut".

Die Entscheidung ist eine **Matrix** aus zwei Ampeln:

* ``hr``  — Puls gegen das Zielband der Tagesempfehlung (hr_low/hr_high)
* ``cad`` — Kadenz gegen das Zielband der Tagesempfehlung (cadence_low/high)

Leitgedanke der Matrix: **der Puls sagt, wie hart gefahren wird, die Kadenz sagt,
wie es mechanisch umgesetzt wird.** Der Puls hat daher Vorrang; die Kadenz
bestimmt, *welcher* Hebel hilft (Gang wechseln oder schlicht Tempo rausnehmen).

Diese Matrix ist die einzige Quelle der Wahrheit: ``matrix_payload()`` wandert
über ``build_today.py`` in ``mobile/today.json``, die PWA schlägt dort nur noch
nach. In ``mobile/ride.html`` liegt eine Kopie als Offline-Notnagel — dass beide
identisch sind, prüft ``tests/test_shift.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Toleranz auf das Pulsband, bevor "drüber"/"drunter" gemeldet wird. Die HF
# schwankt atem- und messbedingt um ein paar Schläge; ohne Toleranz flackert die
# Kachel am Bandrand. 3 bpm ist knapp über dem typischen Gurtrauschen.
HR_TOLERANCE_BPM = 3

# Analog für die Kadenz (Kurbelsensoren runden je nach Umdrehung).
CAD_TOLERANCE_RPM = 2

# Wie lange ein neuer Zustand anliegen muss, bevor die Kachel umschaltet.
# Der Puls hinkt der Leistung ~20-30 s hinterher; ohne Verweilzeit würde die
# Empfehlung bei jedem Wellchen springen. Nur für die PWA relevant.
DWELL_SECONDS = 6

# Farben spiegeln die CSS-Variablen in mobile/ride.html.
C_EASE = "#3a9bdc"   # Belastung runter
C_HOLD = "#2ecc71"   # im Soll
C_PUSH = "#e8503a"   # Belastung hoch

STATUSES = ("below", "in", "above", "unknown")


@dataclass(frozen=True)
class Advice:
    """Eine Zelle der Matrix — fertig zum Anzeigen."""

    action: str   # grosse Zeile in der Kachel
    symbol: str   # Badge oben rechts
    color: str    # Akzentfarbe
    why: str      # Begruendung, Platzhalter {hr} {cad} {hr_low} … noch offen

    def as_dict(self) -> dict[str, str]:
        return {"action": self.action, "symbol": self.symbol, "color": self.color, "why": self.why}


# Die Matrix: (Puls-Status, Kadenz-Status) -> Empfehlung.
#
# Lesart der neun "beide bekannt"-Zellen:
#   Puls zu hoch  -> Belastung runter. Bei niedriger/passender Kadenz hilft ein
#                    leichterer Gang; bei bereits hoher Kadenz hilft kein Gang
#                    mehr, dann muss schlicht Tempo raus.
#   Puls im Ziel  -> Intensitaet stimmt, nur die Kadenz nachziehen (gleicher
#                    Krafteinsatz, anderer Gang).
#   Puls zu tief  -> Belastung hoch. Bei niedriger Kadenz zuerst schneller
#                    treten (gleicher Gang), sonst schwererer Gang.
MATRIX: dict[tuple[str, str], Advice] = {
    # --- Puls ueber dem Zielband -------------------------------------------
    ("above", "below"): Advice(
        "leichter", "⬇", C_EASE,
        "Puls {hr} > {hr_high} bei nur {cad} U/min — leichterer Gang, runder treten.",
    ),
    ("above", "in"): Advice(
        "leichter", "⬇", C_EASE,
        "Puls {hr} > {hr_high} — einen Gang leichter, Kadenz halten.",
    ),
    ("above", "above"): Advice(
        "lockerer", "⬇", C_EASE,
        "Puls {hr} > {hr_high} trotz {cad} U/min — kein Gang hilft, Tempo rausnehmen.",
    ),
    # --- Puls im Zielband ---------------------------------------------------
    ("in", "below"): Advice(
        "leichter", "⬇", C_EASE,
        "Puls passt, Kadenz {cad} < {cad_low} — leichterer Gang bei gleichem Druck.",
    ),
    ("in", "in"): Advice(
        "halten", "✓", C_HOLD,
        "Puls {hr} und Kadenz {cad} im Ziel — genau so weiterfahren.",
    ),
    ("in", "above"): Advice(
        "schwerer", "⬆", C_PUSH,
        "Puls passt, Kadenz {cad} > {cad_high} — schwererer Gang bei gleichem Druck.",
    ),
    # --- Puls unter dem Zielband -------------------------------------------
    ("below", "below"): Advice(
        "schneller treten", "⬆", C_PUSH,
        "Puls {hr} < {hr_low} und Kadenz {cad} niedrig — im gleichen Gang zulegen.",
    ),
    ("below", "in"): Advice(
        "schwerer", "⬆", C_PUSH,
        "Puls {hr} < {hr_low} — einen Gang schwerer, Kadenz halten.",
    ),
    ("below", "above"): Advice(
        "schwerer", "⬆", C_PUSH,
        "Puls {hr} < {hr_low} bei {cad} U/min — schwererer Gang bringt beides ins Ziel.",
    ),
    # --- kein Brustgurt: wie bisher rein ueber die Kadenz -------------------
    ("unknown", "below"): Advice(
        "leichter", "⬇", C_EASE,
        "Kadenz {cad} < {cad_low} — leichterer Gang. (kein Puls verbunden)",
    ),
    ("unknown", "in"): Advice(
        "halten", "✓", C_HOLD,
        "Kadenz {cad} im Ziel {cad_low}–{cad_high}. (kein Puls verbunden)",
    ),
    ("unknown", "above"): Advice(
        "schwerer", "⬆", C_PUSH,
        "Kadenz {cad} > {cad_high} — schwererer Gang. (kein Puls verbunden)",
    ),
    # --- kein Kadenzsensor: Empfehlung allein aus dem Puls ------------------
    # Damit ist die Kachel auch ohne CSC-Sensor nutzbar (bisher blieb sie leer).
    ("above", "unknown"): Advice(
        "lockerer", "⬇", C_EASE,
        "Puls {hr} > {hr_high} — leichterer Gang oder Tempo raus. (keine Kadenz)",
    ),
    ("in", "unknown"): Advice(
        "halten", "✓", C_HOLD,
        "Puls {hr} im Ziel {hr_low}–{hr_high}. (keine Kadenz)",
    ),
    ("below", "unknown"): Advice(
        "mehr geben", "⬆", C_PUSH,
        "Puls {hr} < {hr_low} — schwererer Gang oder mehr Druck. (keine Kadenz)",
    ),
    # --- gar nichts verbunden ----------------------------------------------
    ("unknown", "unknown"): Advice(
        "–", "—", "#2a3142",
        "warte auf Puls oder Kadenz",
    ),
}


def status(value: float | None, low: float | None, high: float | None,
           tol: float = 0.0) -> str:
    """Ampel eines Messwerts gegen ein Zielband (mit Toleranz an den Raendern)."""
    if value is None or low is None or high is None:
        return "unknown"
    if value < low - tol:
        return "below"
    if value > high + tol:
        return "above"
    return "in"


def advise(
    hr: float | None,
    cad: float | None,
    hr_low: int | None,
    hr_high: int | None,
    cad_low: int | None,
    cad_high: int | None,
) -> Advice:
    """Fertige Empfehlung inkl. eingesetzter Zahlen in der Begruendung."""
    hr_st = status(hr, hr_low, hr_high, HR_TOLERANCE_BPM)
    cad_st = status(cad, cad_low, cad_high, CAD_TOLERANCE_RPM)
    tpl = MATRIX[(hr_st, cad_st)]
    why = tpl.why.format(
        hr=_num(hr), cad=_num(cad),
        hr_low=_num(hr_low), hr_high=_num(hr_high),
        cad_low=_num(cad_low), cad_high=_num(cad_high),
    )
    return Advice(tpl.action, tpl.symbol, tpl.color, why)


def _num(v: float | None) -> str:
    if v is None:
        return "–"
    return str(int(round(v)))


def matrix_payload() -> dict[str, object]:
    """Matrix + Stellschrauben als JSON-taugliche Struktur fuer today.json.

    Schluessel sind ``"<puls>|<kadenz>"``, damit sie in JSON abbildbar sind.
    """
    return {
        "hr_tolerance_bpm": HR_TOLERANCE_BPM,
        "cad_tolerance_rpm": CAD_TOLERANCE_RPM,
        "dwell_seconds": DWELL_SECONDS,
        "cells": {f"{h}|{c}": a.as_dict() for (h, c), a in MATRIX.items()},
    }
