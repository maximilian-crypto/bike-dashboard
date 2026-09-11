# Feature-Index

> Übersicht über **alle Features**, wo sie im Code leben, **woran sie hängen** und
> wie weit sie sind. Gedacht als Einstiegspunkt: „Ich will X ändern — welche
> Dateien fasse ich an, und was geht dabei kaputt?"
>
> Nachbardokumente: [`CLAUDE.md`](CLAUDE.md) (Projektkontext),
> [`OFFENE_AUFGABEN.md`](OFFENE_AUFGABEN.md) (was noch zu tun ist),
> [`SICHERHEIT.md`](SICHERHEIT.md) (Datenschutz-Prüfung).

---

## 1. Datenfluss auf einen Blick

```
 Strava API ─┐                                   ┌─▶ dashboard.py ........ PC-Auswertung (Streamlit)
             ├─▶ sync.py ─▶ store.py (SQLite/PG) ─┤
 Whoop API ──┘                  │                └─▶ build_today.py ─▶ mobile/today.json
                                │                                            │
                                ├─▶ dataprep.py ─▶ load ─▶ form ─────┐       ├─▶ mobile/ride.html (PWA)
                                │                                    │       │
 Open-Meteo ────▶ weather.py ───┼─▶ daytime.py ──┐                   │       └─▶ send_report.py ─▶ ntfy ─▶ Handy
                                │                ├─▶ recommend.py ◀──┘
 OpenRouteService ─▶ routing.py ┘                └─▶ report.py
```

**Eine Regel erklärt fast alles:** `recommend.py` ist das Herz. Fast jedes Feature
liest entweder daraus (`today.json`, Report, Dashboard) oder füttert es
(`load`, `form`, `zones`, `dataprep`).

---

## 2. Feature-Tabelle

Legende Reife: **stabil** = im Alltag bewährt · **neu** = fertig, aber noch nicht
am echten Gerät im Einsatz · **beta** = bewusst unfertig.

| # | Feature | Logik-Modul | Oberfläche | Hängt ab von | Fließt ein in | Tests | Reife |
|---|---|---|---|---|---|---|---|
| 1 | **Tagesempfehlung** (Typ, Dauer, Zone, RPE) | `bikedash/recommend.py` | Tab „Heute" · `today.json` · Report | `dataprep`, `form`, `zones`, Whoop-Recovery | ①→ alles darunter | `test_recommend.py` | stabil |
| 2 | **Trainingslast** (Banister-TRIMP) | `bikedash/load.py` | Tab „Trainingsbelastung" | HF + Dauer je Fahrt | ③ Form | `test_load.py` | stabil |
| 3 | **Form/Fitness** (CTL/ATL/TSB) | `bikedash/form.py` | Tab „Trainingsbelastung" | ② Trainingslast | ① Empfehlung, Report | `test_form.py` | stabil |
| 4 | **HF-Zonen** (LTHR → Karvonen → %max) | `bikedash/zones.py` | überall, wo bpm steht | Whoop Max-HF/Ruhepuls, optional LTHR aus Config | ①, ⑨ Shift, PWA | `test_zones.py` | stabil |
| 5 | **Wetter am Start** | `bikedash/weather.py` | Tab „Heute" · `today.json` | Open-Meteo, Heimat-Koordinate | ⑥ Tageszeit, ⑦ Route, Report | `test_weather_hourly.py` | stabil |
| 6 | **Tageszeit-Empfehlung** „wann fahren?" | `bikedash/daytime.py` | Tab „Heute" · `today.json` · **Report-Push** | ⑤ Stundenraster, ① Dauer | Report, PWA-Banner | `test_daytime.py` | **neu** |
| 7 | **Windkluge Rundkurse** | `bikedash/routing.py` | Tab „Heute" (Karte) · PWA „Route" | ORS-Key, Heimat-Koordinate, ⑤ Windrichtung | GPX-Export | `test_routing.py` | stabil |
| 8 | **Live-Ride-PWA** (Tacho, BLE-Puls/Kadenz, Karte) | — (alles in der Seite) | `mobile/ride.html` | `today.json`, Web Bluetooth, GPS | ⑨–⑪ | via ⑨ | stabil |
| 9 | **Gangempfehlung (Shift)** — Puls **und** Kadenz | `bikedash/shift.py` | PWA-Kachel „Gang" | ④ Zielzone, ① Kadenzband, BLE-Sensoren | — | `test_shift.py`, `test_shift_pwa.py` | **neu** |
| 10 | **Windrose** (heading-up) | — (in `ride.html`) | PWA-Kachel „Wind" | GPS-Kurs, Open-Meteo | — | — | beta |
| 11 | **Steigung** (Neigungssensor, kalibrierbar) | — (in `ride.html`) | PWA-Kachel „Steigung" | `DeviceOrientation` | — | — | beta |
| 12 | **Orden & Meilensteine** | `bikedash/milestones.py` | Tab „Orden" · `today.json` · PWA-Banner | Gesamtdistanz (ganze Historie) | — | `test_milestones.py` | stabil |
| 13 | **Verschleiß-/Wartungs-Tracker** | `bikedash/maintenance.py` | Tab „Wartung" | Gesamtdistanz, `app_kv` | — | `test_maintenance.py` | stabil |
| 14 | **Wind-Labor** (Wind vs. Tempo) | `bikedash/windlab.py` | Tab „Wind-Labor (Beta)" | `wind_segments`-Tabelle | — | — | beta |
| 15 | **Morgen-Report** (ntfy-Push) | `bikedash/report.py` + `send_report.py` | Handy-Push | ①, ③, ⑤, **⑥** | — | — | **neu** (⑥ ergänzt) |
| 16 | **KI-Coach** | `bikedash/coach.py` | Tab „Coach" | Claude API, alle DataFrames | — | — | stabil |
| 17 | **Zugangsschutz** (Passwort) | `bikedash/webauth.py` | vor dem ganzen Dashboard | `APP_PASSWORD` | — | — | stabil |
| 18 | **Datensicherung** | `bikedash/backup.py` | Tab „Einrichtung" | SQLite-Datei | — | `test_backup.py` | stabil |
| 19 | **Sync & OAuth** | `strava.py`, `whoop.py`, `auth.py`, `config.py`, `store.py` | Tab „Einrichtung" · `sync.py` · Actions | Strava-/Whoop-Zugangsdaten | **alles** | `test_store.py`, `test_config.py` | stabil |

---

## 3. Verknüpfungen, die man leicht übersieht

Das sind die Stellen, an denen eine Änderung *woanders* etwas kaputt macht:

| Änderst du … | … ändert sich automatisch mit | Warum |
|---|---|---|
| `TEMPLATES` in `recommend.py` (Kadenz, Zone, Dauer) | PWA-Zielbänder, Shift-Kachel, Report, `today.json` | Die PWA zieht `cadence_low/high` und die Zone aus `today.json` — sie hat **keine** eigenen Zielwerte. |
| `bikedash/shift.py` (Matrix, Toleranzen) | PWA-Kachel „Gang" | Die Matrix wandert über `today.json` in die PWA. Die Kopie in `ride.html` ist nur der Offline-Notnagel — **`test_shift.py` schlägt fehl**, wenn beide auseinanderlaufen. Dann den Block zwischen `SHIFT_MATRIX_DEFAULT:BEGIN/END` aus `shift.matrix_payload()` neu erzeugen. |
| `WEEKDAY_WINDOW` / `WEEKEND_WINDOW` in `daytime.py` | Report-Push, Dashboard-Kachel, PWA-Banner | Eine einzige Quelle, drei Anzeigeorte. |
| Felder in `build_today.py` | PWA | `today.json` ist der **einzige** Kanal Dashboard → PWA. Neue Felder immer optional behandeln (die PWA lädt evtl. eine alte Datei aus dem Cache). |
| Design-Tokens oben in `dashboard.py` | — | Spiegeln die CSS-Variablen in `ride.html`. Beide von Hand synchron halten. |
| `mobile/ride.html` | Service Worker | Bei größeren Änderungen `CACHE` in `mobile/sw.js` hochzählen (aktuell `ride-v4`). |
| Alles, was in `today.json` landet | **Öffentlichkeit** | Die Datei liegt öffentlich (siehe [`SICHERHEIT.md`](SICHERHEIT.md)). Nie Koordinaten oder Routen hineinschreiben. |

---

## 4. Wo neue Logik hingehört

1. **Rechnen** → neues Modul in `bikedash/` — rein, ohne Streamlit-Import, testbar.
2. **Testen** → `tests/test_<modul>.py`; die `conftest.py`-Fixture lenkt auf eine Wegwerf-DB.
3. **Anzeigen (PC)** → `dashboard.py` ruft nur auf und rendert.
4. **Anzeigen (Handy)** → Feld in `build_today.py` ergänzen, in `ride.html` auslesen.
5. **Kleindaten speichern** → `store.get_kv` / `set_kv` statt neuer Tabelle.

---

## 5. Datenhaltung

| Tabelle | Inhalt | Gefüllt von |
|---|---|---|
| `strava_activities` | Fahrten inkl. Roh-JSON | `strava.sync` |
| `whoop_recovery` | Recovery, HRV, Ruhepuls | `whoop.sync` |
| `whoop_cycles` | Tageszyklen, Max-HF | `whoop.sync` |
| `whoop_workouts` | Whoop-Einheiten | `whoop.sync` |
| `sync_state` | Zeitstempel, Max-HF-Cache | `sync.py` |
| `app_kv` | Kleinkram als JSON (Wartung, OAuth-Tokens in der Cloud) | `maintenance`, `config` |
| `wind_segments` | Segmente fürs Wind-Labor | `windlab` |

Lokal SQLite (`data/bikedash.db`), beim Hosting Postgres über `DATABASE_URL`
(`bikedash/store.py` entscheidet das automatisch).
