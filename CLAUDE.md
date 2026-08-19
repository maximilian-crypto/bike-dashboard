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
│  ├─ dataprep.py         # Rohtabellen -> DataFrames
│  ├─ load.py             # Banister-TRIMP (Trainingslast)
│  ├─ form.py             # CTL/ATL/TSB (Fitness/Ermüdung/Form)
│  ├─ zones.py            # HF-Zonen (LTHR > Karvonen/HRR > %max)
│  ├─ recommend.py        # Tagesempfehlung (Kern-Heuristik)
│  ├─ routing.py          # windkluge Rundkurse via ORS
│  ├─ weather.py          # Open-Meteo
│  ├─ windlab.py          # Wind-Performance-Analyse
│  ├─ milestones.py       # NEU: Distanz-Meilensteine & Orden
│  ├─ maintenance.py      # NEU: Verschleiss-/Wartungs-Tracker
│  ├─ coach.py            # KI-Coach (Claude API)
│  ├─ report.py           # Morgen-Report (ntfy-Push)
│  └─ backup.py           # Datensicherung
├─ dashboard.py           # Streamlit-App (ein grosses Skript, Tabs via st.tabs)
├─ build_today.py         # schreibt mobile/today.json
├─ sync.py, connect.py    # CLI: Daten holen / Konten verbinden
├─ mobile/                # Live-Ride-PWA (ride.html, sw.js, manifest.json)
├─ tests/                 # pytest, isolierte Wegwerf-DB via conftest.py
├─ *.ps1                  # Windows-Helfer (siehe Abschnitt 5 — AKTUELLER BLOCKER)
└─ .github/workflows/     # sync.yml, report.yml, keepalive.yml (laufen auf Linux)
```

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

**Tests:** 46 grün (`python -m pytest -q`), inkl. neuer Suites
`tests/test_milestones.py` und `tests/test_maintenance.py`.

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
- Entwicklung läuft auf Branch `claude/fahrrad-app-neue-feature-ptpp0w`.
- Vor „fertig": `python -m pytest -q` muss grün sein.
- Deutsche UI-Texte und Kommentare beibehalten.
- Bei Änderungen an `recommend.py`-Templates daran denken, dass die Werte über
  `today.json` in die PWA fliessen — dort ggf. Defaults mitziehen.
- `dashboard.py` ist gross: neue Logik in ein `bikedash/`-Modul auslagern und im
  Dashboard nur rendern.
