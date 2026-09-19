"""Fitness-Index: ein Fortschrittswert, der auf Physiologie beruht — nicht auf
abgehakten Einheiten.

Warum überhaupt ein weiterer Wert, wo es CTL doch schon gibt? CTL misst, **wie
viel** du trainierst. Es steigt auch dann, wenn du dieselbe Runde ewig gleich
schnell mit demselben Puls fährst. Was es nicht beantwortet: *Bist du besser
geworden?* Genau das misst dieses Modul — aus fünf Signalen, die unabhängig
voneinander erhoben werden und sich gegenseitig stützen:

============  =======  =====================================================
Teilwert      Gewicht  Was er misst
============  =======  =====================================================
Effizienz         30   Leistung je Herzschlag (Efficiency Factor, Friel).
                       Steigt er, holst du bei gleichem Puls mehr Vortrieb
                       heraus — der direkteste Beleg aerober Anpassung.
Kapazität         25   Chronische Trainingslast (CTL). Wie viel Reiz dein
                       Körper dauerhaft verträgt.
Ermüdungs-        20   Aerobic Decoupling (Pw:HR): driftet dein Puls in der
resistenz              zweiten Hälfte einer Fahrt vom Tempo weg? Unter 5 %
                       gilt als gut aerob konditioniert.
Regeneration      15   HRV- und Ruhepuls-Basislinie aus Whoop. Wächst die
                       HRV und sinkt der Ruhepuls, arbeitet dein autonomes
                       Nervensystem ökonomischer.
Konsistenz        10   Wie lückenlos du über zwölf Wochen trainierst.
                       Anpassung entsteht aus Wiederholung, nicht aus
                       Einzelleistungen.
============  =======  =====================================================

Getroffene Entscheidungen
-------------------------
1. **Verankert statt gleitend.** Jeder Teilwert wird gegen ein einmalig
   festgehaltenes *Ausgangsniveau* gerechnet (`app_kv: fitness_anchor`, aus den
   ersten acht Wochen verwertbarer Daten). Ein gleitender Median als Bezug
   würde bedeuten: wer sich verbessert, verschiebt seinen eigenen Maßstab mit —
   der Index klebte für immer bei 50. Mit festem Anker zeigt er echten
   Fortschritt über Monate. Dieselbe Überlegung wie beim Plananker in
   `season.py`.
2. **50 Punkte = dein Ausgangsniveau**, 90 Punkte = eine volle Skalenstufe
   besser (z. B. +15 % Effizienz). Die Abbildung ist ein Tangens hyperbolicus:
   sie sättigt, damit ein einzelner Ausreißer den Index nicht sprengt, und sie
   ist symmetrisch — Rückschritt wird genauso sichtbar wie Fortschritt.
3. **Fenster statt Einzelwerte.** Jeder Teilwert ist der Median eines 42-Tage-
   Fensters (die CTL-Zeitkonstante). Eine einzelne Fahrt verschiebt den Index
   deshalb um Bruchteile eines Punkts — genau das unterscheidet ihn von einem
   „+1 pro Workout"-Zähler. Eine abgebrochene Einheit kostet nichts; erst eine
   abgebrochene *Woche* ist sichtbar.
4. **Fehlende Signale kosten keine Punkte.** Wer kein Whoop trägt oder noch
   keine Streams ausgewertet hat, bekommt den Index aus den verfügbaren
   Teilwerten; die Gewichte werden auf die vorhandenen normiert. Ein fehlender
   Wert darf nie wie ein schlechter Wert aussehen.
5. **Effizienz getrennt nach Quelle.** Drinnen echte Watt je Herzschlag,
   draußen geschätzte Watt je Herzschlag (Physikmodell aus Tempo, Steigung und
   Masse). Die beiden Zahlen sind *nicht* vergleichbar — deshalb wird jede
   gegen ihren eigenen Anker in eine relative Änderung umgerechnet und erst
   danach gemittelt.

Quellen: Joe Friel („Efficiency Factor", „Aerobic Decoupling"); Allen & Coggan
(CTL/TSS); Martin et al. 1998 (Leistungsmodell Rad); Buchheit 2014 (HRV als
Trainingsmarker).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config, dataprep, form, store, strava, zones

KV_ANCHOR = "fitness_anchor"

# --- Fenster ---------------------------------------------------------------
WINDOW_DAYS = 42          # Bewertungsfenster (= CTL-Zeitkonstante)
LONG_WINDOW_DAYS = 90     # für rauschende Größen (Decoupling)
ANCHOR_DAYS = 56          # Ausgangsniveau aus den ersten acht Wochen
CONSISTENCY_WEEKS = 12
HISTORY_DAYS = 420        # Verlaufskurve: gut ein Jahr

# Ein Anker wird erst festgeschrieben, wenn er auf etwas steht.
ANCHOR_MIN_DAYS = 21
ANCHOR_MIN_RIDES = 5

# --- Auswahl verwertbarer Fahrten -----------------------------------------
# Effizienz ist nur im aeroben Bereich aussagekräftig: ein 12-Minuten-Sprint
# hat einen grandiosen Watt-pro-Schlag-Wert und sagt über Grundlagenausdauer
# nichts. Ebenso brauchen wir genug Dauer, damit sich der Puls eingependelt hat.
MIN_MINUTES = 30
HRR_LOW, HRR_HIGH = 0.45, 0.88      # Intensitätsfenster (Herzfrequenzreserve)

# --- Skalen: wie viel Verbesserung sind 90 Punkte? -------------------------
# Absichtlich so weit gespannt, dass eine *sehr* gute Saison bei ~85 landet und
# nicht bei 99. Ein Index, der nach zwölf Monaten am Anschlag klebt, kann im
# zweiten Jahr keinen Fortschritt mehr zeigen — und genau dann wird es
# interessant. Die Skalen sind auf einen aufbauenden Fahrer geeicht; wer schon
# austrainiert ist, bewegt sie naturgemäß langsamer (das ist keine Panne,
# sondern die Aussage).
#
# Zur Größenordnung bei der Effizienz: Luftwiderstand wächst mit v³. Wer 14 %
# schneller fährt, braucht rund 35 % mehr Leistung — Effizienzgewinne fallen in
# Watt deshalb viel größer aus als in km/h.
FULL_EFF = 0.40      # +40 % Leistung je Herzschlag
FULL_CAP = 1.50      # zweieinhalbfache chronische Trainingslast
FULL_HRV = 0.35      # +35 % HRV-Basislinie
FULL_RHR = 0.12      # −12 % Ruhepuls
# Decoupling wird absolut bewertet (Literaturwerte), nicht gegen den Anker:
DEC_MID, DEC_SPAN = 10.0, 8.0       # 10 % -> 50 Punkte, 2 % -> ~90 Punkte

WEIGHTS = {"eff": 30.0, "cap": 25.0, "dur": 20.0, "reg": 15.0, "kon": 10.0}

LABELS = {
    "eff": "Effizienz",
    "cap": "Kapazität",
    "dur": "Ermüdungsresistenz",
    "reg": "Regeneration",
    "kon": "Konsistenz",
}

# Stufen: 50 ist per Konstruktion das eigene Ausgangsniveau, deshalb sind die
# Namen Fortschrittsstufen und keine Werturteile über den Athleten.
TIERS = [
    (40.0, "Wiedereinstieg"),
    (55.0, "Grundlage"),
    (70.0, "Im Aufbau"),
    (82.0, "Formstark"),
    (92.0, "Topform"),
    (999.0, "Bestform"),
]

# --- Physikmodell für geschätzte Außen-Watt --------------------------------
# P = Steigleistung + Rollwiderstand + Luftwiderstand. Ohne Wind (der steckt im
# Rauschen) und ohne Beschleunigung — für einen *Trend gegen sich selbst* reicht
# das, weil alle Konstanten über die Zeit gleich bleiben.
G = 9.81
CRR = 0.005          # Rollwiderstandsbeiwert, Straßenreifen auf Asphalt
CDA = 0.32           # effektive Stirnfläche m², Hobbyfahrer am Oberlenker
RHO = 1.225          # Luftdichte kg/m³ auf Meereshöhe
DRIVETRAIN = 0.97    # Antriebsstrangwirkungsgrad
DEFAULT_MASS_KG = 88.0   # Fahrer + Rad, wenn kein Gewicht hinterlegt ist
BIKE_KG = 10.0


# ===========================================================================
# Reine Rechenbausteine
# ===========================================================================

def total_mass_kg(weight_kg: float | None = None) -> float:
    """Systemmasse (Fahrer + Rad) für das Leistungsmodell."""
    if weight_kg and weight_kg > 0:
        return float(weight_kg) + BIKE_KG
    return DEFAULT_MASS_KG


def estimate_power(distance_km: float | None, moving_s: float | None,
                   elev_m: float | None, mass_kg: float = DEFAULT_MASS_KG) -> float | None:
    """Geschätzte mittlere Leistung einer Außenfahrt in Watt.

    Aus Durchschnittstempo, Gesamtanstieg und Masse. Der Wert ist *nicht*
    genau genug, um FTP daraus abzuleiten — aber er ist konsistent, und genau
    darauf kommt es beim Vergleich mit dir selbst an.
    """
    if not distance_km or not moving_s or moving_s <= 0 or distance_km <= 0:
        return None
    v = (distance_km * 1000.0) / moving_s                  # m/s
    if v <= 0.5:
        return None
    climb = max(float(elev_m or 0.0), 0.0)
    p_climb = mass_kg * G * climb / moving_s               # Steigleistung
    p_roll = CRR * mass_kg * G * v                         # Rollwiderstand
    p_air = 0.5 * RHO * CDA * v ** 3                       # Luftwiderstand
    return (p_climb + p_roll + p_air) / DRIVETRAIN


def efficiency_factor(power_w: float | None, avg_hr: float | None,
                      rest_hr: float | None = None) -> float | None:
    """Leistung je Herzschlag über dem Ruhepuls.

    Friels Efficiency Factor teilt schlicht durch die Herzfrequenz. Wir ziehen
    zusätzlich den Ruhepuls ab, wo er bekannt ist: die ~50 Schläge, die auch im
    Sessel laufen, tragen nichts zum Vortrieb bei, verwässern den Quotienten
    aber kräftig und dämpfen jede echte Veränderung.
    """
    if not power_w or not avg_hr or avg_hr <= 0:
        return None
    base = avg_hr - rest_hr if rest_hr and avg_hr > rest_hr + 10 else avg_hr
    if base <= 0:
        return None
    return power_w / base


def points(rel: float | None, full_scale: float) -> float | None:
    """Relative Änderung -> Punkte. 0 % = 50, volle Skala = 90, symmetrisch.

    Der Tangens hyperbolicus sättigt: doppelte Verbesserung gibt nicht doppelt
    Punkte, und ein einzelner Ausreißer kann den Index nicht sprengen.
    """
    if rel is None or not full_scale:
        return None
    return float(np.clip(50.0 + 50.0 * math.tanh(1.1 * rel / full_scale), 0.0, 100.0))


def points_from_decoupling(dec: float | None) -> float | None:
    """Decoupling (%) -> Punkte. Absolut bewertet: 10 % = 50, 2 % = ~90.

    Hier ist der Anker unnötig, weil die Skala physiologisch bedeutungstragend
    ist — unter 5 % gilt als gut aerob konditioniert (Friel), egal wo du
    gestartet bist.
    """
    if dec is None:
        return None
    return float(np.clip(50.0 + 50.0 * math.tanh(1.1 * (DEC_MID - dec) / DEC_SPAN), 0.0, 100.0))


def tier(score: float | None) -> str:
    if score is None:
        return "—"
    for bound, name in TIERS:
        if score < bound:
            return name
    return TIERS[-1][1]


def decoupling_from_streams(time_s: list, hr: list, output: list) -> dict | None:
    """Aerobic Decoupling einer Fahrt in Prozent.

    ``output`` ist der Vortrieb — Watt, wo vorhanden, sonst Geschwindigkeit.
    Die Fahrt wird nach *Bewegungszeit* halbiert, je Hälfte Leistung/Puls
    gebildet und verglichen:

        Decoupling = (EF erste Hälfte − EF zweite Hälfte) / EF erste Hälfte

    Ein positiver Wert heißt: gegen Ende kostet dasselbe Tempo mehr Puls — der
    klassische Ermüdungsdrift. Unter 5 % gilt als gut aerob konditioniert.
    Werte über 0 sind der Normalfall; negative bedeuten, dass du dich
    eingefahren hast (oder zu Beginn zu hart angegangen bist).
    """
    if not time_s or not hr or not output:
        return None
    n = min(len(time_s), len(hr), len(output))
    if n < 120:                       # unter ~10 Minuten sinnlos
        return None
    t = np.asarray(time_s[:n], dtype=float)
    h = np.asarray([np.nan if v is None else v for v in hr[:n]], dtype=float)
    o = np.asarray([np.nan if v is None else v for v in output[:n]], dtype=float)

    # Rollpausen raus: sie verzerren beide Hälften unterschiedlich stark.
    live = np.isfinite(h) & np.isfinite(o) & (h > 60) & (o > 0)
    if live.sum() < 120:
        return None
    t, h, o = t[live], h[live], o[live]
    half = len(t) // 2
    if half < 60:
        return None
    ef1 = float(np.mean(o[:half]) / np.mean(h[:half]))
    ef2 = float(np.mean(o[half:]) / np.mean(h[half:]))
    if ef1 <= 0:
        return None
    return {
        "decoupling": round((ef1 - ef2) / ef1 * 100.0, 2),
        "ef_first": round(ef1, 4),
        "ef_second": round(ef2, 4),
        "hr_drift": round(float(np.mean(h[half:]) - np.mean(h[:half])), 1),
        "n_points": int(len(t)),
    }


def hr_recovery_60(time_s: list, hr: list) -> float | None:
    """Größter Pulsabfall innerhalb von 60 Sekunden während der Fahrt.

    Wie schnell der Puls nach einer Belastungsspitze zurückkommt, ist ein
    etablierter Marker der parasympathischen Reaktivierung — und er wird mit
    steigender Ausdauerleistungsfähigkeit größer. Wir nehmen das Maximum über
    die ganze Fahrt statt nur nach dem Schlusspunkt: so ist der Wert auch für
    Fahrten definiert, die nicht mit einer Belastung enden.
    """
    if not time_s or not hr:
        return None
    n = min(len(time_s), len(hr))
    t = np.asarray(time_s[:n], dtype=float)
    h = np.asarray([np.nan if v is None else v for v in hr[:n]], dtype=float)
    ok = np.isfinite(h) & (h > 60)
    if ok.sum() < 120:
        return None
    t, h = t[ok], h[ok]
    best = 0.0
    j = 0
    for i in range(len(t)):
        while j < len(t) and t[j] < t[i] + 60:
            j += 1
        if j >= len(t):
            break
        best = max(best, float(h[i] - h[j]))
    return round(best, 1) if best > 0 else None


# ===========================================================================
# Datenaufbereitung
# ===========================================================================

def _weight_kg() -> float | None:
    cfg = config.load_config_raw()
    config._overlay_env(cfg)
    try:
        w = float(config.athlete(cfg).get("weight_kg"))
    except (TypeError, ValueError):
        return None
    return w if w > 0 else None


def ef_series(rides: pd.DataFrame) -> pd.DataFrame:
    """Efficiency Factor je verwertbarer Fahrt.

    Spalten: ``day`` (datetime64), ``ef``, ``kind`` ("power"/"estimate"),
    ``power`` (W), ``hr``, ``speed_kmh``, ``is_indoor``.

    Verwertbar ist eine Fahrt, wenn sie lang genug war und im aeroben
    Intensitätsfenster lag — siehe MIN_MINUTES / HRR_LOW / HRR_HIGH.
    """
    cols = ["day", "ef", "kind", "power", "hr", "speed_kmh", "is_indoor"]
    if rides.empty:
        return pd.DataFrame(columns=cols)

    max_hr = zones.max_hr_from_data()
    rest_hr = zones.resting_hr_baseline()
    mass = total_mass_kg(_weight_kg())

    rows = []
    for _, r in rides.iterrows():
        hr = r.get("average_heartrate")
        if not hr or not np.isfinite(hr):
            continue
        if (r.get("moving_time_s") or 0) < MIN_MINUTES * 60:
            continue
        if max_hr:
            frac = zones.intensity_frac(float(hr), max_hr, rest_hr)
            if not (HRR_LOW <= frac <= HRR_HIGH):
                continue
        watts = r.get("weighted_average_watts") or r.get("average_watts")
        indoor = bool(r.get("is_indoor"))
        if watts and np.isfinite(watts) and watts > 0 and dataprep.has_power_meter(r.get("raw_json")):
            power, kind = float(watts), "power"
        elif indoor:
            # Rolle ohne echte Wattdaten: Tempo ist dort frei erfunden
            # (Zwift-Avatar), ein Physikmodell wäre reine Fantasie.
            continue
        else:
            power = estimate_power(r.get("distance_km"), r.get("moving_time_s"),
                                   r.get("elev_m"), mass)
            kind = "estimate"
        ef = efficiency_factor(power, float(hr), rest_hr)
        if ef is None:
            continue
        rows.append({
            "day": pd.Timestamp(r["start"]).normalize(),
            "ef": ef,
            "kind": kind,
            "power": power,
            "hr": float(hr),
            "speed_kmh": float(r.get("avg_speed_kmh") or 0.0),
            "is_indoor": indoor,
        })
    return pd.DataFrame(rows, columns=cols)


def ride_metrics() -> pd.DataFrame:
    """Aus Streams gewonnene Fahrtkennzahlen (Decoupling, HF-Erholung)."""
    df = store.read_table("ride_metrics")
    if df.empty:
        return pd.DataFrame(columns=["ride_id", "day", "decoupling", "hrr60"])
    df["day"] = pd.to_datetime(df.get("ride_day"), errors="coerce")
    return df.dropna(subset=["day"])


@dataclass
class _Ctx:
    """Alles, was für eine Auswertung gebraucht wird — einmal aufbereitet."""
    rides: pd.DataFrame
    ef: pd.DataFrame
    ctl: pd.DataFrame
    metrics: pd.DataFrame
    recovery: pd.DataFrame


def _context() -> _Ctx:
    rides = dataprep.prep_rides()
    ef = ef_series(rides)
    ctl = form.compute(rides)
    if not ctl.empty:
        ctl = ctl.assign(day=pd.to_datetime(ctl["date"]).dt.normalize())
    rec = dataprep.prep_recovery()
    if not rec.empty:
        rec = rec.assign(day=pd.to_datetime(rec["date"]).dt.normalize())
    return _Ctx(rides=rides, ef=ef, ctl=ctl, metrics=ride_metrics(), recovery=rec)


def _window(df: pd.DataFrame, as_of: pd.Timestamp, days: int) -> pd.DataFrame:
    if df.empty or "day" not in df.columns:
        return df
    lo = as_of - pd.Timedelta(days=days)
    return df[(df["day"] > lo) & (df["day"] <= as_of)]


def _med(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return float(s.median()) if len(s) else None


# ===========================================================================
# Ausgangsniveau (Anker)
# ===========================================================================

def _mean_daily_load(rides: pd.DataFrame, as_of: pd.Timestamp,
                     days: int) -> float | None:
    """Mittlere Tageslast über ein Fenster — ruhetagsbereinigt, rampenfrei.

    Das ist der Wert, gegen den CTL bei gleichbleibendem Training konvergiert,
    nur eben ohne die 42-Tage-Anlaufzeit. Leere Tage zählen mit; sonst wäre ein
    Fahrer mit einer harten Einheit pro Monat „kapazitätsstark".
    """
    if rides.empty:
        return None
    r = rides.assign(day=pd.to_datetime(rides["start"]).dt.normalize())
    win = _window(r, as_of, days)
    if win.empty:
        return None
    return float(win["load"].sum()) / days


def _build_anchor(ctx: _Ctx) -> dict | None:
    """Ausgangsniveau aus den ersten ANCHOR_DAYS verwertbarer Daten."""
    if ctx.ef.empty and ctx.ctl.empty:
        return None
    starts = [df["day"].min() for df in (ctx.ef, ctx.ctl) if not df.empty]
    if not starts:
        return None
    start = min(starts)
    end = start + pd.Timedelta(days=ANCHOR_DAYS)
    ef_win = ctx.ef[(ctx.ef["day"] >= start) & (ctx.ef["day"] <= end)]
    ctl_win = ctx.ctl[(ctx.ctl["day"] >= start) & (ctx.ctl["day"] <= end)] if not ctx.ctl.empty else ctx.ctl
    rec_win = ctx.recovery[(ctx.recovery["day"] >= start) & (ctx.recovery["day"] <= end)] if not ctx.recovery.empty else ctx.recovery

    span_days = 0
    if not ctx.ctl.empty:
        span_days = int((ctx.ctl["day"].max() - start).days)
    if span_days < ANCHOR_MIN_DAYS or len(ef_win) < ANCHOR_MIN_RIDES:
        return None

    anchor: dict = {
        "created": dt.date.today().isoformat(),
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "ef": {},
        # Kapazität als **mittlere Tageslast**, nicht als CTL-Wert. Grund: CTL
        # ist ein exponentieller Mittelwert mit 42 Tagen Zeitkonstante und läuft
        # aus dem Stand erst an — nach acht Wochen steht es bei rund 74 % seines
        # Endwerts. Gegen so einen Anker gemessen zeigte der Index selbst einem
        # Fahrer, der ein Jahr lang exakt gleich trainiert, „+47 % Kapazität".
        # Die mittlere Tageslast ist genau der Wert, gegen den CTL konvergiert,
        # und kennt diese Anlaufphase nicht. Beide Seiten des Vergleichs nutzen
        # denselben Schätzer (siehe `_mean_daily_load`), damit er sich kürzt.
        "ctl": _mean_daily_load(ctx.rides, end, ANCHOR_DAYS),
        "hrv": _med(rec_win["hrv_rmssd_milli"]) if not rec_win.empty else None,
        "rhr": _med(rec_win["resting_heart_rate"]) if not rec_win.empty else None,
    }
    for kind, grp in ef_win.groupby("kind"):
        m = _med(grp["ef"])
        if m:
            anchor["ef"][str(kind)] = m
    return anchor if anchor["ef"] or anchor["ctl"] else None


def load_anchor() -> dict | None:
    raw = store.get_kv(KV_ANCHOR)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def save_anchor(anchor: dict) -> None:
    store.set_kv(KV_ANCHOR, json.dumps(anchor, sort_keys=True))


def reset_anchor() -> None:
    """Ausgangsniveau verwerfen — wird beim nächsten Lauf neu gesetzt."""
    store.delete_kv(KV_ANCHOR)


# ===========================================================================
# Teilwerte
# ===========================================================================

@dataclass(frozen=True)
class Subscore:
    key: str
    label: str
    score: float | None       # 0–100, None = keine Datenbasis
    value: float | None       # aktueller Messwert in seiner eigenen Einheit
    unit: str
    baseline: float | None    # Ausgangsniveau in derselben Einheit
    rel: float | None         # relative Änderung gegenüber dem Anker
    n: int
    weight: float
    note: str

    @property
    def confidence(self) -> str:
        if self.score is None:
            return "keine Daten"
        return "hoch" if self.n >= 8 else ("mittel" if self.n >= 4 else "gering")


def _sub_eff(ctx: _Ctx, as_of: pd.Timestamp, anchor: dict) -> Subscore:
    win = _window(ctx.ef, as_of, WINDOW_DAYS)
    base = anchor.get("ef") or {}
    rels, n = [], 0
    for kind, grp in win.groupby("kind"):
        b = base.get(str(kind))
        m = _med(grp["ef"])
        if b and m:
            rels.append(m / b - 1.0)
            n += len(grp)
    rel = float(np.median(rels)) if rels else None
    cur = _med(win[win["kind"] == "estimate"]["power"]) if not win.empty else None
    # Für die Anzeige die Quelle nehmen, die das Fenster dominiert — sonst
    # stünde ein Wert aus Rollenwatt neben einer Basislinie aus Schätzwatt.
    main = win["kind"].mode().iat[0] if not win.empty and win["kind"].notna().any() else None
    cur_ef = _med(win[win["kind"] == main]["ef"]) if main else None
    return Subscore(
        key="eff", label=LABELS["eff"], score=points(rel, FULL_EFF),
        value=cur_ef, unit="W/Schlag",
        baseline=base.get(str(main)) if main else None, rel=rel, n=n,
        weight=WEIGHTS["eff"],
        note="Leistung je Herzschlag im aeroben Bereich, gemittelt über sechs Wochen."
        + (f" Ø geschätzte Außenleistung: {cur:.0f} W." if cur else ""),
    )


def _sub_cap(ctx: _Ctx, as_of: pd.Timestamp, anchor: dict) -> Subscore:
    # Angezeigt wird CTL (der Wert, den der Belastungs-Tab zeigt), gerechnet
    # wird mit der mittleren Tageslast — siehe `_mean_daily_load`.
    ctl_now = None
    if not ctx.ctl.empty:
        past = ctx.ctl[ctx.ctl["day"] <= as_of]
        if not past.empty:
            ctl_now = float(past.iloc[-1]["ctl"])
    base = anchor.get("ctl")
    now = _mean_daily_load(ctx.rides, as_of, WINDOW_DAYS)
    rel = (now / base - 1.0) if (base and now is not None and base > 0) else None
    n = len(_window(ctx.rides.assign(day=pd.to_datetime(ctx.rides["start"]).dt.normalize()),
                    as_of, WINDOW_DAYS)) if not ctx.rides.empty else 0
    return Subscore(
        key="cap", label=LABELS["cap"], score=points(rel, FULL_CAP), value=now,
        unit="Last/Tag", baseline=base, rel=rel, n=n, weight=WEIGHTS["cap"],
        note="Wie viel Reiz du dauerhaft verträgst. Verglichen wird die mittlere "
             "Tageslast und nicht CTL selbst — CTL braucht sechs Wochen Anlauf und "
             "schönte den Vergleich gegen das Ausgangsfenster."
             + (f" Aktuelle CTL: {ctl_now:.0f}." if ctl_now is not None else ""),
    )


def _sub_dur(ctx: _Ctx, as_of: pd.Timestamp, anchor: dict) -> Subscore:
    win = _window(ctx.metrics, as_of, LONG_WINDOW_DAYS)
    dec = _med(win["decoupling"]) if not win.empty else None
    return Subscore(
        key="dur", label=LABELS["dur"], score=points_from_decoupling(dec), value=dec,
        # Kein persönlicher Ausgangswert: hier ist die Skala selbst aussagekräftig
        # (siehe `points_from_decoupling`), ein Anker wäre nur Ballast.
        unit="% Drift", baseline=None, rel=None, n=len(win), weight=WEIGHTS["dur"],
        note="Pulsdrift in der zweiten Fahrthälfte. Unter 5 % gilt als gut aerob "
             "konditioniert — du hältst dein Tempo, ohne dass der Puls davonläuft.",
    )


def _sub_reg(ctx: _Ctx, as_of: pd.Timestamp, anchor: dict) -> Subscore:
    win = _window(ctx.recovery, as_of, WINDOW_DAYS)
    hrv = _med(win["hrv_rmssd_milli"]) if not win.empty else None
    rhr = _med(win["resting_heart_rate"]) if not win.empty else None
    parts = []
    if anchor.get("hrv") and hrv:
        parts.append(points(hrv / anchor["hrv"] - 1.0, FULL_HRV))
    if anchor.get("rhr") and rhr:
        # Ruhepuls: kleiner ist besser, deshalb umgekehrtes Vorzeichen.
        parts.append(points(-(rhr / anchor["rhr"] - 1.0), FULL_RHR))
    parts = [p for p in parts if p is not None]
    score = float(np.mean(parts)) if parts else None
    return Subscore(
        key="reg", label=LABELS["reg"], score=score, value=hrv, unit="ms HRV",
        baseline=anchor.get("hrv"), rel=(hrv / anchor["hrv"] - 1.0) if (anchor.get("hrv") and hrv) else None,
        n=len(win), weight=WEIGHTS["reg"],
        note="HRV-Basislinie und Ruhepuls aus Whoop"
             + (f" · Ruhepuls {rhr:.0f} bpm" if rhr else "") + ".",
    )


def _sub_kon(ctx: _Ctx, as_of: pd.Timestamp, anchor: dict) -> Subscore:
    if ctx.rides.empty:
        return Subscore("kon", LABELS["kon"], None, None, "% Wochen", None, None, 0,
                        WEIGHTS["kon"], "Zu wenige Daten.")
    days = CONSISTENCY_WEEKS * 7
    win = _window(ctx.rides.assign(day=pd.to_datetime(ctx.rides["start"]).dt.normalize()),
                  as_of, days)
    if win.empty:
        return Subscore("kon", LABELS["kon"], 0.0, 0.0, "% Wochen", None, None, 0,
                        WEIGHTS["kon"], "In den letzten zwölf Wochen keine Fahrt.")
    # Montag-bis-Sonntag: pandas gruppiert bei "W-MON" sonst rechtsseitig und
    # zerschneidet die Trainingswochen (siehe CLAUDE.md).
    weekly = (win.set_index("day")["load"]
              .resample("W-MON", closed="left", label="left").sum())
    weekly = weekly.reindex(
        pd.date_range(as_of - pd.Timedelta(days=days), as_of, freq="W-MON"),
        fill_value=0.0,
    )
    active = float((weekly > 0).mean())
    mean = float(weekly.mean())
    cv = float(weekly.std() / mean) if mean > 0 else 1.0
    # Drei Viertel für „überhaupt gefahren", ein Viertel für Gleichmäßigkeit:
    # Regelmäßigkeit schlägt Gleichverteilung, aber Alles-oder-nichts-Wochen
    # sollen nicht so viel wert sein wie ein ruhiger Rhythmus.
    score = 100.0 * (0.75 * active + 0.25 * (1.0 - min(cv, 1.0)))
    return Subscore(
        key="kon", label=LABELS["kon"], score=round(score, 1), value=round(active * 100, 0),
        unit="% Wochen", baseline=None, rel=None, n=len(win), weight=WEIGHTS["kon"],
        note=f"{int(round(active * len(weekly)))} von {len(weekly)} Wochen mit Training, "
             "gleichmäßig gewichtet.",
    )


_SUBS = (_sub_eff, _sub_cap, _sub_dur, _sub_reg, _sub_kon)


def _evaluate(ctx: _Ctx, as_of: pd.Timestamp, anchor: dict) -> tuple[float | None, list[Subscore]]:
    subs = [fn(ctx, as_of, anchor) for fn in _SUBS]
    usable = [s for s in subs if s.score is not None]
    if not usable:
        return None, subs
    # Gewichte auf die vorhandenen Teilwerte normieren: ein fehlendes Signal
    # darf nie wie ein schlechtes aussehen.
    total = sum(s.weight for s in usable)
    score = sum(s.score * s.weight for s in usable) / total
    return round(score, 1), subs


# ===========================================================================
# Klartext: was kannst du heute besser als früher?
# ===========================================================================

def speed_at_hr(ef_df: pd.DataFrame, hr_ref: float) -> float | None:
    """Zu erwartendes Außentempo bei einer Referenz-Herzfrequenz.

    Lineare Regression Tempo ~ Puls über die Fahrten des Fensters. Braucht
    genug Fahrten *und* genug Pulsspreizung — sonst extrapoliert die Gerade
    wild und die schöne Zahl wäre erfunden.
    """
    d = ef_df[(~ef_df["is_indoor"]) & (ef_df["speed_kmh"] > 0)]
    if len(d) < 5:
        return None
    hr = d["hr"].to_numpy(dtype=float)
    if hr.max() - hr.min() < 8:
        return None
    slope, intercept = np.polyfit(hr, d["speed_kmh"].to_numpy(dtype=float), 1)
    # Nicht über den beobachteten Bereich hinaus raten.
    hr_ref = float(np.clip(hr_ref, hr.min() - 5, hr.max() + 5))
    return float(slope * hr_ref + intercept)


def _de(x: float, dec: int = 1) -> str:
    """Zahl mit deutschem Dezimalkomma. Die Sätze landen 1:1 im Dashboard, im
    Morgen-Report und in today.json — dort wäre ein Punkt ein Fremdkörper."""
    return f"{x:.{dec}f}".replace(".", ",")


def _highlights(ctx: _Ctx, as_of: pd.Timestamp, anchor: dict,
                subs: list[Subscore]) -> list[str]:
    """Konkrete Sätze statt abstrakter Punkte — „das kannst du jetzt besser"."""
    out: list[str] = []
    by = {s.key: s for s in subs}

    eff = by.get("eff")
    if eff and eff.rel is not None and abs(eff.rel) >= 0.01:
        verb = "mehr" if eff.rel > 0 else "weniger"
        out.append(
            f"⚡ Bei gleichem Puls bringst du heute **{_de(abs(eff.rel) * 100)} % {verb} "
            f"Leistung** aufs Pedal als zu Beginn deiner Aufzeichnung."
        )

    # Tempo bei Referenzpuls: jetzt gegen das Anker-Fenster.
    lthr = zones.lthr_from_config()
    max_hr = zones.max_hr_from_data()
    rest_hr = zones.resting_hr_baseline()
    if lthr:
        hr_ref = 0.88 * lthr
    elif max_hr:
        z = zones.zone_for(2, max_hr, rest_hr, lthr)
        hr_ref = (z.low_bpm + z.high_bpm) / 2
    else:
        hr_ref = None
    if hr_ref:
        now = speed_at_hr(_window(ctx.ef, as_of, LONG_WINDOW_DAYS), hr_ref)
        a_from = pd.Timestamp(anchor["from"])
        a_to = pd.Timestamp(anchor["to"])
        then_df = ctx.ef[(ctx.ef["day"] >= a_from) & (ctx.ef["day"] <= a_to)]
        then = speed_at_hr(then_df, hr_ref)
        if now and then and abs(now - then) >= 0.2:
            out.append(
                f"🚴 Bei **{hr_ref:.0f} bpm** fährst du inzwischen rund "
                f"**{_de(now)} km/h** — im Ausgangsfenster waren es {_de(then)} km/h "
                f"({'+' if now > then else ''}{_de(now - then)} km/h)."
            )

    dur = by.get("dur")
    if dur and dur.value is not None:
        if dur.value < 5:
            out.append(
                f"🫀 Dein Puls driftet in der zweiten Fahrthälfte nur **{_de(dur.value)} %** "
                "vom Tempo weg — das ist der Bereich, in dem lange Fahrten aufhören, "
                "teuer zu werden."
            )
        else:
            out.append(
                f"🫀 Pulsdrift in der zweiten Fahrthälfte: **{_de(dur.value)} %**. "
                "Unter 5 % ist das Ziel — ruhige lange Einheiten sind der Hebel dafür."
            )

    # Persönliche Bestwerte: „number go high" braucht Rekorde zum Jagen.
    if not ctx.ctl.empty:
        past = ctx.ctl[ctx.ctl["day"] <= as_of]
        if not past.empty:
            cur, peak = float(past.iloc[-1]["ctl"]), float(past["ctl"].max())
            if cur >= peak - 0.01:
                out.append(f"📈 Deine Fitness (CTL {cur:.0f}) steht auf ihrem **Allzeithoch**.")
            elif peak > 0 and cur / peak >= 0.9:
                out.append(
                    f"📈 CTL {cur:.0f} — nur noch {peak - cur:.0f} Punkte unter deinem "
                    f"Bestwert von {peak:.0f}."
                )

    if not ctx.rides.empty:
        r = ctx.rides.assign(day=pd.to_datetime(ctx.rides["start"]).dt.normalize())
        recent = _window(r, as_of, LONG_WINDOW_DAYS)
        if not recent.empty:
            longest = float(recent["distance_km"].max())
            alltime = float(r[r["day"] <= as_of]["distance_km"].max())
            if longest >= alltime - 0.01:
                out.append(f"🏁 Längste Fahrt der letzten 90 Tage: **{longest:.0f} km** — dein Rekord.")
            else:
                out.append(
                    f"🏁 Längste Fahrt der letzten 90 Tage: **{longest:.0f} km** "
                    f"(Rekord: {alltime:.0f} km)."
                )

    reg = by.get("reg")
    if reg and reg.rel is not None and abs(reg.rel) >= 0.03:
        richtung = "höher" if reg.rel > 0 else "niedriger"
        out.append(
            f"😴 Deine HRV-Basislinie liegt **{abs(reg.rel) * 100:.0f} % {richtung}** "
            "als im Ausgangsfenster."
        )
    return out


# ===========================================================================
# Öffentliche Schnittstelle
# ===========================================================================

@dataclass
class FitnessIndex:
    score: float | None
    tier: str
    delta_30: float | None
    delta_90: float | None
    best: float | None
    best_date: dt.date | None
    subscores: list[Subscore]
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    highlights: list[str] = field(default_factory=list)
    anchor: dict | None = None
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.score is not None

    def to_dict(self) -> dict:
        """Kompakte Fassung für ``today.json`` und den Morgen-Report."""
        return {
            "score": self.score,
            "tier": self.tier,
            "delta_30": self.delta_30,
            "delta_90": self.delta_90,
            "best": self.best,
            "subscores": {
                s.key: {"label": s.label, "score": round(s.score, 1), "n": s.n}
                for s in self.subscores if s.score is not None
            },
            "highlight": self.highlights[0] if self.highlights else None,
        }


def _empty(reason: str) -> FitnessIndex:
    return FitnessIndex(score=None, tier="—", delta_30=None, delta_90=None,
                        best=None, best_date=None, subscores=[], reason=reason)


def compute(today: dt.date | None = None, persist: bool = True) -> FitnessIndex:
    """Fitness-Index für einen Stichtag, inklusive Verlauf und Klartext.

    ``persist=False`` verhindert das Festschreiben des Ankers — nützlich für
    Vorschauen und Tests, die die Datenbank nicht verändern sollen.
    """
    as_of = pd.Timestamp(today or dt.date.today()).normalize()
    ctx = _context()
    if ctx.rides.empty:
        return _empty("Noch keine Fahrten in der Datenbank.")

    anchor = load_anchor()
    if anchor is None:
        anchor = _build_anchor(ctx)
        if anchor is None:
            return _empty(
                f"Noch zu wenig Historie: der Index braucht mindestens "
                f"{ANCHOR_MIN_DAYS} Tage und {ANCHOR_MIN_RIDES} auswertbare Fahrten, "
                "um dein Ausgangsniveau festzulegen."
            )
        if persist:
            save_anchor(anchor)

    score, subs = _evaluate(ctx, as_of, anchor)
    if score is None:
        return _empty("Keine auswertbaren Signale im aktuellen Fenster.")

    # Verlauf: wöchentlich ab dem Ende des Ankerfensters. Wöchentlich reicht —
    # der Index ist per Konstruktion träge, tägliche Punkte wären nur Rauschen.
    start = max(pd.Timestamp(anchor["to"]), as_of - pd.Timedelta(days=HISTORY_DAYS))
    dates = pd.date_range(start, as_of, freq="7D")
    if len(dates) == 0 or dates[-1] != as_of:
        dates = dates.append(pd.DatetimeIndex([as_of]))
    hist_rows = []
    for d in dates:
        s, _ = _evaluate(ctx, d, anchor)
        if s is not None:
            hist_rows.append({"day": d, "score": s})
    history = pd.DataFrame(hist_rows, columns=["day", "score"])

    def _back(days: int) -> float | None:
        if history.empty:
            return None
        cut = as_of - pd.Timedelta(days=days)
        prev = history[history["day"] <= cut]
        return round(score - float(prev.iloc[-1]["score"]), 1) if not prev.empty else None

    best, best_date = (None, None)
    if not history.empty:
        row = history.loc[history["score"].idxmax()]
        best, best_date = float(row["score"]), row["day"].date()

    return FitnessIndex(
        score=score, tier=tier(score), delta_30=_back(30), delta_90=_back(90),
        best=best, best_date=best_date, subscores=subs, history=history,
        highlights=_highlights(ctx, as_of, anchor, subs), anchor=anchor,
    )


# ===========================================================================
# Streams auswerten (Ermüdungsresistenz)
# ===========================================================================
# Decoupling braucht den Verlauf einer Fahrt, nicht nur ihre Zusammenfassung —
# also Strava-Streams. Die sind rate-limitiert, deshalb dasselbe Muster wie im
# Wind-Labor: portionsweise abarbeiten, Ergebnis in die DB, schon versuchte
# Fahrten nicht erneut abfragen.

STATE_ATTEMPTED = "fitness_streams_attempted"


def _attempted_ids() -> set[int]:
    raw = store.get_state(STATE_ATTEMPTED)
    return set(json.loads(raw)) if raw else set()


def _mark_attempted(ids: set[int]) -> None:
    store.set_state(STATE_ATTEMPTED, json.dumps(sorted(_attempted_ids() | ids)))


def metrics_from_streams(streams: dict, ride_id: int, day: pd.Timestamp) -> dict | None:
    """Kennzahlen einer Fahrt aus ihren Streams. Ohne Puls kein Ergebnis."""
    time_s = (streams.get("time") or {}).get("data")
    hr = (streams.get("heartrate") or {}).get("data")
    if not time_s or not hr:
        return None
    watts = (streams.get("watts") or {}).get("data")
    vel = (streams.get("velocity_smooth") or {}).get("data")
    # Watt schlägt Tempo: Gegenwind und Steigung verfälschen das Tempo, die
    # Leistung nicht. Ohne Powermeter bleibt nur das Tempo — deshalb steht in
    # ``basis``, worauf der Wert beruht, und Äpfel werden nicht mit Birnen
    # verglichen.
    output, basis = (watts, "power") if watts else (vel, "speed")
    if not output:
        return None
    dec = decoupling_from_streams(time_s, hr, output)
    if dec is None:
        return None
    return {
        "ride_id": int(ride_id),
        "ride_day": pd.Timestamp(day).normalize().date().isoformat(),
        "decoupling": dec["decoupling"],
        "ef_first": dec["ef_first"],
        "ef_second": dec["ef_second"],
        "hr_drift": dec["hr_drift"],
        "hrr60": hr_recovery_60(time_s, hr),
        "basis": basis,
        "n_points": dec["n_points"],
        "computed_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def analyze_rides(cfg: dict, limit: int = 15, force: bool = False,
                  progress_cb=None) -> dict:
    """Holt Streams noch nicht ausgewerteter Fahrten und legt die Kennzahlen ab.

    Beginnt bei den neuesten Fahrten — die sagen über den aktuellen Zustand am
    meisten aus. Gibt eine Zusammenfassung für die Oberfläche zurück.
    """
    rides = dataprep.prep_rides()
    if rides.empty:
        return {"processed": 0, "stored": 0, "todo": 0}
    # Nur Fahrten, die überhaupt lang genug für eine Halbierung sind.
    usable = rides[rides["moving_time_s"] >= MIN_MINUTES * 60]
    done = set() if force else _attempted_ids()
    todo = usable[~usable["id"].isin(done)].sort_values("start", ascending=False)
    batch = todo.head(limit)

    rows: list[dict] = []
    attempted: set[int] = set()
    for pos, (_, r) in enumerate(batch.iterrows()):
        if progress_cb:
            progress_cb(pos, len(batch), r.get("name", ""))
        rid = int(r["id"])
        try:
            streams = strava.fetch_streams(cfg, rid)
        except RuntimeError:
            break   # Rate-Limit: bisher Gesammeltes behalten, später weiter
        attempted.add(rid)
        m = metrics_from_streams(streams, rid, r["start"])
        if m:
            rows.append(m)
    if rows:
        store.upsert_ride_metrics(rows)
    if attempted:
        _mark_attempted(attempted)
    return {"processed": len(attempted), "stored": len(rows),
            "todo": max(len(todo) - len(attempted), 0)}


def streams_pending() -> int:
    """Wie viele Fahrten sind noch nicht auf Ermüdungsresistenz ausgewertet?"""
    rides = dataprep.prep_rides()
    if rides.empty:
        return 0
    usable = rides[rides["moving_time_s"] >= MIN_MINUTES * 60]
    return int((~usable["id"].isin(_attempted_ids())).sum())
