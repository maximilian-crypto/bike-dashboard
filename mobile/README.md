# 🚴 Live Ride – On-Bike-Screen (PWA-Prototyp)

Ein **reiner Client-PWA-Prototyp** für das Fahren: live Tempo, Herzfrequenz,
Trittfrequenz, Wind und Karte — mit **HF-Zonen-Farbindikator**. Läuft komplett
im Browser, **braucht keinen Server** und funktioniert auch unterwegs.

## Was er kann
- **Tempo** aus dem GPS deines Handys.
- **Herzfrequenz** live per Bluetooth (HF-Gurt im BLE/Broadcast-Modus; Whoop:
  in der App „Broadcast Heart Rate" aktivieren). Die Kachel färbt sich nach
  **HF-Zone** (Z1 blau … Z5 rot), berechnet aus deiner Max-HF.
- **Trittfrequenz** per Bluetooth (Cadence-/CSC-Sensor).
- **Gangempfehlung** aus der Kadenz relativ zum Zielband: leichter / halten / schwerer.
- **Wind als Kompass-Rose** am aktuellen Standort (Open-Meteo): heading-up (deine
  Fahrtrichtung oben), aufrechte N/O/S/W-Beschriftung und ein Pfeil für die
  **relative** Windrichtung, farbcodiert nach Gegen-/Rücken-/Seitenwind.
- **Steigung** aus der Sensor-Neigung – **kalibrierbar** (Kachel antippen setzt auf
  ebener Strecke „0 %", weil der Handyhalter nicht immer gleich sitzt).
- **Karte** mit Live-Position und zurückgelegter Strecke.
- **Bildschirm bleibt an** (Wake Lock) während der Fahrt.

## Wichtig: Sensoren brauchen HTTPS
Web Bluetooth und GPS funktionieren nur in einem **sicheren Kontext**:
- am PC: `http://localhost` ist erlaubt (Chrome/Edge),
- am Handy: über **HTTPS** — am einfachsten kostenlos via **GitHub Pages**.

## Kostenlos hosten (GitHub Pages, ~2 Min)
1. Den `mobile/`-Ordner in ein (öffentliches) GitHub-Repo legen.
2. Repo → **Settings → Pages** → Source: „Deploy from branch", Branch: `main`,
   Ordner: `/` (oder `/docs`, falls du die Dateien dahin kopierst).
3. Nach ~1 Min ist die App unter
   `https://<dein-name>.github.io/<repo>/ride.html` erreichbar.
4. Auf dem Handy öffnen → Chrome-Menü → **„Zum Startbildschirm hinzufügen"**.

> Nur **Android (Chrome/Edge)** unterstützt Web Bluetooth. Auf iOS funktionieren
> GPS, Wind und Karte; für Live-HF/-Trittfrequenz braucht iOS eine native App
> oder einen BLE-fähigen Browser (z. B. Bluefy).

## Lokal testen (am PC)
```powershell
cd mobile
python -m http.server 8800
# dann im Browser:  http://localhost:8800/ride.html
```

## Status
Prototyp / Proof of Concept. Nächste Schritte: Navigation entlang einer
generierten Route, Standort-Button zur Routenanpassung, Anbindung an das
Hub-Backend (Empfehlung des Tages direkt im Live-Screen).
