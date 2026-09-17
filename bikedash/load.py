"""Trainingslast pro Einheit — auf einer **einheitlichen Skala**:

    Eine Stunde an der Schwelle = 100 Punkte.

Das ist die Definition von TSS (Coggan). Alle Lastquellen werden darauf
normiert, damit Einheiten mit und ohne Powermeter vergleichbar sind und in
dieselbe CTL/ATL/TSB-Kurve laufen:

* **Leistungsbasiert** (`power_tss`) — wenn ein echter Powermeter Daten
  liefert, also indoor auf der Rolle. Genaueste Quelle.
* **Herzfrequenzbasiert** (`hr_tss`) — Banister-TRIMP, anschließend so
  skaliert, dass eine Stunde an der Schwelle ebenfalls 100 ergibt. Entspricht
  dem, was TrainingPeaks „hrTSS" nennt.

Warum die Normierung nötig ist: rohes TRIMP läuft je nach Schwellenlage 1,4-
bis 1,8-mal „heißer" als TSS. Die Schwellen in `recommend.py`
(`TSB_DEEP_FATIGUE` & Co.) stammen aber aus der TSS-Welt (Allen/Coggan) —
angewendet auf rohes TRIMP bremsen sie deutlich früher als gemeint.

Banister-TRIMP selbst bleibt unverändert erhalten:

    TRIMP = Dauer[min] × HRR-Anteil × 0,64 × e^(k × HRR-Anteil)

mit HRR-Anteil = (Ø-HF − Ruhe) / (Max − Ruhe) und geschlechtsabhängigem k
(1,92 ♂ / 1,67 ♀). Die Exponentialgewichtung bildet ab, dass intensivere
Minuten überproportional zur Last beitragen.

Quellen: Banister 1991; Morton, Fitz-Clarke & Banister 1990 (TRIMP);
Allen & Coggan, „Training and Racing with a Power Meter" (TSS/IF).
"""

from __future__ import annotations

import math

# Geschlechtsabhängiger Exponentialfaktor der Banister-Formel.
TRIMP_K = {"m": 1.92, "f": 1.67}

# Anteil der Herzfrequenzreserve, an dem die Schwelle liegt, solange kein
# LTHR-Feldtestwert hinterlegt ist. 0,90 ist die Obergrenze von Z4 im
# Zonenmodell in `zones.py` — wir bleiben damit konsistent zum Rest des Codes.
THRESHOLD_HRR_FRAC = 0.90

# Referenzlast: eine Stunde an der Schwelle.
REFERENCE_TSS = 100.0
REFERENCE_SECONDS = 3600.0


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


def threshold_hr(max_hr: float | None, rest_hr: float | None,
                 lthr: float | None = None) -> float | None:
    """Schwellen-Herzfrequenz in bpm.

    Bevorzugt den Feldtestwert (LTHR); sonst geschätzt als Obergrenze von Z4,
    analog zu `zones.zones()`. Ohne Max-HF nicht bestimmbar.
    """
    if lthr and lthr > 0:
        return float(lthr)
    if not max_hr:
        return None
    if rest_hr and max_hr > rest_hr:
        return rest_hr + THRESHOLD_HRR_FRAC * (max_hr - rest_hr)
    return max_hr * THRESHOLD_HRR_FRAC


def hr_tss(
    duration_s: float | None,
    avg_hr: float | None,
    max_hr: float | None,
    rest_hr: float | None,
    lthr: float | None = None,
    sex: str = "m",
) -> float | None:
    """HF-basierte Last auf der TSS-Skala (1 h an der Schwelle = 100).

    Rechnet Banister-TRIMP und skaliert es mit dem TRIMP, das eine Stunde an
    der Schwelle ergäbe. Das Verhältnis der Einheiten untereinander bleibt
    damit exakt erhalten — es ändert sich nur die Maßeinheit.
    """
    trimp = banister_trimp(duration_s, avg_hr, max_hr, rest_hr, sex)
    if trimp is None:
        return None
    thr = threshold_hr(max_hr, rest_hr, lthr)
    if thr is None:
        return None
    reference = banister_trimp(REFERENCE_SECONDS, thr, max_hr, rest_hr, sex)
    if not reference:
        return None
    return trimp * REFERENCE_TSS / reference


def power_tss(duration_s: float | None, normalized_power: float | None,
              ftp: float | None) -> float | None:
    """Leistungsbasierte Last (klassisches TSS).

        TSS = Dauer[s] × NP × IF / (FTP × 3600) × 100     mit IF = NP / FTP

    ``normalized_power`` ist Stravas ``weighted_average_watts`` — das ist
    Stravas Name für die Normalized Power. Nur sinnvoll mit echten Wattdaten
    (``device_watts``), nicht mit Stravas Schätzung aus Tempo und Höhenprofil.
    """
    if not duration_s or duration_s <= 0 or not normalized_power or not ftp or ftp <= 0:
        return None
    intensity = normalized_power / ftp
    return (duration_s * normalized_power * intensity) / (ftp * REFERENCE_SECONDS) * 100.0
