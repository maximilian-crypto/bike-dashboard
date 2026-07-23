# 🚴 Fahrrad-Dashboard (Strava + Whoop)

Ein lokales Dashboard, das deine Fahrraddaten aus **Strava** und deine
Körper-/Erholungsdaten aus **Whoop** automatisch zusammenführt und auswertet:

- **🎯 Heute** – Tagesempfehlung aus Wochenvolumen + Whoop-Erholung: Sessiontyp,
  Dauer, **HF-Zone (bpm)**, **Trittfrequenz**, **Anstrengung (RPE)** und eine
  echte, auf der Karte generierte **Rundkurs-Route** der passenden Distanz.
- **📈 Leistung & Fortschritt** – Distanz, Tempo, Leistung (Watt), Effizienz.
- **🏋️ Trainingsbelastung** – Wochenlast, Fitness-vs-Ermüdung (akut/chronisch).
- **💤 Erholung** – Recovery, Ruhepuls, HRV; Belastung → Erholung am Folgetag.
- **🌬️ Wind-Labor (Beta)** – wie Gegen-/Rückenwind dein Tempo beeinflusst; fließt
  in die windkluge Routenplanung ein (Hinweg gegen den Wind, Rückweg mit Rückenwind).
- **🏅 Orden & Meilensteine** – deine kumulierte Gesamtdistanz schaltet „Orden" bei
  berühmten Distanzen frei (Tour de France, Länge Deutschlands, ein Shai-Hulud,
  Erde → Mond …), dazwischen erreichbare Nahziele alle ~40 km.
- **🔧 Verschleiß-Tracker** – km-Zähler pro Bauteil (Kette, Reifen, Kassette …) mit
  Wartungs-Ampel und „gewechselt"-Reset.
- **🧠 KI-Coach** – Klartext-Beratung aus deinen Daten (Claude API) + Wochenrückblick.
- **📱 Morgen-Report** – heutige Empfehlung + Wetter + Form früh aufs Handy (via ntfy).

Außerdem: **Form-Kurve** (Fitness/Ermüdung/Form, CTL/ATL/TSB) und **1-Klick-Backup**.

Alle Daten bleiben **lokal auf deinem PC** (SQLite-Datei). Nur der KI-Coach sendet
(falls du ihn nutzt) eine kompakte Daten-Zusammenfassung an die Claude API.

---

## Schnellstart (empfohlen: alles im Dashboard)

```powershell
# 1. Pakete installieren (einmalig)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Dashboard starten
.\start_dashboard.ps1
```

Dann im Dashboard den Tab **⚙️ Einrichtung** öffnen. Dort gibt es für Strava,
Whoop und OpenRouteService je ein aufklappbares Panel mit **Anleitung**, einem
**Portal-öffnen-Knopf** und **Eingabefeldern**. Werte eintragen → **💾 Speichern**
→ **🔗 Mit Strava/Whoop verbinden** (Browser-Login) → links **🔄 Jetzt
synchronisieren**. Fertig.

> Die Detail-Anleitung (was wo einzutragen ist) steht weiter unten und identisch
> direkt in den Panels im Dashboard.

### Alternative: alles über die Kommandozeile

```powershell
copy config.example.toml config.toml      # config.toml ausfüllen (siehe unten)
.\.venv\Scripts\python.exe connect.py     # Browser-Login Strava + Whoop
.\.venv\Scripts\python.exe sync.py        # Daten holen
.\start_dashboard.ps1                      # Dashboard öffnen
```

---

## Setup im Detail

### A) Strava-API-App anlegen  → `client_id` + `client_secret`

1. Gehe zu **https://www.strava.com/settings/api** (eingeloggt).
2. Lege eine Anwendung an:
   - **Application Name**: z. B. `Mein Fahrrad-Dashboard`
   - **Category**: `Data Importer`
   - **Website**: irgendwas, z. B. `http://localhost`
   - **Authorization Callback Domain**: **`localhost`**  ← wichtig, nur das Wort
3. Nach dem Speichern siehst du **Client ID** und **Client Secret**.
4. Trage beide in `config.toml` unter `[strava]` ein.

### B) Whoop-API-App anlegen  → `client_id` + `client_secret`

1. Gehe zum **Whoop Developer Dashboard**: https://developer.whoop.com
   (mit deinem Whoop-Konto anmelden, ggf. „Create Team"/App).
2. Erstelle eine neue App. Trage als **Redirect URI** exakt ein:
   ```
   http://localhost:8721/whoop/callback
   ```
3. Wähle die Scopes:
   `read:recovery`, `read:cycles`, `read:sleep`, `read:workout`,
   `read:profile`, `read:body_measurement` und `offline`.
4. Kopiere **Client ID** und **Client Secret** in `config.toml` unter `[whoop]`.

> Die Strava-Redirect-Domain ist nur `localhost`; bei Whoop muss die **volle**
> URL `http://localhost:8721/whoop/callback` hinterlegt sein. Wenn du in
> `config.toml` den Port änderst, passe die Whoop-Redirect-URI entsprechend an.

### C) Routen-Feature: OpenRouteService + Heimat-Koordinaten

1. Kostenloses Konto auf **https://openrouteservice.org** → Token/API-Key
   erstellen. In `config.toml` unter `[ors] api_key` eintragen.
2. **Heimat-Koordinaten** (Start der Runden): In Google Maps an deinen Startort
   **rechtsklicken** → die erste Zeile sind `Breite, Länge` (lat, lon). Werte
   unter `[athlete] home_lat` / `home_lon` eintragen.

Ohne C) funktioniert alles andere trotzdem – im „Heute"-Tab erscheint dann nur
ein Hinweis statt der Karte.

> **HF-Zonen:** Deine maximale Herzfrequenz holt die App automatisch aus Whoop
> (aus deinen Jahresdaten bestimmt) und baut daraus die 5 Zonen nach Whoops
> Modell. Du musst dafür nichts eintragen.

---

### D) KI-Coach + Morgen-Report (optional)

**KI-Coach** (Klartext-Beratung aus deinen Daten):
1. API-Key auf **https://console.anthropic.com** erstellen.
2. Im Tab **⚙️ Einrichtung → 4) KI-Coach** eintragen (Modell: `claude-opus-4-8`).
3. Im Tab **🧠 Coach** Fragen stellen oder „Wochenrückblick erstellen" klicken.

**Morgen-Report aufs Handy** (kostenlos, ohne Konto, via ntfy):
1. **ntfy**-App installieren (Android/iOS) und ein **geheimes Thema** abonnieren,
   z. B. `max-bike-7f3a` (wähle etwas Eindeutiges — wer das Thema kennt, sieht die Pushes).
2. Dasselbe Thema im Tab **⚙️ Einrichtung → 4)** unter „ntfy-Thema" eintragen.
3. Test: im **🧠 Coach**-Tab „Test-Report jetzt senden", oder `python send_report.py`.
4. Täglich automatisch:
   ```powershell
   .\setup_report_task.ps1            # täglich 06:30 Uhr
   .\setup_report_task.ps1 -At "07:15"
   ```

## Automatischer Sync (auch mehrmals täglich)

Eine geplante Windows-Aufgabe einrichten (in PowerShell im Projektordner):

```powershell
.\setup_task.ps1                      # alle 4 Stunden, ab 07:00 Uhr
.\setup_task.ps1 -IntervalHours 2     # alle 2 Stunden
.\setup_task.ps1 -IntervalHours 6 -StartTime "06:30"
```

- Läuft im Hintergrund, auch im Akkubetrieb; holt Verpasstes nach.
- Sofort testen: `Start-ScheduledTask -TaskName BikeDashboardSync`
- Log ansehen: `data\sync.log`
- Entfernen: `Unregister-ScheduledTask -TaskName BikeDashboardSync -Confirm:$false`

> Der Sync ist **inkrementell** (holt nur Neues) und damit schnell – häufiges
> Ausführen ist unproblematisch.

---

## Bedienung

| Befehl | Zweck |
|---|---|
| `python connect.py` | Strava **und** Whoop verbinden |
| `python connect.py strava` | nur Strava verbinden |
| `python connect.py whoop` | nur Whoop verbinden |
| `python sync.py` | neue Daten holen (inkrementell) |
| `python sync.py --full` | alles neu holen |
| `.\start_dashboard.ps1` | Dashboard im Browser öffnen |

Im Dashboard gibt es links den Button **🔄 Jetzt synchronisieren** und einen
Zeitraum-Filter.

---

## Aufbau

```
bike-dashboard/
├─ bikedash/            # Programmlogik
│  ├─ config.py         # Zugangsdaten + Token-Speicher
│  ├─ store.py          # lokale SQLite-Datenbank
│  ├─ auth.py           # OAuth-Login-Flow
│  ├─ strava.py         # Strava: Login, Sync, GPS-Streams
│  ├─ whoop.py          # Whoop: Login, Recovery/Strain/Max-HF
│  ├─ dataprep.py       # Aufbereitung der Rohdaten
│  ├─ zones.py          # HF-Zonen aus Whoop-Max-HF
│  ├─ recommend.py      # Tagesempfehlung (Logik)
│  ├─ routing.py        # Rundkurs-Routen (windklug) via ORS
│  ├─ weather.py        # Wetter (Open-Meteo)
│  ├─ windlab.py        # Wind-Performance-Analyse (Beta)
│  ├─ form.py           # Form-Modell (CTL/ATL/TSB)
│  ├─ milestones.py     # Distanz-Meilensteine & Orden
│  ├─ maintenance.py    # Verschleiß-/Wartungs-Tracker
│  ├─ backup.py         # Datensicherung
│  ├─ coach.py          # KI-Coach (Claude API)
│  └─ report.py         # Morgen-Report (ntfy-Push)
├─ tests/               # pytest-Suite (isolierte Test-DB)
├─ connect.py           # Konten verbinden
├─ sync.py              # Daten holen
├─ send_report.py       # Morgen-Report senden
├─ dashboard.py         # Streamlit-Dashboard
├─ run_sync.ps1         # vom Taskplaner aufgerufen
├─ setup_task.ps1       # geplanter Sync
├─ setup_report_task.ps1# geplanter Morgen-Report
├─ start_dashboard.ps1  # Dashboard starten
├─ config.toml          # DEINE Zugangsdaten (nicht eingecheckt)
└─ data/bikedash.db     # deine Daten (nicht eingecheckt)
```

---

## Hinweise

- **Datenschutz:** `config.toml`, `tokens.json` und `data/` stehen in
  `.gitignore` und verlassen deinen Rechner nicht.
- Die Tagesempfehlung ist ein **Trainings-Heuristik-Helfer**, kein medizinischer
  Rat. Höre auf deinen Körper.
- Strava-API-Limits: 100 Anfragen/15 Min, 1000/Tag – für privaten Gebrauch mehr
  als genug.
