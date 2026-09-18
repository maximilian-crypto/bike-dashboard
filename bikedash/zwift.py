"""Tagesworkout automatisch in die Zwift-Bibliothek — über intervals.icu.

Das Ziel: Zwift öffnen, das heutige Workout antippen, ERG macht den Rest. Kein
Suchen, keine Datei, kein PC. Der Weg dorthin:

    build_today.py  →  intervals.icu-Kalender (offene API, API-Key)
                    →  Zwift (offizielle Anbindung „Zwift Training API")
                    →  Zwift-App: Workouts → Custom → Ordner „Intervals.icu"

intervals.icu lädt geplante Workouts seiner Athleten selbst nach Zwift hoch und
hält sie dort aktuell — auf allen Geräten, auch auf dem iPhone. Das ist der
einzige recherchierte Weg ohne PC: die Cloud-Synchronisation eigener
``.zwo``-Dateien verlangt einen Rechner, der Zwift startet, und die inoffizielle
Zwift-API ist ToS-Graubereich. Einmalige Einrichtung (siehe DEPLOY.md): Konto bei
intervals.icu, dort Zwift verbinden, API-Key + Athleten-ID hier hinterlegen.

Was hier passiert:
- ``workout_text``: die Blöcke aus ``power.structure`` (bereits in
  ``Recommendation.power_plan``) werden in die native intervals.icu-Workout-
  Syntax übersetzt — eine Zeile je Block, Wattziel als **Anteil der FTP**.
  Prozent statt Watt, weil Zwift im ERG-Modus ohnehin mit *seiner* FTP
  multipliziert: stimmen FTP im Dashboard und in Zwift überein, kommt exakt die
  geplante Wattzahl an, egal was intervals.icu selbst als FTP hinterlegt hat.
- ``push_today``: legt das Workout für heute an bzw. aktualisiert es. Der
  Sync läuft alle vier Stunden, die Empfehlung ändert sich über den Tag (Whoop-
  Recovery kommt morgens) — deshalb idempotent über ``external_id``: pro Tag
  genau ein Eintrag, nie Duplikate. Wird der Tag ein Ruhetag, verschwindet der
  Eintrag wieder. Unveränderte Workouts werden nicht neu geschrieben, damit
  intervals.icu nicht alle vier Stunden nach Zwift nachschiebt.

Fehler hier dürfen den Tagesplan nie kippen: ``push_today`` wirft nicht, sondern
liefert ein ``PushResult``, das in ``today.json`` und in ``app_kv`` landet — so
sieht man im Dashboard, ob das Workout wirklich angekommen ist.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import requests

from . import store

API_BASE = "https://intervals.icu/api/v1"
TIMEOUT_S = 20
EXTERNAL_PREFIX = "bikedash-"     # external_id = bikedash-JJJJ-MM-TT
NAME_PREFIX = "Bikedash"
KV_KEY = "zwift_last_push"

# Zwift synchronisiert Workouts mit Sonderzeichen im Namen nicht (recherchiert,
# s. Handoff). Deshalb bleibt der Name strikt bei Buchstaben, Ziffern, Leerzeichen
# und Bindestrich — auch keine Umlaute.
_NAME_ALLOWED = re.compile(r"[^A-Za-z0-9 \-]")
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe",
                          "Ü": "Ue", "ß": "ss"})

# Kurzname je Einheitentyp für den Zwift-Ordner (ASCII, s. o.).
SHORT_TITLES = {
    "RECOVERY": "Erholung Z1",
    "ENDURANCE": "Grundlage Z2",
    "TEMPO": "Tempo Z3",
    "THRESHOLD": "Schwelle Z4",
}


@dataclass
class PushResult:
    """Ergebnis eines Laufs — wandert nach today.json und app_kv."""
    status: str                 # sent | updated | unchanged | deleted | skipped | error
    name: str | None = None
    event_id: int | None = None
    detail: str | None = None
    date: str | None = None
    at: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("sent", "updated", "unchanged")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

def settings(cfg: dict[str, Any]) -> tuple[str, str]:
    """(API-Key, Athleten-ID) aus der Config; leer, wenn nicht eingerichtet.

    Die Athleten-ID steht in intervals.icu unter Settings → Developer Settings
    (Form ``i12345``). Fehlt sie, nimmt die API ``0`` für den Besitzer des
    API-Keys.
    """
    sec = cfg.get("intervals", {}) or {}
    key = str(sec.get("api_key", "") or "").strip()
    if key.startswith("DEIN_"):
        key = ""
    athlete = str(sec.get("athlete_id", "") or "").strip() or "0"
    return key, athlete


def configured(cfg: dict[str, Any]) -> bool:
    return bool(settings(cfg)[0])


# ---------------------------------------------------------------------------
# Übersetzung Empfehlung → intervals.icu-Workout
# ---------------------------------------------------------------------------

def _ascii_name(text: str) -> str:
    text = text.translate(_UMLAUTS)
    text = _NAME_ALLOWED.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def workout_name(kind: str, day: dt.date, total_min: int) -> str:
    """Kurzer, Zwift-tauglicher Name: ``Bikedash 18-09 Grundlage Z2 89min``.

    Das Datum steht vorn, weil der Zwift-Ordner mehrere Tage nebeneinander
    zeigen kann und man sonst nicht sieht, welches Workout das heutige ist.
    """
    short = SHORT_TITLES.get(kind, kind.title())
    return _ascii_name(f"{NAME_PREFIX} {day:%d-%m} {short} {total_min}min")


def _cadence_rpm(cadence: str | None) -> int | None:
    """"85–95" → 90 (Mitte des Zielbands). ERG braucht einen Wert, kein Band."""
    nums = [int(n) for n in re.findall(r"\d+", cadence or "")]
    if not nums:
        return None
    return int(round(sum(nums[:2]) / len(nums[:2])))


def _pct_of_ftp(low_w: int, high_w: int, ftp: int) -> int:
    """Bandmitte als ganzzahliger FTP-Anteil — der ERG-Sollwert."""
    return int(round((low_w + high_w) / 2.0 / ftp * 100))


def _step(block: dict[str, Any], ftp: int) -> str:
    pct = _pct_of_ftp(int(block["low_w"]), int(block["high_w"]), ftp)
    line = f"- {int(block['minutes'])}m {pct}%"
    rpm = _cadence_rpm(block.get("cadence"))
    if rpm:
        line += f" {rpm}rpm"
    return line


def workout_text(power_plan: list[dict[str, Any]], ftp: int,
                 headline: str | None = None) -> str:
    """Native intervals.icu-Syntax aus den Blöcken der Tagesempfehlung.

    Ein Schritt je Block, bewusst **ohne** ``Nx``-Wiederholungen: die Struktur
    aus ``power.structure`` hat nach dem letzten Intervall keine Pause, ein
    Wiederholungsblock hätte eine. So entspricht das Zwift-Workout Minute für
    Minute der Tabelle im Dashboard. Abschnittsüberschriften bleiben frei von
    Zahlen mit Einheit, damit der Parser sie nicht für Schritte hält.
    """
    if not power_plan or not ftp or ftp <= 0:
        return ""
    warm = [b for b in power_plan if b["label"] == "Einfahren"]
    cool = [b for b in power_plan if b["label"] == "Ausfahren"]
    main = [b for b in power_plan if b not in warm and b not in cool]

    parts: list[str] = []
    if headline:
        parts.append(headline)
        parts.append("")
    for title, blocks in (("Einfahren", warm), ("Hauptteil", main), ("Ausfahren", cool)):
        if not blocks:
            continue
        parts.append(title)
        parts.extend(_step(b, ftp) for b in blocks)
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def event_payload(rc: Any, day: dt.date, ftp: int) -> dict[str, Any]:
    """Der Kalendereintrag, den intervals.icu nach Zwift weiterreicht."""
    plan: list[dict[str, Any]] = list(getattr(rc, "power_plan", []) or [])
    total_min = sum(int(b["minutes"]) for b in plan)
    headline = f"Bike-Dashboard, Tagesempfehlung vom {day:%d.%m.%Y}: {rc.title}"
    return {
        "category": "WORKOUT",
        "start_date_local": f"{day.isoformat()}T00:00:00",
        "type": "Ride",
        "indoor": True,
        "name": workout_name(rc.kind, day, total_min),
        "description": workout_text(plan, ftp, headline),
        "external_id": external_id(day),
        "moving_time": total_min * 60,
        "icu_ftp": int(ftp),
    }


def external_id(day: dt.date) -> str:
    return f"{EXTERNAL_PREFIX}{day.isoformat()}"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _auth(api_key: str) -> tuple[str, str]:
    # Laut API-Doku: Basic-Auth mit Benutzername „API_KEY" und dem Key als Passwort.
    return ("API_KEY", api_key)


def _err(resp: Any) -> str:
    body = ""
    try:
        body = str(resp.text)[:200]
    except Exception:  # noqa: BLE001
        pass
    return f"HTTP {resp.status_code} {body}".strip()


def _find_existing(session: Any, base: str, auth: tuple[str, str],
                   day: dt.date) -> dict[str, Any] | None:
    """Unser Eintrag für diesen Tag (per external_id), sonst None."""
    resp = session.get(
        f"{base}/events",
        params={"oldest": day.isoformat(), "newest": day.isoformat(),
                "category": "WORKOUT"},
        auth=auth, timeout=TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Kalender lesen: {_err(resp)}")
    events = resp.json() or []
    ext = external_id(day)
    for ev in events:
        if ev.get("external_id") == ext:
            return ev
    return None


def _same(existing: dict[str, Any], payload: dict[str, Any]) -> bool:
    return (str(existing.get("name") or "").strip() == payload["name"]
            and str(existing.get("description") or "").strip()
            == payload["description"].strip())


def push_today(cfg: dict[str, Any], rc: Any, day: dt.date,
               session: Any | None = None) -> PushResult:
    """Heutiges Workout nach intervals.icu (→ Zwift) schreiben. Wirft nie.

    - nicht eingerichtet → ``skipped``
    - Ruhetag / keine Wattstruktur → vorhandener Eintrag wird gelöscht
    - vorhanden und identisch → ``unchanged`` (kein erneuter Push nach Zwift)
    - vorhanden, aber anders → ``updated``; sonst ``sent``
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    api_key, athlete_id = settings(cfg)
    if not api_key:
        return PushResult("skipped", detail="intervals.icu nicht eingerichtet",
                          date=day.isoformat(), at=now)

    ftp = getattr(rc, "ftp", None)
    plan = list(getattr(rc, "power_plan", []) or [])
    sess = session or requests.Session()
    auth = _auth(api_key)
    base = f"{API_BASE}/athlete/{athlete_id}"

    try:
        existing = _find_existing(sess, base, auth, day)

        if not plan or not ftp:
            if existing and existing.get("id") is not None:
                resp = sess.delete(f"{base}/events/{existing['id']}", auth=auth,
                                   timeout=TIMEOUT_S)
                if resp.status_code not in (200, 204):
                    raise RuntimeError(f"Löschen: {_err(resp)}")
                return PushResult("deleted", name=existing.get("name"),
                                  event_id=existing.get("id"),
                                  detail="Ruhetag – Workout entfernt",
                                  date=day.isoformat(), at=now)
            reason = "Ruhetag" if not plan else "keine FTP hinterlegt"
            return PushResult("skipped", detail=reason, date=day.isoformat(), at=now)

        payload = event_payload(rc, day, int(ftp))

        if existing is not None:
            if _same(existing, payload):
                return PushResult("unchanged", name=payload["name"],
                                  event_id=existing.get("id"),
                                  date=day.isoformat(), at=now)
            resp = sess.put(f"{base}/events/{existing['id']}", json=payload,
                            auth=auth, timeout=TIMEOUT_S)
            if resp.status_code != 200:
                raise RuntimeError(f"Aktualisieren: {_err(resp)}")
            return PushResult("updated", name=payload["name"],
                              event_id=existing.get("id"),
                              date=day.isoformat(), at=now)

        # upsertOnUid ist in der API-Beschreibung ein Pflichtparameter; wir
        # haben oben schon selbst nach Duplikaten gesucht.
        resp = sess.post(f"{base}/events", params={"upsertOnUid": "false"},
                         json=payload, auth=auth, timeout=TIMEOUT_S)
        if resp.status_code != 200:
            raise RuntimeError(f"Anlegen: {_err(resp)}")
        created = resp.json() if resp.text else {}
        return PushResult("sent", name=payload["name"],
                          event_id=(created or {}).get("id"),
                          date=day.isoformat(), at=now)

    except Exception as exc:  # noqa: BLE001 – Fehler dürfen den Tagesplan nie kippen
        # today.json liegt öffentlich auf Pages: Athleten-ID aus dem Fehlertext nehmen.
        detail = str(exc).replace(athlete_id, "<id>") if athlete_id != "0" else str(exc)
        return PushResult("error", detail=detail[:300], date=day.isoformat(), at=now)


# ---------------------------------------------------------------------------
# Letztes Ergebnis merken (app_kv), damit das Dashboard es anzeigen kann
# ---------------------------------------------------------------------------

def remember(result: PushResult) -> None:
    try:
        store.set_kv(KV_KEY, json.dumps(result.to_dict(), ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


def last_result() -> PushResult | None:
    try:
        raw = store.get_kv(KV_KEY)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return PushResult(**{k: data.get(k) for k in PushResult.__dataclass_fields__})
    except (json.JSONDecodeError, TypeError):
        return None


def status_line(result: PushResult | None, today: dt.date | None = None) -> str:
    """Ein Satz fürs Dashboard: ist das heutige Workout in Zwift angekommen?"""
    today = today or dt.date.today()
    if result is None:
        return "Noch kein Workout an Zwift geschickt — der nächste Sync-Lauf erledigt das."
    stale = result.date != today.isoformat()
    when = ""
    if result.at:
        try:
            ts = dt.datetime.fromisoformat(result.at)
            when = f" ({ts:%d.%m. %H:%M} UTC)"
        except ValueError:
            pass
    if result.status in ("sent", "updated", "unchanged"):
        if stale:
            return (f"Zuletzt am {result.date} geschickt{when} — das heutige "
                    "Workout kommt mit dem nächsten Sync-Lauf.")
        return (f"Heute in Zwift bereit: **{result.name}**{when} → "
                "Zwift → Workouts → Custom → Ordner „Intervals.icu“.")
    if result.status == "deleted":
        return f"Ruhetag — das Zwift-Workout für {result.date} wurde entfernt{when}."
    if result.status == "skipped":
        return f"Übersprungen{when}: {result.detail}."
    return f"Fehler beim Senden{when}: {result.detail}"
