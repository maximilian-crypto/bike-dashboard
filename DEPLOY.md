# 🚀 Hosting: Backend in die Cloud + App aufs iPhone

Diese Anleitung bringt das Fahrrad-Dashboard vom lokalen PC in die Cloud, sodass
es **24/7 läuft (auch wenn dein PC aus ist)** und du es **wie eine App auf dem
iPhone** nutzen kannst. Alles mit **kostenlosen** Diensten.

## Architektur nach dem Umzug

```
                 ┌─────────────────────────┐
   iPhone  ─────▶│ Streamlit Community Cloud│  Dashboard (Passwort-geschützt)
 (Home-Screen)   └───────────┬─────────────┘
                             │  liest/schreibt
   iPhone  ─────▶  GitHub Pages: Ride-PWA    │
 (Home-Screen)               │               ▼
                 ┌───────────┴─────────────────────────┐
                 │   Neon  (PostgreSQL, dauerhaft)      │  ← alle Daten + Tokens
                 └───────────▲─────────────────────────┘
                             │  Sync alle 4 h / Report morgens
                 ┌───────────┴─────────────┐
                 │  GitHub Actions (Cron)   │  holt Strava/Whoop, pusht Report
                 └─────────────────────────┘
```

**Warum so:** Kostenlose Hosting-Dienste haben eine „vergessliche" Festplatte.
Deshalb liegen Daten **und** OAuth-Tokens in **Neon** (dauerhaft), nicht in
Dateien. Der Code merkt automatisch: ist `DATABASE_URL` gesetzt → Cloud (Postgres),
sonst → lokale SQLite wie bisher. **Lokal ändert sich für dich nichts.**

---

## Voraussetzungen (kostenlose Konten)
- **GitHub** – Code-Repo, Cron-Jobs (Actions), Ride-PWA (Pages).
- **Neon** (https://neon.tech) – Postgres-Datenbank.
- Deine bestehenden Keys: Strava, Whoop, OpenRouteService, optional Anthropic + ntfy.

---

## Schritt 1 — Neon-Datenbank anlegen
1. Auf https://neon.tech mit GitHub anmelden → **Create Project** (Region Europe).
2. Im Dashboard **Connection string** kopieren – Format:
   `postgresql://USER:PW@ep-xyz.eu-central-1.aws.neon.tech/neondb?sslmode=require`
3. Diesen String brauchst du gleich mehrfach als **`DATABASE_URL`**.

## Schritt 2 — Code zu GitHub (privates Repo)
Im Projektordner (PowerShell):
```powershell
git init
git add .
git commit -m "Bike-Dashboard: Cloud-fähig"
```
Dann auf GitHub ein **privates** Repo anlegen und pushen (GitHub zeigt dir die
zwei `git remote add` / `git push`-Befehle). `.gitignore` sorgt dafür, dass
`config.toml`, `tokens.json`, `data/` und `secrets.toml` **nicht** hochgeladen
werden.

## Schritt 3 — Einmalig verbinden + Daten mitnehmen (lokal)
Der OAuth-Login braucht einen Browser – das machst du **einmal lokal**, schreibst
aber direkt in die Cloud-DB. In PowerShell im Projektordner:
```powershell
$env:DATABASE_URL = "postgresql://…?sslmode=require"   # dein Neon-String

# bestehende lokale Historie in die Cloud-DB heben (optional, empfohlen):
.\.venv\Scripts\python.exe migrate_to_postgres.py

# Strava + Whoop verbinden (Tokens landen in der Cloud-DB):
.\.venv\Scripts\python.exe connect.py

# Danach die Variable wieder leeren, damit du lokal wieder die SQLite nutzt:
$env:DATABASE_URL = ""
```
> Falls `migrate_to_postgres.py` die Tokens schon übernommen hat, kannst du
> `connect.py` überspringen. Neu verbinden schadet aber nicht.

## Schritt 4 — Dashboard auf Streamlit Community Cloud
1. Auf https://share.streamlit.io mit GitHub anmelden → **Create app** → dein
   Repo, Branch `main`, Main file `dashboard.py`.
2. **Advanced settings → Secrets**: den Inhalt von
   [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) einfügen
   und ausfüllen (v. a. `DATABASE_URL` und ein **starkes `APP_PASSWORD`**).
3. **Deploy**. Nach ~1 Min läuft das Dashboard unter
   `https://<name>.streamlit.app` – beim Öffnen fragt es nach dem Passwort.

> Ohne `APP_PASSWORD` ist das Dashboard **öffentlich** – unbedingt setzen!
> Streamlit-Apps „schlafen" bei Nichtnutzung ein und wachen beim Öffnen in
> ~10 s wieder auf. Die Daten in Neon bleiben davon unberührt.

## Schritt 5 — Automatischer Sync + Morgen-Report (GitHub Actions)
Die Workflows liegen schon im Repo (`.github/workflows/`). Trage die Secrets ein:
**Repo → Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Wert |
|---|---|
| `DATABASE_URL` | dein Neon-String |
| `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` | aus Strava |
| `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET` | aus Whoop |
| `ORS_API_KEY`, `ATHLETE_HOME_LAT`, `ATHLETE_HOME_LON` | Routen/Wetter |
| `NTFY_TOPIC` | dein ntfy-Thema (für den Report) |

Testen: **Actions → „Sync Strava + Whoop" → Run workflow**. Danach läuft der Sync
alle 4 h automatisch, der Report morgens (04:30 UTC ≈ 06:30 DE-Sommerzeit).

## Schritt 6 — Ride-PWA (unterwegs) auf GitHub Pages
1. **Repo → Settings → Pages** → Source „Deploy from branch", Branch `main`,
   Ordner `/ (root)`.
2. Die App ist dann unter
   `https://<name>.github.io/<repo>/mobile/ride.html` erreichbar.

## Schritt 7 — Aufs iPhone legen (beide Apps)
- **Dashboard**: in Safari `https://<name>.streamlit.app` öffnen → Teilen-Symbol
  → **„Zum Home-Bildschirm"**.
- **Ride-PWA**: in Safari die `ride.html`-URL öffnen → **„Zum Home-Bildschirm"**.

---

## ⚠️ iPhone & Sensoren (Magene-Trittfrequenz, Live-HF)
iOS-Safari unterstützt **kein Web Bluetooth**. In der Ride-PWA funktionieren auf
dem iPhone **GPS, Wind, Karte und Navigation**, aber **Live-HF und Trittfrequenz
per Bluetooth nicht**. Optionen für den Magene-Sensor / Live-HF auf iPhone:
- **Bluefy** (BLE-Browser aus dem App Store) statt Safari für die Ride-PWA, oder
- die Sensordaten laufen ohnehin über Whoop/Strava in die Historie (Auswertung
  im Dashboard) – nur der Echtzeit-Screen ist betroffen.

*(Offener Punkt: Magene-Trittfrequenz sauber in die Historie/Backend integrieren –
z. B. über Wahoo-Export. Siehe Projekt-Notizen.)*

## Sicherheit — was eingebaut ist
- **Passwort-Gate** vor dem Dashboard (`APP_PASSWORD`) inkl. Brute-Force-Bremse.
- **Keine Secrets im Code/Repo**: alles über Secrets/Umgebungsvariablen,
  `.gitignore` schützt lokale Dateien. Repo **privat** halten.
- **Tokens in der DB** (privates Neon), nicht in einer offenen Datei; HTTPS überall.
- Nutze für Neon/GitHub sichere, einzigartige Passwörter und aktiviere 2FA.

## Fehlersuche
- **„Keine Konfiguration gefunden"** → Secrets/Umgebungsvariablen fehlen.
- **Dashboard zeigt keine Daten** → Actions-Sync gelaufen? `DATABASE_URL` überall
  identisch (Streamlit-Secrets **und** Actions-Secrets)?
- **Whoop/Strava „nicht verbunden"** → Schritt 3 lief gegen die **falsche** DB.
  `DATABASE_URL` auf Neon setzen und `connect.py` erneut ausführen.
- **Report kommt nicht** → `NTFY_TOPIC` gesetzt und in der ntfy-App abonniert?
