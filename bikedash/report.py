"""Morgen-Report: heutige Empfehlung aufs Handy, sobald die Whoop-Recovery da ist.

Push läuft über ntfy.sh (kostenlos, ohne Konto): in der ntfy-App auf dem Handy
ein selbst gewähltes Thema abonnieren und dasselbe Thema in der Einrichtung
unter [report] ntfy_topic eintragen.

**Zeitpunkt — ereignisgesteuert statt Uhrzeit.** Eine feste Uhrzeit (früher
06:30) war zu früh: Whoop rechnet die Recovery erst nach dem Aufwachen, und bis
der Sync sie geholt hat, stünde im Report die von gestern — ohne es zu sagen.
Deshalb entscheidet ``due()`` bei jedem Sync-Lauf im Morgenfenster:

- heute schon gesendet → nichts
- heutige Recovery in der Datenbank → jetzt senden
- Frist (``DEADLINE``, 10:00 deutscher Zeit) erreicht → senden, mit Hinweis,
  dass die Recovery fehlt und die Empfehlung den Stand von gestern hat
- sonst → warten

Der Sync-Workflow läuft dafür morgens alle 30 Minuten (``sync.yml``). Der
Marker ``report_sent_date`` liegt in ``app_kv``, damit auch bei überlappenden
Läufen nur ein Push pro Tag rausgeht.

**Inhalt — die erste Zeile trägt die Entscheidung.** Am Sperrbildschirm sind
drei, vier Zeilen sichtbar; alles Wichtige steht deshalb vorn: Einheit, Dauer,
Watt, und ob das Workout in Zwift liegt. Wetter nur, wenn Draußenfahren
überhaupt in Frage kommt (kein Ruhetag) — in der Indoor-Saison ist es Rauschen.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import requests

from . import config, dataprep, fitness, form, recommend, store, weather, zwift

TZ = ZoneInfo("Europe/Berlin")
EARLIEST = dt.time(6, 0)    # vorher nie – auch wenn Whoop nachts etwas liefert
DEADLINE = dt.time(10, 0)   # spätestens dann, notfalls ohne heutige Recovery
KV_SENT = "report_sent_date"

SHORT = {"RECOVERY": "Erholung Z1", "ENDURANCE": "Grundlage Z2",
         "TEMPO": "Tempo Z3", "THRESHOLD": "Schwelle Z4", "REST": "Ruhetag"}


# ---------------------------------------------------------------------------
# Wann senden?
# ---------------------------------------------------------------------------

def recovery_present(today: dt.date) -> bool:
    """Liegt die Whoop-Recovery für heute schon in der Datenbank?

    Das Recovery-Datum ist der Beginn des Whoop-Zyklus, also der Aufwach-Tag —
    die Recovery von heute Morgen trägt damit das heutige Datum.
    """
    try:
        rec = dataprep.prep_recovery()
    except Exception:  # noqa: BLE001
        return False
    if rec.empty:
        return False
    today_rows = rec[rec["date"].dt.date == today]
    return bool(today_rows["recovery_score"].notna().any())


def last_sent() -> dt.date | None:
    raw = store.get_kv(KV_SENT)
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def mark_sent(today: dt.date) -> None:
    store.set_kv(KV_SENT, today.isoformat())


def due(now_local: dt.datetime, has_recovery: bool,
        sent: dt.date | None) -> tuple[bool, str]:
    """(senden?, Begründung) – rein, ohne Datenbank, damit testbar."""
    today = now_local.date()
    if sent == today:
        return False, "heute schon gesendet"
    if now_local.time() < EARLIEST:
        return False, f"vor {EARLIEST:%H:%M} Uhr wird nicht gesendet"
    if has_recovery:
        return True, "heutige Whoop-Recovery ist da"
    if now_local.time() >= DEADLINE:
        return True, f"Frist {DEADLINE:%H:%M} Uhr erreicht, Recovery fehlt noch"
    return False, "wartet auf die heutige Whoop-Recovery"


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def _watts(rc: Any) -> str:
    if not rc.power_plan:
        return ""
    main = [b for b in rc.power_plan if b["label"] not in ("Einfahren", "Ausfahren")]
    if not main:
        return ""
    b = main[0]
    return f"{int(round((b['low_w'] + b['high_w']) / 2))} W"


def build_text(cfg: dict[str, Any], today: dt.date | None = None,
               stale_recovery: bool = False) -> tuple[str, str]:
    """Gibt (Titel, Nachricht) für den heutigen Report zurück.

    Der Titel bleibt Latin-1-tauglich (HTTP-Header); der Text darf alles.
    """
    today = today or dt.date.today()
    rc = recommend.build(today)
    short = SHORT.get(rc.kind, rc.title)

    if rc.kind == "REST":
        title = "Heute: Ruhetag"
    else:
        mid = int(sum(rc.duration_min) / 2)
        w = _watts(rc)
        title = f"Heute: {short} · {mid} min" + (f" · {w}" if w else "")

    parts: list[str] = []
    if stale_recovery:
        parts.append("Whoop-Recovery von heute fehlt noch — Empfehlung mit dem Stand von gestern.")

    if rc.kind == "REST":
        parts.append("Erhol dich gut. 🌱")
    else:
        power = f", {rc.power_low}–{rc.power_high} W" if rc.power_low else ""
        hr = f" (HF {rc.hr_low}–{rc.hr_high})" if rc.hr_low else ""
        parts.append(f"{rc.title}: {rc.duration_min[0]}–{rc.duration_min[1]} min{power}{hr}, "
                     f"Trittfrequenz {rc.cadence}.")
        last = zwift.last_result()
        if last is not None and last.ok and last.date == today.isoformat():
            parts.append("Zwift: Workout liegt bereit (Workouts → Custom → Intervals.icu).")

    why = rc.rationale[-1] if rc.rationale else ""
    rec = f"Recovery {rc.recovery_score:.0f} %" if rc.recovery_score is not None else "Keine Recovery"
    parts.append(f"{rec} · {why}" if why else f"{rec}.")

    if rc.target_load:
        pct = int(round(100 * rc.week_load / rc.target_load))
        parts.append(f"Woche: {rc.week_load:.0f}/{rc.target_load:.0f} Last ({pct} %), "
                     f"{rc.week_hours:.1f}/{rc.target_hours:.1f} h.")
    else:
        parts.append(f"Woche bisher {rc.week_hours:.1f}/{rc.target_hours:.1f} h.")

    if rc.kind != "REST":
        wx = weather.current(cfg)
        if wx is not None:
            parts.append(f"Draußen: {wx.icon} {wx.temp_c:.0f} °C, Wind {wx.wind_kmh:.0f} km/h "
                         f"aus {wx.wind_dir}, Regen {wx.precip_prob} %.")
            tips = weather.advice(wx)
            if tips and not tips[0].startswith("👍"):
                parts.append(tips[0])

    fdf = form.compute(dataprep.prep_rides())
    if len(fdf) >= 7:
        cur = fdf.iloc[-1]
        status, _ = form.interpret(cur["tsb"])
        parts.append(f"Form (TSB) {cur['tsb']:+.0f} — {status}.")

    line = fitness_line(today)
    if line:
        parts.append(line)

    return title, "\n".join(parts)


def fitness_line(today: dt.date | None = None) -> str:
    """Eine Zeile Fortschritt für den Push — der tägliche „number go high"-Blick.

    Bewusst am Ende der Nachricht: die Trainingsentscheidung steht vorn, das
    hier ist Motivation. ``persist=False``, damit ein Cron-Lauf nie das
    Ausgangsniveau festschreibt (siehe `bikedash/fitness.py`).
    """
    try:
        fi = fitness.compute(today, persist=False)
    except Exception:  # noqa: BLE001 – eine Motivationszeile kippt keinen Report
        return ""
    if not fi.available:
        return ""
    txt = f"Fitness-Index {fi.score:.1f} ({fi.tier})"
    if fi.delta_30 is not None and abs(fi.delta_30) >= 0.1:
        txt += f", {fi.delta_30:+.1f} in 30 Tagen"
    if fi.best is not None and fi.score >= fi.best - 0.01:
        return txt + " — neuer Bestwert! 🏆"
    return txt + "."


# ---------------------------------------------------------------------------
# Senden
# ---------------------------------------------------------------------------

def topic(cfg: dict[str, Any]) -> str:
    t = str(cfg.get("report", {}).get("ntfy_topic", "")).strip()
    return "" if t.startswith("DEIN") else t


def send_push(cfg: dict[str, Any], title: str, message: str) -> bool:
    """Schickt den Report per ntfy ans Handy. True bei Erfolg."""
    t = topic(cfg)
    if not t:
        return False
    headers = {"Title": title.encode("latin-1", "replace").decode("latin-1"),
               "Tags": "bike", "Priority": "default"}
    # Tipp auf die Nachricht öffnet das Dashboard (optional).
    url = str(cfg.get("report", {}).get("dashboard_url", "")).strip()
    if url.startswith("http"):
        headers["Click"] = url
    try:
        resp = requests.post(f"https://ntfy.sh/{t}", data=message.encode("utf-8"),
                             headers=headers, timeout=20)
        return resp.status_code < 300
    except requests.RequestException:
        return False


def send_if_due(cfg: dict[str, Any], now: dt.datetime | None = None) -> tuple[str, str]:
    """Der Aufruf aus dem Sync-Workflow. Gibt (Status, Begründung) zurück.

    Status: ``sent`` | ``waiting`` | ``already`` | ``no_topic`` | ``failed``.
    """
    if not topic(cfg):
        return "no_topic", "kein ntfy-Thema gesetzt"
    now_local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(TZ)
    today = now_local.date()
    has_rec = recovery_present(today)
    ok, why = due(now_local, has_rec, last_sent())
    if not ok:
        return ("already" if why.startswith("heute schon") else "waiting"), why
    title, msg = build_text(cfg, today=today, stale_recovery=not has_rec)
    if not send_push(cfg, title, msg):
        return "failed", "ntfy hat nicht angenommen"
    mark_sent(today)
    return "sent", why
