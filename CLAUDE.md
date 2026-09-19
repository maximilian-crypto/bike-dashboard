# CLAUDE.md — Projektkontext für Claude Code

> Diese Datei wird von Claude Code automatisch geladen. Sie fasst zusammen, was
> das Projekt tut, was bereits umgesetzt ist, welche Entscheidungen bewusst so
> getroffen wurden, **woran es aktuell hakt** und was als Nächstes zu tun ist.
>
> Ergänzende Detail-Übergabe (kompletter Code + Diff der neuen Features):
> **`HANDOFF_NEUE_FEATURES.md`**.


---

## 1. Was das Projekt macht

Ein **persönliches Fahrrad-Dashboard**, das Trainingsdaten aus **Strava**
(Fahrten, GPS, Leistung) und Körperdaten aus **Whoop** (Recovery, HRV,
Ruhepuls, Max-HF) zusammenführt und daraus konkrete Trainingsentscheidungen
ableitet. Alle Daten bleiben lokal (SQLite) bzw. in einer eigenen Postgres-DB.

Zwei Oberflächen:

| Oberfläche | Datei | Zweck |
|---|---|---|
| **Analyse-Dashboard** | `dashboard.py` (Streamlit) | Auswertung am PC: Tagesempfehlung, Leistung, Belastung, Erholung, Wind-Labor, Orden, Wartung, KI-Coach |
| **Live-Ride-PWA** | `mobile/ride.html` | On-Bike-Screen am Handy: Tempo, Puls (BLE), Kadenz (BLE), Windrose, Steigung, Gang, Karte |

Verbunden werden beide über **`build_today.py`** → schreibt `mobile/today.json`
(Tagesempfehlung + HF-Zonen + Wetter + Meilenstein). Die PWA lädt diese Datei
same-origin von GitHub Pages.

**Kernidee:** Die Tagesempfehlung (`bikedash/recommend.py`) ist bewusst
*deterministisch und erklärbar* — kein LLM, keine Blackbox. Jede Entscheidung
kommt mit einer Begründung, die im Dashboard angezeigt wird.

---

## 2. Architektur / Repo-Karte

```
bike-dashboard/
├─ bikedash/              # Programmlogik (reine, testbare Module)
│  ├─ config.py           # Zugangsdaten + Token-Speicher
│  ├─ store.py            # SQLite lokal / Postgres via DATABASE_URL
│  ├─ auth.py, webauth.py # OAuth-Flows
│  ├─ strava.py, whoop.py # API-Anbindung + Sync
│  ├─ dataprep.py         # Rohtabellen -> DataFrames, Indoor-/Outdoor-Erkennung
│  ├─ load.py             # Trainingslast auf TSS-Skala (1 h Schwelle = 100)
│  ├─ form.py             # CTL/ATL/TSB (Fitness/Ermüdung/Form)
│  ├─ zones.py            # HF-Zonen (LTHR > Karvonen/HRR > %max)
│  ├─ recommend.py        # Tagesempfehlung (Kern-Heuristik)
│  ├─ season.py           # Saisonplan: Wochenlast-Sollkurve aufs Zieldatum
│  ├─ power.py            # Leistungszonen (%FTP) + abfahrbare Einheiten-Struktur
│  ├─ routing.py          # windkluge Rundkurse via ORS
│  ├─ weather.py          # Open-Meteo
│  ├─ windlab.py          # Wind-Performance-Analyse
│  ├─ fitness.py          # NEU: Fitness-Index (Fortschritt aus Physiologie)
│  ├─ milestones.py       # NEU: Distanz-Meilensteine & Orden
│  ├─ maintenance.py      # NEU: Verschleiss-/Wartungs-Tracker
│  ├─ zwift.py            # NEU: Tagesworkout → intervals.icu-Kalender → Zwift-Bibliothek
│  ├─ coach.py            # KI-Coach (Claude API)
│  ├─ report.py           # Morgen-Report (ntfy-Push)
│  └─ backup.py           # Datensicherung
├─ dashboard.py           # Streamlit-App (ein grosses Skript, Tabs via st.tabs)
├─ build_today.py         # schreibt mobile/today.json
├─ sync.py, connect.py    # CLI: Daten holen / Konten verbinden
├─ mobile/                # Live-Ride-PWA (ride.html, sw.js, manifest.json)
├─ tests/                 # pytest, isolierte Wegwerf-DB via conftest.py
├─ *.ps1                  # Windows-Helfer (siehe Abschnitt 5 — AKTUELLER BLOCKER)
└─ .github/workflows/     # sync.yml (Sync + Tagesplan + Morgen-Report), keepalive.yml
```

**Trainingslast — eine Skala für alles (seit Indoor-Saison 2026/27):**
Jede Einheit wird auf **TSS** normiert: *eine Stunde an der Schwelle = 100*.
Quellen in dieser Reihenfolge (`dataprep.prep_rides`, Spalte `load_source`):
`power` (echte Wattdaten, erkennbar an Stravas `device_watts`, braucht
`athlete.ftp`) → `hr` (Banister-TRIMP, normiert über `load.hr_tss`) →
`suffer_score` → grobe Schätzung. Wichtig: Die TSB-Schwellen in `recommend.py`
stammen aus der TSS-Welt (Allen/Coggan). Rohes TRIMP läuft ~1,6-mal heißer —
wer die Normierung entfernt, bremst den Athleten unabsichtlich aus.

**Indoor ≠ Outdoor:** `dataprep.is_indoor()` erkennt Rollenfahrten
(`VirtualRide` bzw. Stravas `trainer`-Flag). `prep_rides` liefert
`is_indoor`, `distance_km_indoor`, `distance_km_outdoor`. Der Verschleiß-
Tracker gewichtet Indoor-km je Bauteil über `indoor_factor` (Antrieb anteilig,
Reifen/Bremsen/Züge gar nicht) — siehe `maintenance.odometer()`.

**Zwei Steuerebenen, bewusst getrennt:** `season.py` sagt, **wie viel** Last
diese Woche anstehen sollte (Richtung, progressive Überlast bis zum Saisonstart);
`recommend.py` entscheidet über Whoop/TSB, **ob heute** davon etwas geliefert
wird (Sicherheit). Gesteuert wird über Last, nicht über Stunden — 2 h Grundlage
und 2 h Intervalle sind nicht derselbe Reiz. Der Plananker (Startdatum +
Ausgangslast) liegt in `app_kv`, damit die Kurve Richtung behält statt dem
rollenden Mittelwert zu folgen. Steigerung ist **prozentual** (+10 %/Woche), nicht
als absolute CTL-Rampe: „+3 bis +5 CTL/Woche" stammt von trainierten Fahrern und
ist bei niedrigem Ausgangsniveau eine Vervielfachung.

**Drinnen Watt, draussen Herzfrequenz.** `zones.py` liefert HF-Zonen (draussen
ohne Powermeter die einzige Groesse), `power.py` Leistungszonen als Anteil der
FTP plus eine abfahrbare Struktur (`structure()`: Einfahren, Intervalle bzw.
Hauptteil, Ausfahren). Auf der Rolle ist Watt die richtige Waehrung: die
Herzfrequenz hinkt dem Reiz 1-2 min hinterher und driftet mit der Hitze. Ohne
hinterlegte `athlete.ftp` bleiben alle Wattfelder leer — nie erzwingen.

**Tagesworkout automatisch in Zwift (seit 2026-09-18):** `bikedash/zwift.py`
übersetzt `Recommendation.power_plan` in die native intervals.icu-Workout-
Syntax (ein Schritt je Block, Wattziel als **Anteil der FTP**, Kadenz als
Bandmitte) und legt den Eintrag per API im intervals.icu-Kalender an;
intervals.icu schiebt ihn über seine offizielle Zwift-Anbindung in die Zwift-
Bibliothek (Workouts → Custom → Ordner „Intervals.icu“), auch aufs iPhone.
Läuft in `build_today.py` (Actions alle 4 h), idempotent über
`external_id = bikedash-JJJJ-MM-TT`: pro Tag ein Eintrag, unverändert = kein
erneuter Push, Ruhetag = Eintrag wird gelöscht. Ergebnis steht in `today.json`
(`zwift`) und `app_kv` (`zwift_last_push`), das Dashboard zeigt es unter dem
Wattplan. Prozent statt Watt, weil Zwift im ERG mit *seiner* FTP multipliziert —
die Zwift-FTP muss `ATHLETE_FTP` entsprechen. Bewusst **kein** `.zwo`-Dateiweg
(braucht einen PC, der Zwift startet) und **keine** inoffizielle Zwift-API.
Einrichtung: Secrets `INTERVALS_API_KEY` + `INTERVALS_ATHLETE_ID`, DEPLOY.md
Schritt 8.

**Morgen-Report ereignisgesteuert (seit 2026-09-18):** kein eigener
Zeitplan mehr (`report.yml` gelöscht). Der Sync-Workflow läuft morgens alle
30 Minuten (`*/30 5-9 * * *` UTC) und ruft `send_report.py --if-due`;
`report.due()` entscheidet: heute schon gesendet → nein; heutige Whoop-Recovery
in der DB → senden; Frist 10:00 deutscher Zeit erreicht → senden mit Hinweis
„Recovery fehlt noch"; nie vor 06:00. Marker `report_sent_date` in `app_kv`.
Grund: die alte feste Uhrzeit 06:30 lag vor der Whoop-Recovery und hätte still
mit dem Wert von gestern gerechnet. Erste Zeile trägt die Entscheidung (Einheit,
Dauer, Watt, Zwift bereit), Wetter nur an Fahrtagen. Kanal ntfy (Secret
`NTFY_TOPIC`), optional `DASHBOARD_URL` als Klick-Ziel. Nutzerentscheid
(Sept 2026): ntfy, morgens, spätestens 10:00.

**Fitness-Index — Fortschritt statt Fleiß (seit 2026-09-19):** `bikedash/fitness.py`
beantwortet die Frage, die CTL offen lässt. CTL misst, **wie viel** trainiert wird,
und steigt auch bei jahrelangem Plateau; der Index misst, **ob der Athlet besser
wird**. Fünf Teilwerte, Gewichte in Klammern: Effizienz (30) = Leistung je
Herzschlag (Friels Efficiency Factor, draußen mit aus Tempo/Steigung/Masse
geschätzter Leistung), Kapazität (25) = mittlere Tageslast, Ermüdungsresistenz
(20) = Aerobic Decoupling aus den Strava-Streams, Regeneration (15) = HRV- und
Ruhepuls-Basislinie aus Whoop, Konsistenz (10) = Trainingswochen von zwölf.

Drei Konstruktionsentscheidungen tragen das Ganze:
1. **Fester Anker statt gleitendem Bezug** (`app_kv: fitness_anchor`, aus den
   ersten acht Wochen). Ein mitwandernder Median macht jede Verbesserung sofort
   zur neuen Normalität — der Index klebte für immer bei 50. Gleiche Überlegung
   wie beim Plananker in `season.py`.
2. **42-Tage-Median je Teilwert.** Eine einzelne Fahrt bewegt den Index um
   Bruchteile eines Punkts. Das ist der ganze Unterschied zu einem Zähler und
   war die ausdrückliche Anforderung (nicht „+1 pro Workout").
3. **Kapazität über die mittlere Tageslast, nicht über CTL.** CTL hat 42 Tage
   Zeitkonstante und steht nach dem Ankerfenster erst bei ~74 % seines Endwerts.
   Gegen diesen Anker gemessen zeigte der Index einem Fahrer, der ein Jahr lang
   *exakt gleich* trainiert, „+47 % Kapazität". Beide Seiten nutzen jetzt
   denselben rampenfreien Schätzer.

Skalen (`FULL_EFF` & Co.) sind so gespannt, dass eine sehr gute Saison bei ~85
landet, nicht bei 99 — ein Index am Anschlag kann im zweiten Jahr nichts mehr
zeigen. Fehlende Signale (kein Whoop, keine ausgewerteten Streams) kosten keine
Punkte: die Gewichte werden auf die vorhandenen Teilwerte normiert.

**Wichtige Konventionen:**
- Design-Tokens (`C_IN`, `C_ABOVE`, `PANEL_A`, `MUTED`, `ACCENT` …) stehen oben
  in `dashboard.py` und spiegeln 1:1 die CSS-Variablen in `mobile/ride.html`.
- Kleindaten brauchen **kein Schema-Change**: `store.get_kv` / `store.set_kv`
  (Tabelle `app_kv`) als Schlüssel-Wert-Ablage nutzen.
- Kommentare und UI-Texte sind **deutsch**, Code-Bezeichner englisch.
- Neue Logik gehört in ein `bikedash/`-Modul (rein + testbar), nicht in
  `dashboard.py`. Das Dashboard rendert nur.

---

## 3. Was bisher umgesetzt wurde

### Bestand (vor dieser Arbeitsphase)
Tagesempfehlung mit Route, Leistungs-/Fortschrittsanalyse, Trainingsbelastung
(CTL/ATL/TSB), Erholung, Wind-Labor (Beta), KI-Coach, Morgen-Report via ntfy,
Live-Ride-PWA mit BLE-Puls/-Kadenz und Karte.

### Neu in Branch `claude/fahrrad-app-neue-feature-ptpp0w` (Commit `544201d`)

| # | Feature | Wo | Status |
|---|---|---|---|
| 1 | **Verschleiss-Tracker** — km/Bauteil, Wartungs-Ampel, „gewechselt"-Reset, editierbare Intervalle | `bikedash/maintenance.py` + Tab „Wartung" | Code fertig, mit Synthetikdaten verifiziert |
| 2 | **Orden & Meilensteine** — 31 benannte Orden (Geo/Sci-Fi/Fantasy/Astro) + generische ~40 km-Nahziele | `bikedash/milestones.py` + Tab „Orden" + `today.json` | Code fertig, mit Synthetikdaten verifiziert |
| 3 | **Kadenz-Untergrenze 90 → 85** für TEMPO/THRESHOLD | `bikedash/recommend.py` | fertig |
| 4 | **Windrose** — heading-up, aufrechte N/O/S/W, relativer Windpfeil | `mobile/ride.html` | rendert, **Zielbild noch offen** |
| 5 | **Steigung** — aus DeviceOrientation-Pitch, kalibrierbar (Kachel antippen = 0 %) | `mobile/ride.html` | rendert, **am Handy ungetestet** |
| 6 | **Gangempfehlung (Shift)** — leichter/halten/schwerer aus Kadenz vs. Zielband | `mobile/ride.html` | rendert, **braucht BLE-Kadenzsensor** |

### Neu (2026-09-18): Tagesworkout automatisch in die Zwift-Bibliothek

| # | Feature | Wo | Status |
|---|---|---|---|
| 7 | **Zwift-Zustellung via intervals.icu** — Tagesworkout landet ohne Zutun unter Zwift → Workouts → Custom → „Intervals.icu“ | `bikedash/zwift.py`, `build_today.py`, Einrichtung „5) Zwift“, Statuszeile unter dem Wattplan | Code fertig, Tests grün, Dashboard im Browser geprüft. **Offen: einmalige Einrichtung durch den Nutzer + Sichtprüfung am Handy** (Abschnitt 6, Schritt 0) |

| 9 | **Fitness-Index** — ein Fortschrittswert aus fünf physiologischen Signalen, Verlaufskurve, Teilwert-Aufschlüsselung und Klartext-Sätzen (bei 139 bpm fährst du inzwischen 28,0 km/h statt 24,7) | `bikedash/fitness.py`, Tab „Fitness-Index", `today.json` (`fitness`), Zeile im Morgen-Report | Code fertig, 29 Tests grün, Tab mit synthetischer Jahreshistorie im Browser geprüft. **Offen: Sichtprüfung mit echten Daten + einmal „Mehr Fahrten auswerten" drücken** (Abschnitt 6, Schritt 0b) |
| 10 | **Dunkles Streamlit-Theme** (`.streamlit/config.toml`) — die Diagramme waren app-weit hell in einer dunklen App | `.gitignore`, `.streamlit/config.toml` | fertig, im Browser geprüft |

| 8 | **Morgen-Report ereignisgesteuert** — Push, sobald die heutige Whoop-Recovery da ist, spätestens 10:00; erste Zeile = Entscheidung | `bikedash/report.py`, `send_report.py --if-due`, `sync.yml` | Code fertig, Tests grün. **Offen: `NTFY_TOPIC` als Actions-Secret + ntfy-App abonnieren** |

**Tests:** 168 grün (`python -m pytest -q`), inkl. Suites
`tests/test_milestones.py`, `tests/test_maintenance.py`, `tests/test_dataprep.py`, `tests/test_season.py`, `tests/test_power.py`, `tests/test_zwift.py`, `tests/test_report.py` und `tests/test_fitness.py`.

**Zwift-Zustellung verifiziert (2026-09-18, Lauf #346):** `today.json` meldet
`zwift.status = sent`, Event-ID 136989140 im intervals.icu-Kalender.

---

## 4. Getroffene Entscheidungen (und warum)

1. **Meilenstein-Modell: benannte Orden UND generische Nahziele.**
   Nur benannte Orden hätte bedeutet, dass das nächste Ziel manchmal Hunderte km
   weg ist. Deshalb zusätzlich generische Schritte alle ~40 km (±40 % Varianz,
   deterministisch aus dem Index — stabil über Läufe, keine Zufallszahlen in der
   DB). Stellschrauben: `GENERIC_STEP_KM`, `GENERIC_VARIANCE` in `milestones.py`.

2. **Orden-Themen gemischt:** Radsport/Geografie, Sci-Fi, Fantasy, Astronomie —
   von „Ein Shai-Hulud" (0,4 km) bis „Erde → Mond" (384.400 km). Filterbar im Tab.

3. **Verschleiss-Persistenz über `app_kv`, nicht über eine neue Tabelle.**
   Vermeidet eine Schema-Migration für eine kleine JSON-Liste. Jedes Bauteil
   speichert `installed_km` (Stand beim letzten Wechsel); Verschleiss ist die
   Differenz zum aktuellen Gesamtstand — dadurch ist ein Reset trivial und die
   Historie muss nicht mitgeschrieben werden.

4. **Gesamtdistanz für Orden/Wartung ignoriert den Zeitraum-Filter.**
   Der Sidebar-Filter steuert die Analyse-Tabs; Orden und Verschleiss beziehen
   sich immer auf die **ganze** Historie (`total_km_all` in `dashboard.py`).

5. **`today.json` bleibt route-frei.** Die Datei liegt öffentlich auf GitHub
   Pages; eine Route ab Zuhause würde die als Secret gehaltene Heimat-Koordinate
   veröffentlichen. Das neue `milestone`-Feld enthält daher nur aggregierte km.

6. **Kadenz 85 statt 90:** Der grüne „im Soll"-Bereich soll früher greifen —
   Erfolgserlebnis statt Dauerwarnung. Wirkt automatisch bis in die PWA, weil
   diese ihre Zielwerte aus `today.json` (`cadence_low`/`cadence_high`) zieht.

7. **Windrose heading-up mit aufrechten Labels.** Erster Versuch drehte die
   Buchstaben mit (unlesbar); jetzt folgt nur die *Position* der Fahrtrichtung,
   die Beschriftung bleibt aufrecht.

8. **Steigung kalibrierbar statt absolut.** Der Handyhalter sitzt nie gleich —
   deshalb Tare-Button (Offset in `localStorage`) statt fixer Annahme.

9. **Fitness-Index misst Fortschritt, nicht Fleiß.** Ausdrücklicher Wunsch des
   Nutzers: ein Wert, der auf etwas beruht und nicht „+1 pro Workout" zählt.
   Deshalb fester Anker, 42-Tage-Fenster und sättigende Skala — Begründung und
   Fallstricke stehen ausführlich oben in Abschnitt 2 und im Modulkopf von
   `bikedash/fitness.py`.

10. **`.gitignore` hatte `config.toml` ohne Anker** und schluckte damit auch
   `.streamlit/config.toml`. Folge: Streamlit lief mit seinem hellen Vorgabe-Theme
   und überschrieb das sorgfältig gebaute Plotly-Template `bikedash` — HELLE
   Diagramme in einer dunklen App, quer durch alle Tabs. Muster ist jetzt
   `/config.toml`; das Theme liegt eingecheckt in `.streamlit/config.toml`.

---

## 5. Ehemaliger „Blocker": PowerShell war NICHT die Ursache

> **Nachtrag (2026-08-19, verifiziert):** Die frühere Diagnose „alles hakt wegen
> fehlender PowerShell" war falsch. Die `.ps1`-Skripte starten nur Python und
> enthalten keine Programmlogik — sie können nichts kaputt machen. Die echten
> Ursachen sind gefunden und behoben, siehe **Abschnitt 5b**.

Der Vollständigkeit halber der ursprüngliche Umgebungs-Hinweis:

Konkret fehlt in der Cloud-Session:

- **Keine PowerShell** (`pwsh`/`powershell` nicht vorhanden) → die vier
  Helfer-Skripte konnten **nie ausgeführt werden**:
  - `start_dashboard.ps1` — startet Streamlit über `.venv\Scripts\python.exe`
  - `run_sync.ps1` — vom Taskplaner aufgerufener Sync
  - `setup_task.ps1` — registriert den geplanten Sync (Windows-Aufgabenplanung)
  - `setup_report_task.ps1` — registriert den täglichen Morgen-Report
  Alle vier referenzieren `.venv\Scripts\python.exe` und
  `Register-ScheduledTask` — das ist **reines Windows**.
- **Keine `config.toml`, keine `tokens.json`, leeres `data/`** → keine echten
  Strava-/Whoop-Zugangsdaten, keine echte Datenbank.

**Folge:** Es gab **keinen End-to-End-Test gegen echte Fahrdaten**. Verifiziert
wurde nur mit *synthetischen* Fahrten (130 Ritte, 5.200 km) auf Linux —
Screenshots der Tabs „Orden" und „Wartung" sahen korrekt aus, 46 Tests grün.
Der komplette Windows-Pfad (venv, `.ps1`-Start, Taskplaner, echter Sync) ist
**ungetestet**.

### Ehrlicher Zusatz: das erklärt nicht *alle* gemeldeten Symptome

Gemeldet wurde: „Shift funktioniert nicht, Steigung fehlt, alle Dashboard-Features
fehlen komplett." Dafür gibt es **separate, verifizierte** Ursachen — bitte nicht
allein auf PowerShell schieben:

| Symptom | Wahrscheinliche Ursache |
|---|---|
| **Alle Dashboard-Features fehlen** | Lokaler Checkout steht auf dem alten Branch, bzw. der gehostete Streamlit-Deploy läuft von `main`. Der Code ist gepusht, aber nicht ausgecheckt/deployt. |
| **Steigung fehlt** | Braucht `DeviceOrientation` **und** erteilte Sensor-Berechtigung (iOS: Nutzergeste + Prompt). Am Desktop gibt es keine Neigung → Kachel bleibt auf „—". |
| **Shift funktioniert nicht** | `updateShift()` braucht `cadVal`, das **ausschliesslich** von einem gekoppelten BLE-Kadenzsensor (CSC) kommt. Ohne Sensor bleibt die Kachel auf „warte auf Kadenz". |
| **Windrose nicht wie vorgestellt** | Design-Frage, kein Bug — Zielbild ist noch nicht spezifiziert. |

---

## 5b. Tatsächliche Ursachen — gefunden und behoben (2026-08-19)

Alles unten wurde in einer Linux-Session **real ausgeführt und im Browser
verifiziert** (Streamlit gestartet, PWA mit simulierten Sensordaten getestet).

| # | Befund | Warum es das Symptom erklärt | Behebung |
|---|---|---|---|
| 1 | **Feature-Branch war nie in `main`** — die 3 Commits lagen nur auf `claude/fahrrad-app-neue-feature-ptpp0w` | Streamlit-Deploy und GitHub Pages liefern aus `main` → dort gab es Orden/Wartung schlicht nicht | Branch zusammengeführt |
| 2 | **`initMap()` warf `L is not defined`**, wenn Leaflet vom CDN fehlte; es stand in der Startkette `… initMap(); startGeo(); loadToday();` | Ein Wurf dort brach die **restliche Kette ab** → kein GPS, keine HF-Zonen, kein Meilenstein. Genau das Bild „alle Features fehlen" | Leaflet-Prüfung + Startkette einzeln per `boot()` abgesichert |
| 3 | **`onPos()` griff ungeprüft auf `marker`/`trail`/`map` zu** | Ohne Leaflet warf **jedes GPS-Update** → Distanz, Zeit, Ø-Tempo, Wind und Navigation standen still | Karten-Zugriffe mit `if(map)` abgesichert |
| 4 | **Service Worker cachte Leaflet nie** (`unpkg` war von der Cache-Strategie ausgenommen) | Ohne Empfang fehlte Leaflet → Fall 2/3 trat unterwegs zuverlässig ein | Leaflet jetzt cache-first (`ride-v3`) |
| 5 | **Neigungs-Listener wurde nur beim Antippen registriert** | Steigungs-Kachel blieb auf „—", obwohl Android gar keine Berechtigung braucht | `autoEnableOrientation()` beim Start (iOS wartet weiterhin auf die Nutzergeste) |
| 6 | **`Math.tan(beta)` ohne Begrenzung** | Aufrecht montiert ist `beta≈90°` → vor dem Kalibrieren stand Unsinn in der Kachel | Auf ±40 % geklemmt; unkalibriert zeigt die Kachel ehrlich „—" |
| 7 | **Orden < 10 km zeigten „0 km"** | „Ein Shai-Hulud" (0,4 km) sah kaputt aus | `km_label()` mit Nachkommastelle |
| 8 | **Zwei der drei Fortschrittsbalken waren immer leer** | Ziele 2 und 3 liegen definitionsgemäss vor ihrem Startpunkt | Balken nur noch fürs nächste Ziel |
| 9 | **PWA-Banner formulierte „noch 15 km bis 5.215 km"** | Generische Nahziele heissen bereits nach ihrer Kilometerzahl | `next_kind` in `today.json`; Text danach formuliert |

**Nicht kaputt (verifiziert):** Shift/Gangempfehlung arbeitet korrekt gegen das
Zielband 85–95 (leichter/halten/schwerer), die Windrose rechnet Gegen-/Rücken-/
Seitenwind richtig, `build_today.py` schreibt das `milestone`-Feld, und die Tabs
„Orden" und „Wartung" rendern mit echten Kilometern. **Shift braucht weiterhin
einen BLE-Kadenzsensor** — ohne Sensor gibt es keine Kadenz, das ist Physik,
kein Bug.

---

## 6. Was als Nächstes zu tun ist

### Schritt 0 — Zwift-Zustellung scharf schalten (einmalig, ~10 Minuten)
1. Konto auf intervals.icu → **Settings → Zwift → Connect** (Zugriff in Zwift bestätigen).
2. **Settings → Developer Settings**: API-Key erzeugen, Athleten-ID (`i12345`) notieren.
3. GitHub → Settings → Secrets → Actions: `INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID`.
4. **FTP in Zwift = `ATHLETE_FTP`** (170) prüfen — Zwift rechnet die Wattziele daraus.
5. Actions → „Sync Strava + Whoop“ → Run workflow. Im Log: `Zwift-Workout: sent – Bikedash …`.
6. Zwift am Handy: Workouts → Custom → Ordner „Intervals.icu“ → Eintrag antippen.

Was aus der Sandbox heraus **nicht** verifiziert werden konnte (intervals.icu
ist dort netzseitig gesperrt): der echte API-Aufruf und die Sichtprüfung in
Zwift. Die API-Semantik stammt aus der OpenAPI-Spezifikation von intervals.icu
(Basic-Auth `API_KEY:<key>`, `POST/PUT /api/v1/athlete/{id}/events`,
Workout als `description` in nativer Syntax). Schlägt Schritt 5 fehl, steht der
Fehlertext in `mobile/today.json` unter `zwift.detail`.

### Schritt 0b — Fitness-Index mit echten Daten scharf schalten (einmalig)
1. Dashboard öffnen → Tab **„Fitness-Index"**. Beim ersten Aufruf wird das
   **Ausgangsniveau** aus den ersten acht Wochen deiner Historie festgeschrieben
   (steht im Aufklapper „Wie wird das gerechnet?"). Sieht der Zeitraum unpassend
   aus — lange Pause, Materialwechsel — dort einmal **„Ausgangsniveau neu setzen"**.
2. Gewicht eintragen: Einrichtung → **Körpergewicht in kg**. Ohne den Wert
   schätzt der Index die Außenleistung mit 88 kg Systemmasse. Fürs Hosting
   zusätzlich als Secret `ATHLETE_WEIGHT_KG` (Streamlit **und** Actions).
3. Unten im Tab mehrfach **„Mehr Fahrten auswerten"** drücken — das holt die
   Fahrtverläufe von Strava und schaltet die **Ermüdungsresistenz** frei
   (10 Fahrten pro Klick, Stravas Kontingent). Ohne diesen Schritt fehlt einer
   von fünf Teilwerten; der Index rechnet dann ohne ihn weiter.
4. Gegenprobe: Stimmt die Effizienzkurve mit deinem Gefühl überein? Fährst du
   bei gleichem Puls wirklich schneller als vor einem Jahr?

### Schritt 1 — Umgebung am PC herstellen (Blocker auflösen)
```powershell
git fetch origin
git checkout claude/fahrrad-app-neue-feature-ptpp0w
git pull

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

copy config.example.toml config.toml    # ausfüllen: Strava, Whoop, ORS, Heimat-Koordinaten
.\.venv\Scripts\python.exe connect.py   # Browser-Login Strava + Whoop
.\.venv\Scripts\python.exe sync.py      # echte Daten holen
```

### Schritt 2 — verifizieren, was bisher nur synthetisch getestet ist
```powershell
.\.venv\Scripts\python.exe -m pytest -q   # erwartet: 46 passed
.\start_dashboard.ps1                     # Tabs „Orden" + „Wartung" mit ECHTEN km prüfen
.\.venv\Scripts\python.exe build_today.py # today.json inkl. milestone-Feld erzeugen
```
Prüfen: Stimmt der Kilometerstand? Sind die Wartungsintervalle plausibel?
Beim ersten Start einmal **„Alle ab jetzt frisch tracken"** klicken — sonst
zählt der Verschleiss ab km 0 und alles ist sofort „überfällig".

### Schritt 3 — die drei offenen Design-/Technikpunkte klären
1. **Windrose (#4):** Zielbild vom Nutzer erfragen. Optionen: Nordnadel statt
   Buchstaben? Zwei Pfeile (woher der Wind kommt *und* wohin er drückt)?
   Böen-Anzeige? Gegen-/Rückenwind-Komponente gross als Zahl? Rose als eigener
   grosser Screen statt kleiner Kachel?
2. **Shift ohne Kadenzsensor (#6):** Grundsatzentscheid — (a) Sensor-Pflicht
   dokumentieren, (b) Fallback: Trittfrequenz aus Tempo + geschätzter Übersetzung
   schätzen (ungenau), oder (c) Shift-Hinweis an Ziel-Zone/Tempo koppeln.
   Empfehlung: erst (a) klarstellen, dann ggf. (b)/(c).
3. **Vorzeichen der Steigung (#5):** hängt von der Einbaurichtung des Halters ab.
   Falls invertiert: „Richtung umkehren"-Toggle (Faktor ±1 in `localStorage`).

### Schritt 4 — ausliefern
- PWA am **Android-Handy mit Chrome** testen (Web Bluetooth + HTTPS nötig),
  inkl. gekoppeltem Kadenzsensor für den Shift-Test.
- Wenn zufrieden: Branch nach `main` mergen, damit GitHub Pages und der
  Streamlit-Deploy die neuen Versionen ausliefern.

---

## 7. Nützliche Kommandos

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # Tests
.\.venv\Scripts\python.exe sync.py               # inkrementeller Sync
.\.venv\Scripts\python.exe sync.py --full        # alles neu holen
.\.venv\Scripts\python.exe build_today.py        # today.json bauen
.\start_dashboard.ps1                            # Dashboard starten
cd mobile; ..\.venv\Scripts\python.exe -m http.server 8800   # PWA lokal: /ride.html
```

Logik-Check ohne DB:
```powershell
.\.venv\Scripts\python.exe -c "from bikedash import milestones as m; v=m.compute(4200); print(len(v.earned),'/',v.badges_total, v.latest.name)"
```

---

## 8. Hinweise für Claude Code

- **Keine PR erstellen**, ausser der Nutzer bittet ausdrücklich darum.
- Entwicklung läuft auf einem `claude/…`-Branch, **nie direkt auf `main`**.
- Deutsche UI-Texte und Kommentare beibehalten.
- `dashboard.py` ist gross: neue Logik in ein `bikedash/`-Modul auslagern und im
  Dashboard nur rendern.

### 8a. Fertig heisst: gemerged  ⚠️

**Nach `main` mergen, sobald etwas fertig ist — ohne Rückfrage.** Der Nutzer hat
das ausdrücklich so angeordnet (Sept 2026). Grund: Streamlit Community Cloud
deployt aus `main`, GitHub Pages liefert die PWA aus `main`. Code auf einem
Feature-Branch ist für den Nutzer **nicht vorhanden** — er sieht das alte
Dashboard und meldet „Features fehlen". Das ist in diesem Projekt schon zweimal
passiert (Abschnitt 5b, Befund 1; und erneut im September 2026).

„Fertig" ist definiert als: `python -m pytest -q` grün **und** die betroffene
Oberfläche real im Browser geprüft (Streamlit starten, Tab anklicken, auf
Traceback und JS-Fehler schauen) — nicht „kompiliert durch".

### 8b. Nach jeder Änderung: Ausbreitung prüfen  ⚠️

Ein neuer Wert oder eine neue Einstellung lebt in diesem Projekt an **sechs**
Stellen. Wer nur zwei davon anfasst, baut einen stillen Fehler: das Dashboard
rechnet dann anders als `today.json`, und niemand merkt es. Genau so waren
`ATHLETE_LTHR` (nie in den Workflows) und `weekly_hours_target` (nirgends
gelesen) monatelang kaputt. Checkliste:

| # | Stelle | wofür |
|---|---|---|
| 1 | `bikedash/config.py` → `_ENV_MAP` | Env-Overlay beim Hosting |
| 2 | `config.example.toml` | lokale Einrichtung |
| 3 | `.streamlit/secrets.toml.example` | Streamlit-Secrets |
| 4 | `.github/workflows/sync.yml` (beide Schritte: Tagesplan **und** Morgen-Report) | **die vergessene Stelle** |
| 5 | `DEPLOY.md` (Secrets-Tabelle) | damit der Nutzer es findet |
| 6 | Einrichtungs-Tab in `dashboard.py` | Eingabe + Speichern |

Gegenprobe vor dem Commit:
`grep -rn "DEIN_NEUER_WERT" --include=*.py --include=*.toml --include=*.yml --include=*.md .`
— taucht er in weniger als sechs Dateien auf, fehlt etwas.

Weitere Fallen, die hier schon zugeschlagen haben:
- **Rechnet der gehostete Pfad wie das Dashboard?** `build_today.py` läuft in
  GitHub Actions ohne `config.toml` — alles muss über Env-Variablen ankommen.
- **Bestehende Tests, die eine kaputte Annahme zementieren.** Beim Umstellen der
  Lastskala war ein Test auf die falsche Skala kalibriert. Schlägt ein Test nach
  einer bewussten Änderung fehl: erst prüfen, welche der beiden Seiten recht hat.
- **`pandas.resample("W-MON")` gruppiert rechtsseitig** und zerschneidet
  Trainingswochen. Für Montag-bis-Sonntag `closed="left", label="left"` setzen.
- **`pkill -f "streamlit run"`** killt die eigene Shell mit, weil die Kommandozeile
  den Suchstring selbst enthält. `pkill -f "[s]treamlit.run"` benutzen.
- Bei Änderungen an `recommend.py`-Templates daran denken, dass die Werte über
  `today.json` in die PWA fliessen — dort ggf. Defaults mitziehen.
