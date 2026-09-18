# Handoff: Tagesworkout automatisch in die Zwift-Bibliothek

> Stand: 18.09.2026. Für ein frisches Kontextfenster. Projektkontext steht in
> `CLAUDE.md` — hier steht nur, was für **diese eine offene Aufgabe** zählt.

---

## 1. Die Aufgabe in einem Satz

Das Dashboard berechnet täglich die optimale Einheit. Sie soll **ohne jedes
Zutun des Nutzers** als Zwift-Workout in seiner Bibliothek auftauchen, damit er
Zwift öffnet, das Workout antippt und der ERG-Modus den Rest macht.

## 2. Warum das die eigentliche Anforderung ist

Wörtlich vom Nutzer:

> „Der ganze Punkt der App ist, dass ich außer dem eigentlichen Sport so wenig
> wie möglich machen muss. Wenn ich dann jedes Mal nach nem Workout mit meinen
> hyperspezifischen Spezifikationen suchen muss, ist das genau die Hemmschwelle,
> die dazu führt, dass ich es gar nicht mehr benutze."

**Das ist das Abnahmekriterium, nicht die technische Eleganz.** Jede Lösung, die
einen wiederkehrenden manuellen Schritt enthält (Datei suchen, Workout anlegen,
Werte abtippen), ist gescheitert — egal wie gut sie sonst ist.

### Mein Fehler, den du nicht wiederholen solltest

Ich habe eine **Wattplan-Tabelle** ins Dashboard gebaut („12' ein · 4×8' @
155–178 W · 10' aus") und das für die Lösung gehalten. War es nicht: das ist
eine *Anleitung*, die der Nutzer manuell in Zwift nachbauen oder wiederfinden
muss. Er braucht eine *Automatik*. Die Tabelle darf bleiben (sie ist als
Referenz nützlich), aber sie löst das Problem nicht.

### Was ebenfalls abgelehnt wurde

Ein eigener ERG-Player in der PWA (Trainer direkt per Web-Bluetooth FTMS
steuern, Zwift komplett umgehen) wäre technisch machbar — der Nutzer hat es
**bewusst abgelehnt**:

> „Die Gamification mit den Ingame-Rewards und dass ich es dann trotzdem noch
> auf Strava packen kann, haben mich gecatcht."

Zwift bleibt also gesetzt. Nicht neu aufrollen.

---

## 3. Was schon gebaut ist und wiederverwendet werden muss

**`bikedash/power.py` → `structure(kind, duration_min, ftp, cadence)`** liefert
bereits exakt die Datenstruktur, die eine `.zwo`-Datei beschreibt:

```python
[Block(label="Einfahren",       minutes=15, low_w=76,  high_w=94,  zone=1),
 Block(label="Intervall 1/4",   minutes=8,  low_w=155, high_w=178, zone=4),
 Block(label="Pause",           minutes=4,  low_w=76,  high_w=94,  zone=1),
 ...
 Block(label="Ausfahren",       minutes=10, low_w=76,  high_w=94,  zone=1)]
```

Die Umwandlung nach `.zwo`-XML ist damit **~50 Zeilen**, nicht 200. `.zwo`
arbeitet mit `<SteadyState Duration="480" Power="0.95"/>`, also Sekunden und
Anteil der FTP — beides trivial aus dem Block ableitbar (`minutes*60`,
`mitte(low_w, high_w)/ftp`).

Dieselben Blöcke stehen auch schon in `mobile/today.json` unter
`recommendation.power_plan`. Der Wert ist also bereits im Netz abrufbar.

Weitere relevante Bausteine: `recommend.build()` (Tagesempfehlung),
`season.build()` (Wochenziel, Phase), `config.ftp_from_config()` (FTP = 170).

---

## 4. Recherche-Ergebnisse (verifiziert, mit Quellen)

### Befund 1 — Zwift synct eigene Workouts über die Cloud ✅

Custom Workouts werden zwischen allen Geräten synchronisiert. Das ist der
Hebel: Eine `.zwo`, die **irgendwo** in Zwifts Workouts-Ordner landet,
erscheint anschließend auch auf dem Handy. ([Zwift Insider – Cloud Sync für
Workouts](https://zwiftinsider.com/workout-cloud-sync/),
[Zwift Support – Custom Workouts](https://support.zwift.com/en_us/custom-workouts-ryGOTVEPs))

Bekannte Fallstricke aus den Foren, die eingeplant werden müssen:
- **Keine Sonderzeichen im Workout-Namen** — verhindert das Syncen.
- **Maximal 64 KB pro `.zwo`** — für unsere Dateien unkritisch.
- Nur `.zwo`-Dateien direkt im `workouts`-Verzeichnis werden gesynct,
  **Unterordner nicht**.

### Befund 2 — der Standardweg braucht einen PC ⚠️

> „The easiest way to get custom workouts onto your iOS device is to create or
> download the workout on a Windows or Apple PC, boot up Zwift on the PC so that
> workout is copied to the cloud, then boot up Zwift on your iOS device."

([Zwift Insider – Workout-Dateien auf iOS kopieren](https://zwiftinsider.com/copy-workout-files-zwift-ios/))

Der Ablageort auf iOS ist `iCloud → Documents/Zwift/Workouts/<ZwiftID>/`. Ob
eine dort **ohne laufendes Zwift-auf-PC** abgelegte Datei zuverlässig in die
Cloud hochgeladen wird, ist **die offene Kernfrage**. Die Foren deuten auf
„eher nein", sind aber nicht eindeutig und teils veraltet.

### Befund 3 — Zwift kann Workouts von Drittanbietern importieren

Zwift selbst schreibt, man könne „custom workouts from certain third-party
platforms" importieren. Bekannt ist die TrainingPeaks-Anbindung: ein dort
geplantes Workout erscheint in Zwift auf **jedem** Gerät, ganz ohne Dateien.
**Nicht verifiziert** — das ist die vielversprechendste Spur für einen Weg
komplett ohne PC.

---

## 5. Lösungswege, nach Erfolgsaussicht

### Weg A — TrainingPeaks (oder ähnliche Plattform) als Brücke ⭐ zuerst prüfen
`build_today.py` schreibt das Tagesworkout zu TrainingPeaks, Zwift zieht es sich
über die bestehende Verknüpfung. Kein PC, kein Dateisystem, geräteunabhängig.

**Zu klären:** Nimmt die TrainingPeaks-API Workouts von außen an, oder ist sie
partnergebunden? Gibt es einen freien Zwischenhändler (intervals.icu hat eine
offene API und kann `.zwo` exportieren — kann es auch *in* Zwift oder
TrainingPeaks schreiben)? Welche „third-party platforms" meint Zwift konkret?

### Weg B — Cloud-Ordner + PC, der Zwift ohnehin startet
GitHub Action legt die `.zwo` in einen OneDrive-/Dropbox-/iCloud-Ordner, der auf
einem PC in Zwifts Workouts-Verzeichnis gespiegelt ist. Beim nächsten
Zwift-Start auf dem PC wandert sie in die Cloud und damit aufs Handy.

**Nachteil:** braucht einen PC, der regelmäßig Zwift startet. Der Nutzer fährt
aber auf dem Handy — die Kette könnte tagelang stillstehen. **Vor dem Bauen
klären, ob überhaupt ein PC verfügbar ist.** Der Nutzer erwähnte OneDrive
ausdrücklich als Idee, hat aber nie gesagt, dass ein PC läuft.

### Weg C — iCloud-Ablage direkt vom Handy
`.zwo` per Shortcut/Action in `iCloud/Documents/Zwift/Workouts/<ID>/` legen.
Wäre der kürzeste Weg — steht und fällt mit Befund 2. **Billig zu testen:**
einmal eine Datei von Hand dort ablegen, Zwift am Handy öffnen, schauen ob sie
auftaucht. Das sollte der allererste Versuch sein, er kostet zehn Minuten.

### Weg D — inoffizielle Zwift-API
Es gibt reverse-engineerte Bibliotheken. **Nicht empfohlen:** ToS-Graubereich,
bricht bei jedem Zwift-Update, und der Nutzer würde den Ausfall erst merken,
wenn das Workout eines Tages fehlt.

---

## 6. Rahmenbedingungen

- **Gerät:** Zwift läuft auf dem **Handy**. Auf iOS ist Web Bluetooth über den
  Browser **Bluefy** möglich (für einen eventuellen Direktweg zum Trainer
  relevant, für diese Aufgabe eher nicht).
- **Trainer:** Van Rysel D100 mit Zwift Cog & Click, virtuelles Schalten, ERG
  funktioniert.
- **Athlet:** 24 J., 71 kg, **FTP 170 W** (Ramp Test 17.09.2026). **LTHR fehlt
  noch** — 20-Minuten-Test ist für Dezember vorgesehen. Ruhepuls 68, Max-HF 197.
  Ziel: 1. März 2027, aktuell Planwoche 1, Phase Grundlage.
  Kommt von ~1,16 h/Woche, vier Wochen nach einem Meniskusproblem — der
  Saisonplan steigert bewusst langsam, das nicht „optimieren".
- **Automatisierung** läuft über `.github/workflows/sync.yml` (alle 4 h) und
  `report.yml` (morgens). Dort muss ein neuer Schritt andocken.
- **`CLAUDE.md` Abschnitt 8a/8b gilt:** nach `main` mergen, sobald fertig
  (Streamlit und Pages deployen aus `main`), und neue Konfigurationswerte an
  **allen sechs** Stellen eintragen. Beides ist hier schon zweimal schiefgegangen.

## 7. Wenn kein Weg trägt

Dann ist die ehrliche Antwort an den Nutzer: **Zwift auf dem Handy und
automatische Workout-Zustellung schließen sich aus.** In dem Fall die Optionen
offen benennen (Laptop für Zwift, oder ERG-Player in der PWA ohne Zwift-Welt,
oder bei der Tabelle bleiben) statt eine Halblösung zu bauen, die täglich
Handarbeit verlangt. Der Nutzer entscheidet das, nicht wir — aber er braucht
eine klare Aussage statt einer Bastelei.

---

## 8. Reihenfolge, die ich empfehlen würde

1. **Weg C testen** (zehn Minuten, klärt Befund 2 endgültig).
2. **Weg A recherchieren** — die Frage „welche Drittanbieter nimmt Zwift an"
   entscheidet, ob es eine saubere geräteunabhängige Lösung gibt.
3. Erst wenn beides trägt oder scheitert: `.zwo`-Generator bauen
   (`bikedash/zwo.py`, ~50 Zeilen auf Basis von `power.structure()`), inklusive
   Tests und dem Namensschema ohne Sonderzeichen.
4. Zustellung an den gefundenen Weg andocken, in `sync.yml` einhängen.
