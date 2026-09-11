"""Tageszeit-Empfehlung: wann heute fahren?

Der Morgen-Report soll nicht nur sagen *was* heute ansteht, sondern auch *wann*.
Dafuer wird das Stundenraster von Open-Meteo (``weather.hourly_forecast``) fuer
das erlaubte Tagesfenster bewertet und das beste zusammenhaengende Zeitfenster in
Laenge der empfohlenen Einheit gesucht.

Erlaubte Fenster (Vorgabe des Nutzers):

* Montag bis Freitag: **13:00 bis spaetestens 20:00**
* Samstag/Sonntag:    **08:00 bis spaetestens 20:00**

Das Ende ist als *Rueckkehrzeit* gemeint — die Einheit muss bis dahin durch sein.

Bewertung: jede Stunde bekommt Strafpunkte (kleiner = besser). Bewusst in zwei
Toepfe getrennt:

* ``base``  — Regen, Gewitter, Kaelte/Hitze, UV, Dunkelheit
* ``wind``  — Windgeschwindigkeit und Boeen

Grund fuer die Trennung: Sieht der ganze Tag nach gutem Wetter aus (alle
``base``-Werte unter :data:`SETTLED_DAY_MAX`), soll die Entscheidung allein am
Wind haengen — genau so formuliert es dann auch die Begruendung.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

from . import weather

# --- Erlaubte Tagesfenster (Stunde von, Stunde bis = spaeteste Rueckkehr) -----
WEEKDAY_WINDOW = (13, 20)
WEEKEND_WINDOW = (8, 20)

# Ein Tag gilt als "durchweg gut", wenn keine Kandidatenstunde mehr als so viele
# Nicht-Wind-Strafpunkte hat. ~8 Punkte entsprechen z. B. 20 % Regenrisiko oder
# 5 Grad ausserhalb des Wohlfuehlbereichs — spuerbar, aber kein Ausschluss.
SETTLED_DAY_MAX = 8.0

# Eine Alternative wird nur genannt, wenn sie nicht deutlich schlechter ist als
# das beste Fenster — sonst empfiehlt der Report ein Regenloch als "Alternative".
ALT_MAX_PENALTY = 10.0

# Wohlfuehlbereich Temperatur (gefuehlt) in Grad Celsius.
COMFORT_LOW, COMFORT_HIGH = 12.0, 24.0

# Gewitter/Eisregen sind harte Ausschlusskriterien, Schnee ein weiches.
CODE_PENALTY = {95: 60.0, 96: 70.0, 99: 80.0, 66: 45.0, 67: 45.0,
                71: 20.0, 73: 28.0, 75: 40.0, 77: 20.0, 85: 25.0, 86: 35.0}


@dataclass
class HourScore:
    hour: weather.Hour
    base: float          # Strafpunkte ohne Wind
    wind: float          # Strafpunkte aus Wind/Boeen
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.base + self.wind


@dataclass
class RideWindow:
    """Ein Zeitfenster als Empfehlung."""

    start: dt.datetime
    end: dt.datetime
    score: float
    temp_c: float
    wind_kmh: float
    gust_kmh: float
    wind_deg: float
    precip_prob: int
    code: int

    @property
    def label(self) -> str:
        return f"{self.start.hour}–{self.end.hour} Uhr"

    @property
    def icon(self) -> str:
        return weather.WMO.get(self.code, ("🌡️", "?"))[0]

    @property
    def desc(self) -> str:
        return weather.WMO.get(self.code, ("", "unbekannt"))[1]

    @property
    def wind_dir(self) -> str:
        return weather.wind_dir_label(self.wind_deg)

    @property
    def summary(self) -> str:
        return (f"{self.label} · {self.icon} {self.temp_c:.0f} °C, "
                f"Wind {self.wind_kmh:.0f} km/h aus {self.wind_dir}, "
                f"Regen {self.precip_prob} %")


@dataclass
class DayPlan:
    date: dt.date
    window_from: int
    window_to: int
    duration_h: int
    best: RideWindow | None
    alternative: RideWindow | None
    settled: bool                       # durchweg gutes Wetter -> Wind entscheidet
    reasons: list[str] = field(default_factory=list)

    @property
    def headline(self) -> str:
        if self.best is None:
            return "Kein Zeitfenster empfohlen."
        return f"Bestes Zeitfenster: {self.best.summary}"


def allowed_window(day: dt.date) -> tuple[int, int]:
    """(fruehester Start, spaeteste Rueckkehr) als volle Stunden."""
    return WEEKEND_WINDOW if day.weekday() >= 5 else WEEKDAY_WINDOW


def score_hour(h: weather.Hour) -> HourScore:
    """Strafpunkte einer Stunde — getrennt nach Wetter (base) und Wind."""
    base = 0.0
    notes: list[str] = []

    # Niederschlag: gemessene Menge wiegt schwerer als die blosse Wahrscheinlichkeit.
    if h.precip_mm > 0:
        base += min(60.0, h.precip_mm * 30.0)
        notes.append(f"{h.precip_mm:.1f} mm Regen")
    if h.precip_prob > 0:
        base += h.precip_prob * 0.18
        if h.precip_prob >= 40:
            notes.append(f"{h.precip_prob} % Regenrisiko")

    # Gewitter, Eisregen, Schnee
    if h.code in CODE_PENALTY:
        base += CODE_PENALTY[h.code]
        notes.append(h.desc)

    # Temperatur (gefuehlt) ausserhalb des Wohlfuehlbereichs
    if h.feels_c < COMFORT_LOW:
        base += (COMFORT_LOW - h.feels_c) * 1.5
        if h.feels_c < 5:
            notes.append(f"kalt ({h.feels_c:.0f} °C gefuehlt)")
    elif h.feels_c > COMFORT_HIGH:
        base += (h.feels_c - COMFORT_HIGH) * 2.0
        if h.feels_c > 28:
            notes.append(f"heiss ({h.feels_c:.0f} °C gefuehlt)")

    # UV
    if h.uv > 6:
        base += (h.uv - 6.0) * 2.0

    # Dunkelheit: fahrbar, aber deutlich unattraktiver.
    if not h.is_day:
        base += 35.0
        notes.append("dunkel")

    # Wind getrennt fuehren (siehe Modul-Docstring).
    wind = h.wind_kmh * 0.7 + max(0.0, h.gust_kmh - 25.0) * 0.8

    return HourScore(hour=h, base=round(base, 2), wind=round(wind, 2), notes=notes)


def _window_score(scores: list[HourScore], settled: bool) -> float:
    """Fenster-Bewertung: Mittel plus Zuschlag fuer die schlechteste Stunde.

    Der Zuschlag verhindert, dass ein Fenster mit einer einzigen Gewitterstunde
    durch drei schoene Stunden schoengemittelt wird. Bei durchweg gutem Wetter
    zaehlt nur noch der Wind.
    """
    vals = [s.wind for s in scores] if settled else [s.total for s in scores]
    return round(sum(vals) / len(vals) + 0.35 * max(vals), 3)


def plan_from_hours(
    hours: list[weather.Hour],
    day: dt.date,
    duration_min: int,
) -> DayPlan:
    """Kern der Empfehlung — ohne Netz, damit testbar."""
    lo, hi = allowed_window(day)
    span = hi - lo

    # Einheitsdauer auf volle Stunden aufrunden (Umziehen/Rollen inklusive),
    # mindestens 1 h, und nie laenger als das erlaubte Fenster.
    duration_h = max(1, math.ceil(max(0, duration_min) / 60)) if duration_min > 0 else 0
    reasons: list[str] = []

    if duration_h == 0:
        return DayPlan(day, lo, hi, 0, None, None, False,
                       ["Ruhetag — heute kein Zeitfenster noetig."])

    if duration_h > span:
        reasons.append(
            f"Einheit ({duration_h} h) ist laenger als das erlaubte Fenster "
            f"({lo}–{hi} Uhr) — auf {span} h gekuerzt bewertet."
        )
        duration_h = span

    today_hours = [h for h in hours if h.time.date() == day and lo <= h.time.hour < hi]
    if len(today_hours) < duration_h:
        return DayPlan(day, lo, hi, duration_h, None, None, False,
                       ["Keine Wettervorhersage fuer das Tagesfenster verfuegbar."])

    scores = [score_hour(h) for h in today_hours]
    by_hour = {s.hour.time.hour: s for s in scores}

    settled = max(s.base for s in scores) <= SETTLED_DAY_MAX
    if settled:
        reasons.append(
            "Der ganze Tag sieht gut aus (kein Regen, angenehme Temperatur) — "
            "das Fenster richtet sich daher nach dem Wind."
        )

    # Alle zusammenhaengenden Fenster der Laenge duration_h bewerten.
    candidates: list[tuple[float, int, RideWindow]] = []
    for start in range(lo, hi - duration_h + 1):
        block = [by_hour.get(start + k) for k in range(duration_h)]
        if any(b is None for b in block):
            continue
        sc = _window_score(block, settled)  # type: ignore[arg-type]
        first = block[0].hour              # type: ignore[union-attr]
        win = RideWindow(
            start=first.time,
            end=first.time + dt.timedelta(hours=duration_h),
            score=sc,
            temp_c=sum(b.hour.feels_c for b in block) / duration_h,       # type: ignore[union-attr]
            wind_kmh=sum(b.hour.wind_kmh for b in block) / duration_h,    # type: ignore[union-attr]
            gust_kmh=max(b.hour.gust_kmh for b in block),                 # type: ignore[union-attr]
            wind_deg=block[duration_h // 2].hour.wind_deg,                # type: ignore[union-attr]
            precip_prob=max(b.hour.precip_prob for b in block),           # type: ignore[union-attr]
            code=max(b.hour.code for b in block),                         # type: ignore[union-attr]
        )
        candidates.append((sc, start, win))

    if not candidates:
        return DayPlan(day, lo, hi, duration_h, None, None, settled,
                       reasons + ["Kein passendes Zeitfenster gefunden."])

    # Bei Gleichstand das fruehere Fenster — dann bleibt der Abend frei.
    candidates.sort(key=lambda c: (c[0], c[1]))
    best = candidates[0][2]

    # Alternative: bestes ueberlappungsfreies Fenster — aber nur, wenn es dem
    # besten nahekommt. Ein deutlich schlechteres Fenster als "Alternative" zu
    # verkaufen waere ein schlechter Rat.
    alt = next((w for sc, st, w in candidates[1:]
                if (st >= best.start.hour + duration_h or st + duration_h <= best.start.hour)
                and sc <= best.score + ALT_MAX_PENALTY), None)

    worst = max(candidates, key=lambda c: c[0])[0]
    if not settled:
        bad = by_hour[best.start.hour]
        reasons.append(
            f"Beste Stunden {best.label}: {best.icon} {best.desc}, "
            f"{best.precip_prob} % Regenrisiko, Wind {best.wind_kmh:.0f} km/h."
            + (f" ({', '.join(bad.notes)})" if bad.notes else "")
        )
        if worst - best.score > 15:
            reasons.append("Ausserhalb dieses Fensters wird es deutlich unangenehmer.")
    else:
        reasons.append(
            f"Schwaechster Wind im Fenster {best.label}: {best.wind_kmh:.0f} km/h "
            f"aus {best.wind_dir} (Boeen bis {best.gust_kmh:.0f})."
        )

    return DayPlan(day, lo, hi, duration_h, best, alt, settled, reasons)


def plan(cfg: dict, day: dt.date | None = None, duration_min: int = 90) -> DayPlan:
    """Tageszeit-Empfehlung inkl. Abruf der Vorhersage."""
    day = day or dt.date.today()
    hours = weather.hourly_forecast(cfg, days=2)
    return plan_from_hours(hours, day, duration_min)


def payload(p: DayPlan) -> dict[str, object]:
    """Kompakte, personenbezugsfreie Struktur fuer ``mobile/today.json``.

    Enthaelt nur Uhrzeiten und Wetterwerte — keine Koordinaten (today.json liegt
    oeffentlich auf GitHub Pages).
    """
    def win(w: RideWindow | None) -> dict[str, object] | None:
        if w is None:
            return None
        return {
            "start": w.start.strftime("%H:%M"),
            "end": w.end.strftime("%H:%M"),
            "label": w.label,
            "temp_c": round(w.temp_c, 1),
            "wind_kmh": round(w.wind_kmh, 1),
            "gust_kmh": round(w.gust_kmh, 1),
            "wind_dir": w.wind_dir,
            "precip_prob": w.precip_prob,
            "icon": w.icon,
            "desc": w.desc,
        }

    return {
        "window_from": p.window_from,
        "window_to": p.window_to,
        "duration_h": p.duration_h,
        "settled": p.settled,
        "best": win(p.best),
        "alternative": win(p.alternative),
        "reasons": p.reasons,
    }
