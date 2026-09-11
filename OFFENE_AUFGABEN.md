# Offene Aufgaben

> Eine Liste, kein Roman. Was **wirklich** noch offen ist — mit Begründung, warum
> es offen ist, und was der nächste konkrete Schritt wäre.
>
> Nachbardokumente: [`FEATURE_INDEX.md`](FEATURE_INDEX.md) ·
> [`SICHERHEIT.md`](SICHERHEIT.md) · [`CLAUDE.md`](CLAUDE.md)
>
> Legende Dringlichkeit: 🔴 zuerst · 🟡 bald · 🔵 wenn Zeit ist

---

## A. Entscheidungen, die nur du treffen kannst

| # | Thema | Worum es geht | Vorschlag |
|---|---|---|---|
| 🔴 **S-1** | **Öffentliche Gesundheitsdaten** | Das Repo ist **public**, `mobile/today.json` veröffentlicht damit alle 4 h Recovery, Ruhepuls, Max-HF, Form — und seit heute auch dein bestes Zeitfenster. 50 Versionen liegen bereits in der Historie. Details: [`SICHERHEIT.md` §2](SICHERHEIT.md) | Drei Wege: **(a)** so lassen (bewusste Entscheidung, nichts zu tun); **(b)** `today.json` abspecken — nur noch `hr_low/high`, `cadence_low/high`, `target_zone`, `shift`; Recovery, TSB, `rationale`, `timing` bleiben im Dashboard und im Push. Kostet nur das Detail im PWA-Banner; **(c)** Repo privat + PWA über Pages eines separaten Repos oder GitHub Pro. — **Empfehlung: (b)**, das trifft 90 % des Nutzens bei fast keinem Aufwand. |
| 🔴 **S-7** | **Ist `APP_PASSWORD` im Streamlit-Deploy gesetzt?** | Ohne dieses Secret ist das Gate aus und das gehostete Dashboard **komplett offen** — dort liegen *alle* Daten, nicht nur der Tagesauszug. Von hier aus nicht prüfbar. | In Streamlit → App → Settings → Secrets nachsehen. Falls leer: langes Zufallspasswort setzen. 2 Minuten. |
| 🟡 **S-2** | **ntfy-Thema ratbar?** | Wer dein ntfy-Thema errät, liest deine Morgen-Reports mit. | Thema auf etwas Langes/Zufälliges ändern (z. B. `openssl rand -hex 12`), im `NTFY_TOPIC`-Secret **und** in der Handy-App. |
| 🟡 **F-1** | **Windrose: Zielbild fehlt** | Sie rechnet korrekt (verifiziert), sieht aber nicht aus wie vorgestellt. Das ist eine Design-Frage, kein Fehler — und ohne Zielbild nicht lösbar. | Sag, was du sehen willst: Nordnadel statt Buchstaben? Zwei Pfeile (woher der Wind kommt *und* wohin er drückt)? Gegen-/Rückenwind groß als Zahl? Böen? Eigener großer Screen statt kleiner Kachel? |
| 🔵 **F-2** | **Vorzeichen der Steigung** | Hängt von der Einbaurichtung des Handyhalters ab — am Schreibtisch nicht entscheidbar. | Einmal am Rad prüfen. Falls invertiert: „Richtung umkehren"-Schalter (Faktor ±1 in `localStorage`) — 10 Zeilen. |

---

## B. Muss am echten Gerät geprüft werden

Diese Sitzung hat **kein** Handy, **keinen** BLE-Sensor und **keinen** Zugriff auf
Open-Meteo (der Container blockt die API). Was hier trotzdem verifiziert wurde,
steht in der rechten Spalte.

| # | Zu prüfen | Wie | Hier schon abgesichert durch |
|---|---|---|---|
| 🔴 **T-1** | **Shift mit echtem Pulsgurt + Kadenzsensor** auf einer echten Fahrt | Android + Chrome, PWA über HTTPS, beide Sensoren koppeln | 14 Python-Tests + **7 Tests, die den echten PWA-Code in Node ausführen** + Browser-Test mit simulierten Werten (Screenshot: Kadenz 90 ✓, Puls 185 → „leichter") |
| 🔴 **T-2** | **Tageszeit-Empfehlung mit echter Open-Meteo-Antwort** | `python send_report.py --print` am PC | 14 Tests der Fensterlogik + 5 Tests des Antwort-Parsers gegen eine realitätsgetreue API-Antwort. **Der Live-Abruf selbst ist ungetestet.** |
| 🟡 **T-3** | **Kommt der Morgen-Report überhaupt an?** | Actions → „Morgen-Report" → *Run workflow* und aufs Handy schauen | Der Workflow existiert seit Längerem; ob `NTFY_TOPIC` gesetzt und abonniert ist, ist von hier nicht sichtbar |
| 🟡 **T-4** | **Feineinstellung der Fenster-Bewertung** | Ein paar Tage beobachten: passen die vorgeschlagenen Zeiten? | Stellschrauben stehen gesammelt oben in `bikedash/daytime.py`: `SETTLED_DAY_MAX`, `COMFORT_LOW/HIGH`, `CODE_PENALTY`, `ALT_MAX_PENALTY` |
| 🔵 **T-5** | **Windows-Pfad** (`.venv`, `.ps1`, Taskplaner) | einmal durchspielen | gar nicht — läuft hier auf Linux. Seit Actions den Sync übernimmt aber weitgehend irrelevant. |

---

## C. Bekannte Grenzen (kein Fehler, aber gut zu wissen)

| Thema | Grenze |
|---|---|
| **Shift ohne Sensoren** | Mit Pulsgurt **oder** Kadenzsensor gibt es jetzt eine Empfehlung (früher brauchte es zwingend Kadenz). Mit **beiden** ist sie am besten. Ohne beide bleibt die Kachel leer — das ist Physik, kein Fehler. |
| **Puls hinkt nach** | Die HF reagiert ~20–30 s verzögert auf die Leistung. Deshalb schaltet die Kachel erst nach 6 s Verweilzeit um (`DWELL_SECONDS`). Bei kurzen, harten Antritten ist sie damit bewusst träge. |
| **Zeitfenster kennt nur Wetter** | Termine, Verkehr, Sonnenuntergang und Straßenwahl gehen nicht ein. „Dunkel" wird nur über `is_day` aus der Vorhersage bestraft. |
| **Fenster ≠ Pflicht** | Mo–Fr 13–20 Uhr, Sa/So 8–20 Uhr sind hart verdrahtet (`WEEKDAY_WINDOW`/`WEEKEND_WINDOW` in `daytime.py`). Urlaubstage oder ein freier Freitag fallen dadurch unters Wochentagsfenster. |
| **TSB-Schwellen sind Startwerte** | `TSB_DEEP_FATIGUE`, `TSB_HARD_FLOOR` in `recommend.py` sind Praktiker-Heuristik, nicht an deinen Daten kalibriert. |
| **Wind-Labor ist Beta** | Unverändert, bewusst unfertig. |

---

## D. Ideen für später

| # | Idee |
|---|---|
| 🔵 I-1 | **Zeitfenster für morgen** mitschicken — die Vorhersage wird ohnehin für 2 Tage geholt (`hourly_forecast(days=2)`), die Logik kann es bereits. Fehlt nur die Anzeige. |
| 🔵 I-2 | **Rückenwind-Fenster**: nicht nur *wann* am wenigsten Wind weht, sondern wann die Windrichtung zur Lieblingsrunde passt (verbindet `daytime.py` mit `routing.py`). |
| 🔵 I-3 | **Shift-Rückblick**: nach der Fahrt zeigen, wie viel Zeit im Zielband war — braucht Aufzeichnung in der PWA. |
| 🔵 I-4 | **LTHR-Feldtest** im Dashboard anleiten. `zones.py` unterstützt LTHR bereits, der Wert wird aber nirgends erhoben. |
| 🔵 I-5 | **Wetter-Cache**: `daytime` und `weather` holen getrennt bei Open-Meteo. Ein gemeinsamer Abruf spart einen Request pro Lauf. |

---

## E. Erledigt in dieser Runde ✅

| Was | Wo |
|---|---|
| Gangempfehlung richtet sich nach **Puls + Kadenz** statt nur Kadenz | `bikedash/shift.py`, `mobile/ride.html` |
| Shift funktioniert jetzt auch **ohne Kadenzsensor** (nur Pulsgurt) | dieselbe Matrix |
| Verweilzeit gegen Flackern der Gang-Kachel | `DWELL_SECONDS` |
| **Tageszeit-Empfehlung** „wann heute fahren?" | `bikedash/daytime.py` |
| Zeitfenster im **Morgen-Push**, im Dashboard und im PWA-Banner | `report.py`, `dashboard.py`, `ride.html` |
| Stundenraster von Open-Meteo | `weather.hourly_forecast` |
| Sicherheitsprüfung der gesamten Historie | [`SICHERHEIT.md`](SICHERHEIT.md) |
| `report.yml` auf Lesezugriff beschränkt, `.env` in `.gitignore` | S-4, S-5 |
| Feature-Index | [`FEATURE_INDEX.md`](FEATURE_INDEX.md) |
| Tests 46 → 89 grün | `tests/` |
