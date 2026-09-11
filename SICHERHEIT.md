# Sicherheits- und Datenschutz-Prüfung

**Stand: 11.09.2026** · geprüft auf Branch `claude/adoring-knuth-jepz3l`

Geprüft wurde: die **gesamte** Git-Historie (50 Commits, 112 Blobs), alle
getrackten Dateien, die drei GitHub-Actions-Workflows, der Passwort-Schutz des
Dashboards und alles, was öffentlich ausgeliefert wird.

**Kurzfassung:** Es sind **keine Zugangsdaten** im Repo oder in der Historie —
weder jetzt noch jemals. Die Trennung Code / Secrets ist sauber gebaut. Was es
gibt, ist eine bewusste Entscheidung mit Folgen: **das Repo ist öffentlich, und
`mobile/today.json` veröffentlicht damit täglich Gesundheitsdaten** (Abschnitt 2).

---

## 1. Was geprüft wurde — und sauber ist ✅

| Prüfung | Ergebnis |
|---|---|
| `config.toml` je committet? | **nein** — 0 Commits in der gesamten Historie |
| `tokens.json` je committet? | **nein** — 0 Commits |
| `.streamlit/secrets.toml` je committet? | **nein** — 0 Commits |
| Datenbank (`*.db`, `data/`) je committet? | **nein** — 0 Commits |
| API-Schlüsselmuster in allen 112 Blobs der Historie<br>(`sk-ant-…`, `ghp_…`, `github_pat_…`, `AKIA…`, private Schlüssel, JWTs, Postgres-URLs mit Passwort) | **kein Treffer** — nur Platzhalter wie `postgresql://USER:PW@HOST/DB` in der Anleitung |
| Hartkodierte Schlüssel im Code / in der PWA | **keine** — der ORS-Key kommt aus `localStorage` des Nutzers, `config.py` liest alles aus Umgebung oder `config.toml` |
| Heimat-Koordinate in `mobile/today.json` | **nicht enthalten** — bewusst route- und koordinatenfrei, durch Tests abgesichert |
| Passwort-Schutz des gehosteten Dashboards | **vorhanden und korrekt** (`webauth.py`): konstantzeitiger Vergleich (`hmac.compare_digest`), Sperre nach 5 Fehlversuchen, `st.stop()` blockiert die Seite wirklich |
| Secrets in Workflow-Logs | **nein** — alle Secrets nur als `env:`, nichts wird ausgegeben |
| Workflow-Trigger | nur `schedule` + `workflow_dispatch` — **kein** `pull_request`, also keine Secret-Preisgabe an fremde Forks |

---

## 2. Befund: das Repo ist öffentlich ⚠️

`maximilian-crypto/bike-dashboard` ist **public**. Damit ist `mobile/today.json`
für jeden lesbar — über GitHub Pages *und* über `raw.githubusercontent.com`, auch
ohne Pages. Der Sync-Workflow committet die Datei **alle 4 Stunden**; es gibt
inzwischen **50 Versionen** seit dem 01.09.2026. Die Historie ist damit eine
lückenlose Zeitreihe.

Öffentlich einsehbar sind pro Tag:

| Feld | Beispiel aus der aktuellen Datei |
|---|---|
| `recovery_score` | `50.0` — **Whoop-Gesundheitsdatum** |
| `zones.max_hr` / `rest_hr` | `197` / `68` — **Ruhepuls ist ein Gesundheitsindikator** |
| `recommendation.hr_low/high` | `145`–`158` |
| `tsb`, `week_hours` | `4.1`, `1.4` h — Trainingszustand |
| `milestone.total_km` | `892.5` km |
| `rationale` | Klartextsätze über Erholung und Ermüdung |
| `weather` | Wetter **am Heimatort** (nicht die Koordinate selbst) |
| `timing` *(neu)* | bestes Zeitfenster, z. B. „17–19 Uhr" |

**Zwei Dinge sind dabei ehrlich zu benennen:**

1. **Gesundheitsdaten.** Ruhepuls, Max-HF und Recovery sind besondere Daten nach
   Art. 9 DSGVO. Sie zu veröffentlichen ist erlaubt — es sind deine eigenen —
   aber es ist eine Entscheidung, die man bewusst treffen sollte, nicht eine, in
   die man hineinrutscht.
2. **Das neue `timing`-Feld macht daraus einen Tagesplan.** „Empfehlung: 29 km,
   bestes Fenster 17–19 Uhr" sagt öffentlich, wann jemand voraussichtlich nicht
   zu Hause ist. Zusammen mit der Wetterhistorie (die den Ort grob eingrenzt) ist
   das qualitativ etwas anderes als eine nackte Kilometerzahl.

Das ist **kein Programmfehler** — `today.json` ist absichtlich so gebaut, und die
Koordinate wird korrekt herausgehalten. Es ist eine **Produktentscheidung**, die
jetzt ansteht. Lösungsoptionen stehen als Aufgabe **S-1** in
[`OFFENE_AUFGABEN.md`](OFFENE_AUFGABEN.md).

---

## 3. Kleinere Punkte

| # | Punkt | Bewertung | Status |
|---|---|---|---|
| S-2 | **ntfy-Themen sind öffentlich lesbar.** Wer das Thema kennt oder errät, liest deine Morgen-Reports (Recovery, Puls, Form) mit. Das Thema ist ein Secret und steht korrekt nicht im Repo — aber das Beispiel in `.streamlit/secrets.toml.example` (`max-bike-7f3a`) ist als Muster kurz und ratbar. | mittel | offen |
| S-3 | **Brute-Force-Bremse im Dashboard ist nur eine Bremse.** Der Fehlversuchszähler liegt in `st.session_state` — ein neuer Browser-Tab setzt ihn zurück. Bei einem langen, zufälligen `APP_PASSWORD` unkritisch; bei einem kurzen nicht. | niedrig | offen |
| S-4 | `report.yml` hatte keine `permissions`-Angabe und lief damit mit den Repo-Standardrechten, obwohl der Job nur liest. | niedrig | **behoben** — `permissions: contents: read` |
| S-5 | `.env` fehlte in `.gitignore`. Keine solche Datei vorhanden, aber ein leicht zu übersehender Stolperstein. | niedrig | **behoben** |
| S-6 | `keepalive.yml` und `sync.yml` brauchen `contents: write` (sie committen). Das ist korrekt und nicht weiter einschränkbar. | — | in Ordnung |

---

## 4. Was ausdrücklich **nicht** geprüft werden konnte

Ehrlichkeitshalber, damit niemand eine Sicherheit annimmt, die hier nicht belegt ist:

- **Die GitHub-Repo-Einstellungen selbst** (ist Pages aktiv? welche Standardrechte
  haben Workflow-Tokens? sind Secrets korrekt gesetzt?) — dafür fehlt dieser
  Sitzung der Zugriff. Bitte in **Settings → Pages** und **Settings → Actions →
  Workflow permissions** nachsehen.
- **Ob die Secrets echt und aktuell sind** (z. B. ob ein alter Strava-Key noch
  irgendwo gültig ist). Sichtbar ist nur, dass keiner im Repo liegt.
- **Der laufende Streamlit-Deploy** — ob dort tatsächlich ein `APP_PASSWORD`
  gesetzt ist. Der Code erzwingt es nicht: **ohne** das Secret ist das Gate
  komplett aus und das Dashboard offen (so dokumentiert in `DEPLOY.md`).
  → Aufgabe **S-7**.

---

## 5. Wiederholen der Prüfung

```bash
# 1) Wurde je eine Geheimnis-Datei committet?
for f in config.toml tokens.json .streamlit/secrets.toml .env; do
  echo "$f: $(git log --all --oneline -- "$f" | wc -l) Commits"; done

# 2) Schlüsselmuster in der GANZEN Historie
git rev-list --objects --all | awk '{print $1}' | sort -u \
 | git cat-file --batch-check='%(objectname) %(objecttype)' 2>/dev/null \
 | awk '$2=="blob"{print $1}' \
 | while read -r b; do git cat-file blob "$b"; done \
 | grep -nEi "sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|postgres(ql)?://[^ \"']*:[^ \"'@]+@"

# 3) Was heute öffentlich in der PWA-Datei steht
python -m json.tool mobile/today.json
```
