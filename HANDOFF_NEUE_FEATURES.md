# Handoff: „Neue Features" für das Fahrrad-Dashboard

> **Zweck dieser Datei.** Diese Datei beschreibt sechs Features, die bereits im
> Branch `claude/fahrrad-app-neue-feature-ptpp0w` (Commit `544201d`)
> implementiert und getestet sind. Sie ist als vollständige Übergabe an eine
> neue Code-Instanz **am PC** gedacht: Absicht, Verhalten und der exakte Code
> jeder Änderung. Wenn am PC/Handy „nichts von den Features zu sehen ist", liegt
> das mit hoher Wahrscheinlichkeit **nicht** am Code, sondern daran, dass die
> laufende App/der lokale Checkout noch die alte Version zeigt. Abschnitt 0 löst
> das zuerst; Abschnitt 4 listet die *echten* offenen Punkte.

---

## 0. ZUERST LESEN: Warum „die Features fehlen" — und der schnellste Fix

Die Änderungen sind gepusht, aber an mehreren Stellen wird evtl. noch die alte
Version ausgeliefert. Bitte der Reihe nach prüfen:

1. **Lokaler Checkout ist auf dem falschen Branch.** Das erklärt „alle Features
   im Analyse-Dashboard fehlen komplett" — der PC sieht schlicht den alten Code.
   ```powershell
   git fetch origin
   git checkout claude/fahrrad-app-neue-feature-ptpp0w
   git pull
   ```
   Danach müssen `bikedash/milestones.py` und `bikedash/maintenance.py`
   existieren und `dashboard.py` die Tabs **„Orden"** und **„Wartung"** enthalten
   (`Select-String -Path dashboard.py -Pattern "tab_orden|tab_maint"`).

2. **Streamlit-Deploy läuft von `main`.** Das gehostete Dashboard zeigt die neuen
   Tabs nur, wenn es diesen Branch deployt — oder nach dem Merge nach `main`.
   Lokal am PC:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\streamlit.exe run dashboard.py
   ```
   Ohne lokale Daten (SQLite leer) stoppt das Dashboard mit dem Hinweis „Noch
   keine Fahrten" — dann erst **Synchronisieren** oder die vorhandene PC-DB
   nutzen. Die neuen Tabs brauchen Fahrten (kumulierte Gesamtdistanz).

3. **Die Ride-PWA (`mobile/ride.html`) kommt von GitHub Pages.**
   Windrose/Steigung/Gang erscheinen auf dem Handy erst, wenn Pages die neue
   Datei serviert (der Branch/`main`, aus dem Pages baut). Der Service Worker
   (`mobile/sw.js`) ist zwar network-first, aber im Zweifel: PWA vom Homescreen
   entfernen, Seite hart neu laden, neu „zum Startbildschirm hinzufügen".

4. **`today.json` wird lokal nicht automatisch gebaut** (nur im Actions-Sync):
   ```powershell
   .\.venv\Scripts\python.exe build_today.py
   ```
   Es enthält jetzt zusätzlich ein `milestone`-Feld für die PWA.

**Kurz:** Wenn alles fehlt → fast sicher Punkt 1/2 (alter Branch/alter Deploy).

---

## 1. Repo-Überblick (Kontext)

- **Dashboard**: `dashboard.py` (ein großes Streamlit-Skript, Tabs via
  `st.tabs`). Design-Tokens (`C_IN`, `C_ABOVE`, `PANEL_A`, `MUTED`, …) oben im File.
- **Logik**: Paket `bikedash/` (`recommend.py`, `dataprep.py`, `store.py`,
  `zones.py`, `form.py` …). Reine, testbare Module.
- **Persistenz**: `bikedash/store.py` (SQLite lokal / Postgres via
  `DATABASE_URL`). Kleindaten über `store.get_kv/set_kv` (Tabelle `app_kv`) —
  **kein Schema-Change** nötig.
- **Ride-PWA**: `mobile/ride.html` (Client-App: Leaflet, Web Bluetooth für
  HF/Kadenz, GPS, DeviceOrientation). Lädt `today.json` same-origin.
- **Tagesbrücke**: `build_today.py` → `mobile/today.json` (Empfehlung + Zonen +
  Wetter + jetzt Meilenstein), route-frei aus Datenschutzgründen.
- **Tests**: `pytest` in `tests/`, isolierte Wegwerf-DB via `conftest.py`.

---

## 2. Die sechs Features — Absicht, Ort, Verhalten

### #1 Verschleiss-Tracker (Dashboard)
**Absicht:** km pro Bauteil (Kette, Reifen, Kassette …) aus der kumulierten
Strava-Gesamtdistanz, mit Wartungs-Ampel und „gewechselt"-Reset.
**Ort:** neues Modul `bikedash/maintenance.py` (reine Logik + Persistenz über
`app_kv`); neuer Tab **„Wartung"** in `dashboard.py`.
**Verhalten:** Jedes Bauteil merkt sich `installed_km` (Stand beim letzten
Wechsel); Verschleiss = Gesamt-km minus `installed_km`. Ampel: ok / bald faellig
(ab 80 Prozent) / faellig (ab 100 Prozent). Buttons „Gewechselt",
„Alle ab jetzt frisch tracken", editierbare Intervalle via `st.data_editor`.
JSON unter `app_kv["maintenance_components"]`.

### #2 Orden und Meilensteine (Dashboard + PWA)
**Absicht:** „Walk to Mordor", aber abwechslungsreicher: kumulierte Distanz
schaltet benannte Orden bei beruehmten Distanzen frei (Radsport/Geo, Sci-Fi,
Fantasy, Astronomie); dazwischen generische Nahziele alle ~40 km (deterministische
Varianz), damit nie ein Ziel zu weit weg ist.
**Ort:** neues Modul `bikedash/milestones.py`; neuer Tab **„Orden"** in
`dashboard.py`; kompaktes `milestone`-Feld in `build_today.py`/`today.json`;
Anzeige im PWA-Banner (`showTodayBanner`).
**Verhalten:** `milestones.compute(total_km)` liefert freigeschaltete Orden, die
naechsten Ziele (Orden + Schritte gemischt, sortiert) und den Katalog.
Themen-Filter im Tab. Stellschrauben: `_CATALOG`, `GENERIC_STEP_KM` (40),
`GENERIC_VARIANCE` (0.4).

### #3 Kadenz-Untergrenze 90 auf 85 (Empfehlung + PWA-Farbe)
**Absicht:** 90 als Untergrenze war zu hoch; der gruene „im Soll"-Bereich soll
frueher greifen. **Ort:** `bikedash/recommend.py`, Templates `TEMPO`/`THRESHOLD`
`cadence "90-100"` auf `"85-100"`. Fliesst ueber `today.json` (`cadence_low`) in
die PWA und faerbt dort die Kadenz-Kachel automatisch (`setCadIndicator`).

### #4 Windrose (PWA `ride.html`)
**Absicht:** statt kleinem Eckpfeil eine echte Kompass-Rose: heading-up (deine
Fahrtrichtung oben), N/O/S/W aufrecht an gedrehter Position, „du"-Marker oben,
Pfeil fuer die relative Windrichtung, farbcodiert (Gegen-/Ruecken-/Seitenwind).
**Ort:** Wind-Kachel-SVG + `updateWindArrow()` in `ride.html`.
**OFFEN:** Nutzer sagt „noch nicht wie vorgestellt" — Zielbild klaeren
(Abschnitt 4).

### #5 Steigung (PWA `ride.html`)
**Absicht:** Steigung in Prozent aus der Sensor-Neigung (DeviceOrientation
`beta`), kalibrierbar, weil der Handyhalter nicht immer gleich sitzt.
**Ort:** neue Kachel + `updateGrad()`/`calibrateGrad()` in `ride.html`.
**Verhalten:** Kachel antippen setzt auf ebener Strecke „0 Prozent" (Offset in
`localStorage`); Steigung = `tan(beta - offset)`, geglaettet.
**Warum evtl. „fehlt":** braucht `DeviceOrientation` UND erteilte
Sensor-Berechtigung (iOS: Nutzergeste + Permission-Prompt, wird beim
Start/„Kompass" angefordert). Ohne Sensordaten bleibt die Kachel auf „—";
am Desktop gibt es keine Neigung. Bitte am Handy testen.

### #6 Gangempfehlung / Shift (PWA `ride.html`)
**Absicht:** aus der Kadenz relativ zum Zielband: zu langsam treten „leichter",
zu schnell „schwerer", im Band „halten".
**Ort:** neue Kachel + `updateShift()` in `ride.html`, aufgerufen aus `onCSC`.
**Warum es „nicht funktioniert":** `updateShift()` braucht `cadVal`, und das kommt
AUSSCHLIESSLICH von einem gekoppelten Bluetooth-Kadenzsensor (CSC). Ohne Sensor
bleibt die Kachel dauerhaft auf „warte auf Kadenz" — das ist die wahrscheinlichste
Ursache. Optionen (mit Nutzer klaeren): (a) so lassen und dokumentieren, dass ein
Kadenzsensor noetig ist; (b) Fallback: grobe Trittfrequenz aus Tempo + geschaetzter
Uebersetzung (ungenau); (c) Shift zusaetzlich an Ziel-Zone/Tempo koppeln, wenn kein
Sensor da ist. Empfehlung: erst (a) klarstellen, dann ggf. (b)/(c).

---

## 3. Verifikation am PC

```powershell
# 1) Tests (erwartet: 46 passed)
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q

# 2) Dashboard (braucht Fahrten in der DB, sonst „keine Fahrten"-Hinweis)
.\.venv\Scripts\streamlit.exe run dashboard.py    # Tabs „Orden" + „Wartung" pruefen

# 3) Ride-PWA lokal ansehen
cd mobile
..\.venv\Scripts\python.exe -m http.server 8800
#   -> http://localhost:8800/ride.html
```

Schneller Logik-Check ohne DB:
```powershell
.\.venv\Scripts\python.exe -c "from bikedash import milestones as m; v=m.compute(4200); print(len(v.earned),'/',v.badges_total, v.latest.name); [print(t.kind,t.label,round(t.remaining_km)) for t in v.next_targets]"
```

---

## 4. Offene Design-Punkte (vor „fertig" mit dem Nutzer klaeren)

1. **Windrose-Zielbild (#4).** Aktuell: heading-up, aufrechte N/O/S/W,
   „du"-Pfeil oben, ein relativer Windpfeil (rot=Gegen, gruen=Ruecken,
   orange=Seiten), km/h in der Mitte, Untertitel „Gegenwind X km/h · aus 225°".
   Konkrete Zielvorstellung erfragen, z. B.: Nordnadel statt Buchstaben? Zwei
   Pfeile (woher der Wind kommt UND wohin er drueckt)? Boeen-Anzeige?
   Gegen-/Rueckenwind-Komponente gross als Zahl? Rose als eigener grosser Screen
   statt kleiner Kachel?
2. **Vorzeichen der Steigung (#5).** Bergauf/-ab haengt von der Einbaurichtung
   des Halters ab. Falls invertiert: „Richtung umkehren"-Toggle (Faktor plus/minus 1
   in `localStorage`).
3. **Shift ohne Kadenzsensor (#6).** Siehe Feature #6 — Grundsatzentscheid.

---

## Anhang A — Exakter Diff der bestehenden Dateien (Commit `544201d`)

Woertlicher `git diff` der geaenderten (nicht-neuen) Dateien; per `git apply`
uebernehmbar bzw. als genauer Orts-/Kontextnachweis.

```diff
diff --git a/README.md b/README.md
index ce2be74..fdc8148 100644
--- a/README.md
+++ b/README.md
@@ -11,6 +11,11 @@ Körper-/Erholungsdaten aus **Whoop** automatisch zusammenführt und auswertet:
 - **💤 Erholung** – Recovery, Ruhepuls, HRV; Belastung → Erholung am Folgetag.
 - **🌬️ Wind-Labor (Beta)** – wie Gegen-/Rückenwind dein Tempo beeinflusst; fließt
   in die windkluge Routenplanung ein (Hinweg gegen den Wind, Rückweg mit Rückenwind).
+- **🏅 Orden & Meilensteine** – deine kumulierte Gesamtdistanz schaltet „Orden" bei
+  berühmten Distanzen frei (Tour de France, Länge Deutschlands, ein Shai-Hulud,
+  Erde → Mond …), dazwischen erreichbare Nahziele alle ~40 km.
+- **🔧 Verschleiß-Tracker** – km-Zähler pro Bauteil (Kette, Reifen, Kassette …) mit
+  Wartungs-Ampel und „gewechselt"-Reset.
 - **🧠 KI-Coach** – Klartext-Beratung aus deinen Daten (Claude API) + Wochenrückblick.
 - **📱 Morgen-Report** – heutige Empfehlung + Wetter + Form früh aufs Handy (via ntfy).
 
@@ -170,6 +175,8 @@ bike-dashboard/
 │  ├─ weather.py        # Wetter (Open-Meteo)
 │  ├─ windlab.py        # Wind-Performance-Analyse (Beta)
 │  ├─ form.py           # Form-Modell (CTL/ATL/TSB)
+│  ├─ milestones.py     # Distanz-Meilensteine & Orden
+│  ├─ maintenance.py    # Verschleiß-/Wartungs-Tracker
 │  ├─ backup.py         # Datensicherung
 │  ├─ coach.py          # KI-Coach (Claude API)
 │  └─ report.py         # Morgen-Report (ntfy-Push)
diff --git a/bikedash/recommend.py b/bikedash/recommend.py
index 6f66c89..8f0d1f4 100644
--- a/bikedash/recommend.py
+++ b/bikedash/recommend.py
@@ -25,8 +25,8 @@ TEMPLATES = {
     "REST":      dict(zone=None, base_min=0,  cadence="–",       rpe="–",   speed_factor=0.0),
     "RECOVERY":  dict(zone=1,    base_min=40, cadence="85–95",   rpe="2–3", speed_factor=0.82),
     "ENDURANCE": dict(zone=2,    base_min=90, cadence="85–95",   rpe="3–4", speed_factor=0.92),
-    "TEMPO":     dict(zone=3,    base_min=75, cadence="90–100",  rpe="5–6", speed_factor=1.05),
-    "THRESHOLD": dict(zone=4,    base_min=70, cadence="90–100",  rpe="7–8", speed_factor=1.00),
+    "TEMPO":     dict(zone=3,    base_min=75, cadence="85–100",  rpe="5–6", speed_factor=1.05),
+    "THRESHOLD": dict(zone=4,    base_min=70, cadence="85–100",  rpe="7–8", speed_factor=1.00),
 }
 
 TITLES = {
diff --git a/build_today.py b/build_today.py
index 26d27d0..492fdcc 100644
--- a/build_today.py
+++ b/build_today.py
@@ -25,7 +25,7 @@ import sys
 from pathlib import Path
 from typing import Any
 
-from bikedash import config, recommend, weather, zones
+from bikedash import config, dataprep, milestones, recommend, weather, zones
 
 ROOT = Path(__file__).resolve().parent
 DEFAULT_OUT = ROOT / "mobile" / "today.json"
@@ -49,6 +49,32 @@ def _parse_cadence(text: str) -> tuple[int | None, int | None]:
     return None, None
 
 
+def _milestone_payload() -> dict[str, Any] | None:
+    """Kompakter Meilenstein für die Ride-PWA: nächstes Ziel + Orden-Zähler.
+
+    Route-frei und ohne persönliche Koordinaten – nur aggregierte Kilometer.
+    Fehlt die Datenbasis, bleibt das Feld weg (unkritisch fürs Frontend).
+    """
+    try:
+        rides = dataprep.prep_rides()
+        if rides.empty:
+            return None
+        total_km = float(rides["distance_km"].sum())
+        mv = milestones.compute(total_km)
+        nxt = mv.next_targets[0] if mv.next_targets else None
+        return {
+            "total_km": round(total_km, 1),
+            "orden_earned": len(mv.earned),
+            "orden_total": mv.badges_total,
+            "next_name": nxt.label if nxt else None,
+            "next_icon": nxt.icon if nxt else None,
+            "next_remaining_km": round(nxt.remaining_km, 1) if nxt else None,
+            "next_km": round(nxt.km, 1) if nxt else None,
+        }
+    except Exception:  # noqa: BLE001
+        return None
+
+
 def _weather_payload(cfg: dict[str, Any]) -> dict[str, Any] | None:
     try:
         wx = weather.current(cfg)
@@ -81,6 +107,7 @@ def build(out_path: Path = DEFAULT_OUT, today: dt.date | None = None) -> dict[st
     # eine Route ab Zuhause würde die (als Secret gehaltene) Heimat-Koordinate
     # veröffentlichen. Die PWA plant die Route weiter clientseitig aus dem GPS.
     wx = _weather_payload(cfg)
+    milestone = _milestone_payload()
 
     payload: dict[str, Any] = {
         "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
@@ -114,6 +141,7 @@ def build(out_path: Path = DEFAULT_OUT, today: dt.date | None = None) -> dict[st
             "method": zones.method_label(rest_hr, lthr),
         },
         "weather": wx,
+        "milestone": milestone,
     }
 
     out_path.parent.mkdir(parents=True, exist_ok=True)
diff --git a/dashboard.py b/dashboard.py
index b1b0fc2..8f89e38 100644
--- a/dashboard.py
+++ b/dashboard.py
@@ -28,8 +28,8 @@ except Exception:
     pass
 
 from bikedash import (
-    backup, coach, config, dataprep, form, recommend, report, routing, store,
-    strava, weather, webauth, whoop, windlab, zones,
+    backup, coach, config, dataprep, form, maintenance, milestones, recommend,
+    report, routing, store, strava, weather, webauth, whoop, windlab, zones,
 )
 
 st.set_page_config(page_title="RIDE · Fahrrad-Dashboard", page_icon="🚴", layout="wide")
@@ -673,13 +673,19 @@ if not rec.empty and rec["recovery_score"].notna().any():
 else:
     c5.metric(":material/speed: Ø Tempo", f"{r['avg_speed_kmh'].mean():.1f} km/h")
 
-tab_today, tab1, tab2, tab3, tab_wind, tab_coach, tab_setup = st.tabs(
+(tab_today, tab1, tab2, tab3, tab_wind, tab_orden, tab_maint, tab_coach,
+ tab_setup) = st.tabs(
     [":material/bolt: Heute", ":material/trending_up: Leistung & Fortschritt",
      ":material/fitness_center: Trainingsbelastung", ":material/bedtime: Erholung",
-     ":material/air: Wind-Labor (Beta)", ":material/psychology: Coach",
+     ":material/air: Wind-Labor (Beta)", ":material/military_tech: Orden",
+     ":material/build: Wartung", ":material/psychology: Coach",
      ":material/tune: Einrichtung"]
 )
 
+# Kumulierte Gesamtdistanz über die GANZE Historie (nicht der Zeitraumfilter) –
+# Grundlage für Orden-Meilensteine und den Verschleiß-Tracker.
+total_km_all = float(rides["distance_km"].sum())
+
 
 # ===========================================================================
 # Tab: Heute (Empfehlung + Route)
@@ -1114,6 +1120,152 @@ with tab_wind:
         st.plotly_chart(figb, width="stretch")
 
 
+# ===========================================================================
+# Tab: Orden (Distanz-Meilensteine)
+# ===========================================================================
+with tab_orden:
+    st.subheader(":material/military_tech: Distanz-Meilensteine & Orden", anchor=False)
+    st.caption(
+        "Jede berühmte Distanz wird zum Orden, sobald deine aufsummierte "
+        "Fahrleistung sie überholt – dazwischen liegen erreichbare Nahziele."
+    )
+
+    all_themes = list(milestones.THEMES.keys())
+    picked = st.multiselect(
+        "Themen", options=all_themes, default=all_themes,
+        format_func=lambda k: milestones.THEMES[k],
+    )
+    themes = set(picked) if picked else None
+    mv = milestones.compute(total_km_all, themes=themes)
+
+    m1, m2, m3 = st.columns(3)
+    m1.metric(":material/route: Gesamtdistanz", de_num(mv.total_km, "km", 0))
+    m2.metric(":material/military_tech: Orden", f"{len(mv.earned)} / {mv.badges_total}")
+    m3.metric(":material/emoji_events: Zuletzt",
+              f"{mv.latest.icon} {mv.latest.name}" if mv.latest else "–")
+
+    st.markdown("#### Nächste Ziele")
+    if mv.next_targets:
+        for t in mv.next_targets:
+            head = f"{t.icon} **{t.label}**"
+            if t.kind == "orden" and t.blurb:
+                head += f" · _{t.blurb}_"
+            rem = f"noch **{de_num(t.remaining_km, 'km', 0)}**"
+            st.markdown(f"{head}  \n{rem} · Ziel bei {de_num(t.km, 'km', 0)}")
+            st.progress(min(max(t.progress, 0.0), 1.0))
+    else:
+        st.success("Alle Orden gesammelt – Wahnsinn! 🏆")
+
+    st.markdown("#### Deine Orden-Sammlung")
+    view_cat = sorted(
+        [b for b in mv.catalog if themes is None or b.theme in themes],
+        key=lambda b: b.km,
+    )
+    ocols = st.columns(4)
+    for i, b in enumerate(view_cat):
+        earned = b.km <= mv.total_km
+        opacity = "1" if earned else "0.4"
+        border = C_IN if earned else BORDER
+        lock = "" if earned else "🔒 "
+        with ocols[i % 4]:
+            st.markdown(
+                f'<div style="opacity:{opacity};background:linear-gradient(158deg,{PANEL_A},{PANEL_B});'
+                f'border:1px solid {border};border-radius:14px;padding:12px 14px;margin-bottom:10px;'
+                f'min-height:120px">'
+                f'<div style="font-size:30px;line-height:1">{b.icon}</div>'
+                f'<div style="font-weight:600;margin-top:6px;font-size:14px">{lock}{b.name}</div>'
+                f'<div style="color:{MUTED};font-size:12px;margin-top:1px">{de_num(b.km, "km", 0)}</div>'
+                f'<div style="color:{FAINT};font-size:11px;margin-top:4px;line-height:1.35">{b.blurb}</div>'
+                f'</div>',
+                unsafe_allow_html=True,
+            )
+
+
+# ===========================================================================
+# Tab: Wartung (Verschleiß-Tracker)
+# ===========================================================================
+with tab_maint:
+    st.subheader(":material/build: Verschleiß & Wartung", anchor=False)
+    maint_state = maintenance.load_state()
+    stats = maintenance.statuses(maint_state, total_km_all)
+    n_due = sum(1 for s in stats if s.status == maintenance.STATUS_DUE)
+    n_soon = sum(1 for s in stats if s.status == maintenance.STATUS_SOON)
+
+    k1, k2, k3 = st.columns(3)
+    k1.metric(":material/route: Kilometerstand", de_num(total_km_all, "km", 0),
+              help="Kumulierte Strava-Gesamtdistanz über die ganze Historie.")
+    k2.metric(":material/warning: Fällig", f"{n_due}")
+    k3.metric(":material/schedule: Bald fällig", f"{n_soon}")
+
+    st.caption(
+        "Verschleiß zählt ab dem Kilometerstand beim letzten Wechsel. Frisch "
+        "eingerichtet? Einmal **„Alle ab jetzt frisch“** klicken, dann stimmt die Basis."
+    )
+    if st.button(":material/restart_alt: Alle ab jetzt frisch tracken"):
+        maintenance.save_state(maintenance.reset_all(maint_state, total_km_all))
+        st.rerun()
+
+    STATUS_STYLE = {
+        maintenance.STATUS_OK:   (C_IN, "in Ordnung"),
+        maintenance.STATUS_SOON: (C_AMBER, "bald fällig"),
+        maintenance.STATUS_DUE:  (C_ABOVE, "fällig"),
+    }
+    for s in stats:
+        color, txt = STATUS_STYLE[s.status]
+        c1, c2 = st.columns([4, 1])
+        with c1:
+            rem = (f"noch {de_num(s.remaining_km, 'km', 0)}" if s.remaining_km >= 0
+                   else f"überfällig um {de_num(-s.remaining_km, 'km', 0)}")
+            st.markdown(
+                f"{s.icon} **{s.name}** · <span style='color:{color}'>{txt}</span>  \n"
+                f"<span style='color:{MUTED};font-size:13px'>"
+                f"{de_num(s.wear_km, 'km', 0)} / {de_num(s.interval_km, 'km', 0)} · {rem}"
+                f"</span>",
+                unsafe_allow_html=True,
+            )
+            st.progress(min(max(s.pct, 0.0), 1.0))
+        with c2:
+            if st.button("Gewechselt", key=f"maint_reset_{s.id}",
+                         help="Bauteil als frisch gewechselt markieren"):
+                maintenance.save_state(
+                    maintenance.reset_component(maint_state, s.id, total_km_all))
+                st.rerun()
+
+    with st.expander(":material/tune: Bauteile & Intervalle bearbeiten"):
+        st.caption("Zeilen hinzufügen/entfernen oder Intervalle ändern, dann speichern. "
+                   "Neue Bauteile starten ab dem aktuellen Kilometerstand.")
+        edit_df = pd.DataFrame([
+            {"Emoji": c["icon"], "Bauteil": c["name"], "Intervall (km)": int(c["interval_km"])}
+            for c in maint_state
+        ])
+        edited = st.data_editor(
+            edit_df, num_rows="dynamic", width="stretch", key="maint_editor",
+            column_config={
+                "Intervall (km)": st.column_config.NumberColumn(min_value=1, step=50),
+            },
+        )
+        if st.button(":material/save: Speichern", type="primary", key="maint_save"):
+            by_name = {c["name"].strip().lower(): c for c in maint_state}
+            new_state: list[dict] = []
+            for _, row in edited.iterrows():
+                name = str(row.get("Bauteil") or "").strip()
+                if not name:
+                    continue
+                prev = by_name.get(name.lower())
+                slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower())
+                new_state.append({
+                    "id": prev["id"] if prev else slug,
+                    "name": name,
+                    "icon": str(row.get("Emoji") or "🔧"),
+                    "interval_km": float(row.get("Intervall (km)") or 1000),
+                    "installed_km": float(prev["installed_km"] if prev else total_km_all),
+                })
+            if new_state:
+                maintenance.save_state(new_state)
+                st.success("Gespeichert.")
+                st.rerun()
+
+
 # ===========================================================================
 # Tab: KI-Coach
 # ===========================================================================
diff --git a/mobile/README.md b/mobile/README.md
index 1848dc0..1a4da5e 100644
--- a/mobile/README.md
+++ b/mobile/README.md
@@ -10,7 +10,12 @@ im Browser, **braucht keinen Server** und funktioniert auch unterwegs.
   in der App „Broadcast Heart Rate" aktivieren). Die Kachel färbt sich nach
   **HF-Zone** (Z1 blau … Z5 rot), berechnet aus deiner Max-HF.
 - **Trittfrequenz** per Bluetooth (Cadence-/CSC-Sensor).
-- **Wind** am aktuellen Standort (Open-Meteo) mit Pfeil + Gegen-/Rückenwind-Anzeige.
+- **Gangempfehlung** aus der Kadenz relativ zum Zielband: leichter / halten / schwerer.
+- **Wind als Kompass-Rose** am aktuellen Standort (Open-Meteo): heading-up (deine
+  Fahrtrichtung oben), aufrechte N/O/S/W-Beschriftung und ein Pfeil für die
+  **relative** Windrichtung, farbcodiert nach Gegen-/Rücken-/Seitenwind.
+- **Steigung** aus der Sensor-Neigung – **kalibrierbar** (Kachel antippen setzt auf
+  ebener Strecke „0 %", weil der Handyhalter nicht immer gleich sitzt).
 - **Karte** mit Live-Position und zurückgelegter Strecke.
 - **Bildschirm bleibt an** (Wake Lock) während der Fahrt.
 
diff --git a/mobile/ride.html b/mobile/ride.html
index d6aea15..780c972 100644
--- a/mobile/ride.html
+++ b/mobile/ride.html
@@ -103,9 +103,24 @@
   body.mapcollapsed .tile{min-height:0;}
   body.mapcollapsed .tile .val{font-size:62px;}
 
-  .wind .arrowwrap{position:absolute;top:11px;right:11px;width:38px;height:38px;opacity:.95;}
-  .wind .arrow{transform-origin:50% 50%;transition:transform .5s ease;}
-  .wind .sub{font-size:12px;color:var(--muted);margin-top:3px;font-weight:500;}
+  /* Wind als Kompass-Rose: Fahrtrichtung oben, N dreht mit, Pfeil = relative Windrichtung */
+  .wind .rosewrap{width:100%;display:flex;justify-content:center;margin:2px 0;}
+  .rose{width:112px;height:112px;max-width:100%;overflow:visible;}
+  body.mapcollapsed .rose{width:148px;height:148px;}
+  .rose-ring{fill:none;stroke:var(--border2);stroke-width:2;}
+  .rose-tick{stroke:var(--faint);stroke-width:1.5;}
+  .rose-lbl{fill:var(--muted);font-size:11px;font-weight:700;text-anchor:middle;dominant-baseline:middle;}
+  .rose-n{fill:var(--accent);}
+  #roseRing{transition:transform .4s ease;}
+  .rose-you{fill:var(--text);}
+  #windArrow{transition:transform .4s ease;}
+  .rose-val{fill:var(--text);font-size:23px;font-weight:700;text-anchor:middle;dominant-baseline:middle;font-variant-numeric:tabular-nums;}
+  .rose-unit{fill:var(--muted);font-size:9px;font-weight:600;text-anchor:middle;letter-spacing:.08em;}
+  .wind .sub{font-size:12px;color:var(--muted);margin-top:2px;font-weight:500;text-align:center;}
+  /* Gang- & Steigungs-Badge oben rechts (wie Kadenz-Badge) */
+  #shiftBadge,#gradBadge{position:absolute;top:11px;right:11px;font-size:12px;font-weight:700;
+    padding:3px 9px;border-radius:9px;background:#2a3142;color:var(--text);letter-spacing:.02em;
+    box-shadow:0 2px 8px -3px #000;transition:background .3s;}
 
   /* Gauge */
   .gauge{display:none;margin-top:6px;}
@@ -216,18 +231,40 @@
       <div class="gauge" id="gaugeCad"></div>
     </div>
 
-    <div class="tile wind">
+    <div class="tile wind" id="windTile">
       <div class="lbl"><i class="ic" data-ic="wind" style="--s:13px"></i> Wind</div>
-      <div class="arrowwrap">
-        <svg width="38" height="38" viewBox="0 0 46 46">
-          <g id="windArrow" class="arrow">
-            <path d="M23 7 L31.5 27 L23 22.5 L14.5 27 Z" fill="var(--accent)"/>
-          </g>
+      <div class="rosewrap">
+        <svg viewBox="0 0 100 100" class="rose" aria-label="Windrose">
+          <circle class="rose-ring" cx="50" cy="50" r="46"/>
+          <line class="rose-tick" x1="50" y1="6" x2="50" y2="12"/>
+          <line class="rose-tick" x1="94" y1="50" x2="88" y2="50"/>
+          <line class="rose-tick" x1="50" y1="94" x2="50" y2="88"/>
+          <line class="rose-tick" x1="6" y1="50" x2="12" y2="50"/>
+          <path class="rose-you" d="M50 1 L54 9 L46 9 Z"/>
+          <text id="rlN" class="rose-lbl rose-n" x="50" y="16">N</text>
+          <text id="rlE" class="rose-lbl" x="84" y="50">O</text>
+          <text id="rlS" class="rose-lbl" x="50" y="84">S</text>
+          <text id="rlW" class="rose-lbl" x="16" y="50">W</text>
+          <g id="windArrow"><path d="M50 31 L43 15 L50 19 L57 15 Z" fill="var(--accent)"/></g>
+          <text id="wind" class="rose-val" x="50" y="52">—</text>
+          <text class="rose-unit" x="50" y="65">km/h</text>
         </svg>
       </div>
-      <div class="valrow"><span id="wind" class="val">—</span><span class="unit">km/h</span></div>
       <div id="windSub" class="sub">aus —</div>
     </div>
+
+    <div id="gradTile" class="tile">
+      <div class="lbl"><i class="ic" data-ic="slope" style="--s:13px"></i> Steigung</div>
+      <div id="gradBadge">tippen = 0 %</div>
+      <div class="valrow"><span id="grad" class="val">—</span><span class="unit">%</span></div>
+    </div>
+
+    <div id="shiftTile" class="tile">
+      <div class="lbl"><i class="ic" data-ic="gear" style="--s:13px"></i> Gang</div>
+      <div id="shiftBadge">—</div>
+      <div class="valrow"><span id="shift" class="val" style="font-size:34px">–</span></div>
+      <div id="shiftSub" class="sub" style="font-size:12px;color:var(--muted);margin-top:3px;font-weight:500">warte auf Kadenz</div>
+    </div>
   </div>
 
   <div class="stats">
@@ -319,6 +356,8 @@ const ICON = {
   arrive:'<svg viewBox="0 0 24 24"><path d="M12 21s6.5-5.4 6.5-10.5A6.5 6.5 0 0 0 5.5 10.5C5.5 15.6 12 21 12 21Z"/><path d="M9.5 10.3l1.8 1.8 3.2-3.4"/></svg>',
   warn:'<svg viewBox="0 0 24 24"><path d="M12 4l9.3 16H2.7L12 4Z"/><path d="M12 10v4.2"/><circle cx="12" cy="17.4" r="0.7" fill="currentColor" stroke="none"/></svg>',
   chevron:'<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
+  slope:'<svg viewBox="0 0 24 24"><path d="M3 20h18"/><path d="M5 20L19 7"/><path d="M19 7v6"/></svg>',
+  gear:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.1"/><path d="M12 3.4v2.5M12 18.1v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M3.4 12h2.5M18.1 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8"/></svg>',
 };
 function buildIcons(root){ (root||document).querySelectorAll('[data-ic]').forEach(el=>{ el.innerHTML = ICON[el.dataset.ic]||''; }); }
 
@@ -336,6 +375,7 @@ let map=null, trail=null, marker=null, routeLayer=null;
 let windFrom=0, windSpeed=0, lastWindFetch=0;
 let route=null, lastZoneInTarget=true, searchIdx=0;
 let compassOn=false, compassHeading=null, lastArrow=0;
+let pitchRaw=null, gradOffset=0, gradVal=null, gradSmooth=null;
 
 // ---------- Helpers ----------
 // Karvonen/HRR: Anteil der Herzfrequenzreserve (mit Ruhepuls), sonst %max.
@@ -451,7 +491,16 @@ async function fetchWind(lat,lon){
 }
 function updateWindArrow(){
   const rel=(windFrom-heading+360)%360;
-  $('windArrow').setAttribute('transform',`rotate(${rel} 23 23)`);
+  // Heading-up: Himmelsrichtungs-Labels an ihre gedrehte Position setzen, aber
+  // aufrecht lassen (nur Position folgt der Fahrtrichtung, oben = wohin du fährst).
+  const R=34;
+  [['rlN',0],['rlE',90],['rlS',180],['rlW',270]].forEach(([id,b])=>{
+    const a=(b-heading)*Math.PI/180, el=$(id);
+    el.setAttribute('x',(50+R*Math.sin(a)).toFixed(1));
+    el.setAttribute('y',(50-R*Math.cos(a)).toFixed(1));
+  });
+  // Windpfeil zeigt die Richtung, AUS der der Wind kommt – relativ zur Fahrtrichtung.
+  $('windArrow').setAttribute('transform',`rotate(${rel} 50 50)`);
   const comp=windSpeed*Math.cos(rel*Math.PI/180), cross=Math.abs(windSpeed*Math.sin(rel*Math.PI/180));
   let label=(Math.abs(comp)<cross)?'Seitenwind':(comp>0?`Gegenwind ${Math.round(comp)}`:`Rückenwind ${Math.round(-comp)}`);
   if(label!=='Seitenwind') label+=' km/h';
@@ -461,6 +510,8 @@ function updateWindArrow(){
 
 // ---------- Kompass ----------
 function onOrient(e){
+  // beta = Vor-/Rück-Neigung → Steigung (unabhängig vom Kompass-Heading auswerten).
+  if(e.beta!=null && !isNaN(e.beta)){ pitchRaw=e.beta; updateGrad(); }
   let h=null;
   if(e.webkitCompassHeading!=null && !isNaN(e.webkitCompassHeading)) h=e.webkitCompassHeading;
   else if(e.absolute && e.alpha!=null){ const sa=(screen.orientation&&screen.orientation.angle)||0; h=(360-e.alpha+sa)%360; }
@@ -480,6 +531,45 @@ async function enableCompass(){
   }catch(err){ console.log(err); }
 }
 
+// ---------- Steigung (kalibrierbar) ----------
+// Der Handyhalter sitzt nicht immer gleich → auf ebener Strecke „tippen = 0 %".
+// Steigung = tan(Pitch − Kalibrier-Offset); geglättet gegen GPS-/Sensorzappeln.
+function updateGrad(){
+  if(pitchRaw==null) return;
+  const deg=pitchRaw-gradOffset;
+  const pct=Math.tan(deg*Math.PI/180)*100;
+  gradSmooth=(gradSmooth==null)?pct:gradSmooth*0.8+pct*0.2;
+  gradVal=gradSmooth;
+  $('grad').textContent=(gradSmooth>=0?'+':'')+gradSmooth.toFixed(1);
+  const col=gradSmooth>1?'#e8503a':(gradSmooth<-1?'#3a9bdc':'#2ecc71');
+  const b=$('gradBadge');
+  b.textContent=Math.abs(gradSmooth)<1?'flach':(gradSmooth>0?'bergauf':'bergab');
+  b.style.background=col; b.style.color='#0a0c10';
+}
+function calibrateGrad(){
+  if(pitchRaw==null){ enableCompass(); $('gradBadge').textContent='neige & tippe'; return; }
+  gradOffset=pitchRaw; gradSmooth=0;
+  localStorage.setItem('gradOffset',String(gradOffset));
+  if(navigator.vibrate) navigator.vibrate(60);
+  updateGrad();
+}
+
+// ---------- Gangempfehlung (Shift) ----------
+// Aus der Kadenz relativ zum Zielband: zu langsam treten → leichterer Gang,
+// zu schnell → schwererer Gang, im Band → halten.
+function updateShift(){
+  const el=$('shift'), sub=$('shiftSub'), badge=$('shiftBadge');
+  if(cadVal==null){ el.textContent='–'; el.style.color='var(--text)'; sub.textContent='warte auf Kadenz';
+    badge.textContent='—'; badge.style.background='#2a3142'; badge.style.color='var(--text)'; return; }
+  const st=statusOf('cad',cadVal);
+  let txt,sym,col,hint;
+  if(st==='below'){ txt='leichter'; sym='⬇'; col='#3a9bdc'; hint=`Kadenz ${cadVal} < ${cadLo} — leichteren Gang, schneller treten`; }
+  else if(st==='above'){ txt='schwerer'; sym='⬆'; col='#e8503a'; hint=`Kadenz ${cadVal} > ${cadHi} — schwereren Gang, kräftiger treten`; }
+  else { txt='halten'; sym='✓'; col='#2ecc71'; hint=`Kadenz ${cadVal} im Ziel ${cadLo}–${cadHi}`; }
+  el.textContent=txt; el.style.color=col; sub.textContent=hint;
+  badge.textContent=sym; badge.style.background=col; badge.style.color='#0a0c10';
+}
+
 // ---------- Heart rate ----------
 async function connectHR(){
   if(!navigator.bluetooth){ alert('Web Bluetooth nur in Chrome/Edge auf Android.'); return; }
@@ -519,7 +609,7 @@ function onCSC(v){
   const f=v.getUint8(0); let off=1; if(f&0x01) off+=6;
   if(f&0x02){ const c=v.getUint16(off,true),t=v.getUint16(off+2,true);
     if(lastCrank!=null){ const dc=(c-lastCrank+65536)%65536, dt=(t-lastCrankT+65536)%65536;
-      if(dt>0){ const rpm=Math.round((dc/(dt/1024))*60); cadVal=rpm; $('cad').textContent=rpm; updateGauge('cad',rpm); setCadIndicator(rpm); } }
+      if(dt>0){ const rpm=Math.round((dc/(dt/1024))*60); cadVal=rpm; $('cad').textContent=rpm; updateGauge('cad',rpm); setCadIndicator(rpm); updateShift(); } }
     lastCrank=c; lastCrankT=t; }
 }
 // Trittfrequenz-Kachel je nach Zielband (cadLo–cadHi aus recommend.py) einfärben.
@@ -630,7 +720,7 @@ function applyTodayZones(d){
   $('maxhr').value=maxHR; $('resthr').value=restHR; $('targetZone').value=targetZone;
   $('cadLo').value=cadLo; $('cadHi').value=cadHi;
   $('targetKm').value=targetKm; $('distLbl').textContent=targetKm;
-  refreshAllGauges();
+  refreshAllGauges(); updateShift();
   if(hrVal!=null) onHR(hrVal);   // Zonenfarbe/-Badge mit neuen Grenzen neu setzen
 }
 function showTodayBanner(d){
@@ -642,6 +732,9 @@ function showTodayBanner(d){
   if(rec.hr_low) bits.push(`Z${rec.zone_number} ${rec.hr_low}–${rec.hr_high} bpm`);
   if(rec.cadence && rec.cadence!=='–') bits.push(rec.cadence+' U/min');
   if(rec.target_distance_km) bits.push(`Ziel ~${Math.round(rec.target_distance_km)} km · „Route" tippen`);
+  const ms=d.milestone;
+  if(ms && ms.next_name && ms.next_remaining_km!=null)
+    bits.push(`${ms.next_icon||'🏅'} noch ${Math.round(ms.next_remaining_km)} km bis ${ms.next_name}`);
   $('navMeta').textContent=bits.join(' · ');
 }
 
@@ -650,6 +743,7 @@ function loadSettings(){
   const s=JSON.parse(localStorage.getItem('rideCfg')||'{}');
   maxHR=s.maxHR||198; restHR=s.restHR||72; targetZone=s.targetZone||2; orsKey=s.orsKey||''; targetKm=s.targetKm||30; windklug=s.windklug!==false;
   cadLo=s.cadLo||85; cadHi=s.cadHi||95; spdLo=s.spdLo||22; spdHi=s.spdHi||30;
+  gradOffset=parseFloat(localStorage.getItem('gradOffset')||'0')||0;
   $('maxhr').value=maxHR; $('resthr').value=restHR; $('targetZone').value=targetZone; $('orsKey').value=orsKey;
   $('targetKm').value=targetKm; $('distLbl').textContent=targetKm; $('windklug').checked=windklug;
   $('cadLo').value=cadLo; $('cadHi').value=cadHi; $('spdLo').value=spdLo; $('spdHi').value=spdHi;
@@ -672,6 +766,7 @@ $('hrBtn').onclick=connectHR;
 $('cadBtn').onclick=connectCad;
 $('targetKm').oninput=e=>$('distLbl').textContent=e.target.value;
 document.querySelector('.tile.wind').onclick=enableCompass;
+$('gradTile').onclick=calibrateGrad;
 $('mapToggle').onclick=()=>{
   const collapsed=document.body.classList.toggle('mapcollapsed');
   $('mapToggleTxt').textContent=collapsed?'Karte zeigen':'Karte ausblenden';
@@ -679,7 +774,7 @@ $('mapToggle').onclick=()=>{
 };
 
 buildIcons(); $('startBtn').querySelector('.ic').innerHTML=ICON.play;
-loadSettings(); buildGauges(); initMap(); startGeo(); loadToday();
+loadSettings(); buildGauges(); updateShift(); initMap(); startGeo(); loadToday();
 document.addEventListener('visibilitychange',async()=>{ if(document.visibilityState==='visible'&&running&&!wakeLock){ try{ wakeLock=await navigator.wakeLock.request('screen'); }catch(e){} } });
 if('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(()=>{});
 </script>
diff --git a/tests/test_build_today.py b/tests/test_build_today.py
index a40a4a8..3b0fe4b 100644
--- a/tests/test_build_today.py
+++ b/tests/test_build_today.py
@@ -57,6 +57,12 @@ def test_build_writes_valid_today_json(tmp_path):
     assert z["rest_hr"] == 52          # aus dem Recovery-Ruhepuls im Helper
     assert z["method"] == "Karvonen/HRR"
 
+    # Meilenstein-Feld ist da und (mit geseedeten Fahrten) befüllt.
+    assert "milestone" in data
+    assert data["milestone"] is not None
+    assert data["milestone"]["orden_total"] >= 1
+    assert data["milestone"]["total_km"] > 0
+
     # today.json ist bewusst route-frei (Datenschutz): kein Route-Feld.
     assert "route" not in data
     # Ohne Heimat-Koordinaten & ohne Netz kein Wetter.

```

---

## Anhang B — Neue Dateien (vollstaendig)

### `bikedash/milestones.py`
```python
"""Distanz-Meilensteine & Orden aus der kumulierten Strava-Gesamtdistanz.

Im Stil der „Walk to Mordor"-Apps, aber mit mehr Abwechslung: Jede berühmte
Distanz (Radsport, Geografie, Sci-Fi, Fantasy, Astronomie) wird zu einem **Orden**,
sobald deine aufsummierte Fahrleistung sie überschreitet. Zwischen den benannten
Orden liegen generische **Nahziele** alle ~40 km (mit deterministischer Varianz),
damit das nächste Ziel nie zu weit weg ist.

Die Logik ist rein und deterministisch (keine DB, kein Netz) – der Aufrufer
reicht nur die Gesamtkilometer herein. So ist sie leicht testbar und lässt sich
sowohl im Dashboard als auch in ``build_today.py`` (für die Ride-PWA) nutzen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Themen der Orden – für Filter/Legende im Dashboard.
THEMES = {
    "geo": "Radsport & Geografie",
    "scifi": "Sci-Fi",
    "fantasy": "Fantasy",
    "astro": "Astronomie",
}

# Kuratierter Orden-Katalog: (km, Name, Emoji, Thema, Kurzbeschreibung).
# Werte sind bewusst „gut genug" recherchiert und teils mit ca. gekennzeichnet;
# es geht um Motivation und Augenzwinkern, nicht um Vermessungsgenauigkeit.
_CATALOG: list[tuple[float, str, str, str, str]] = [
    (0.4,      "Ein Shai-Hulud",            "🪱", "scifi",   "Die Länge eines ausgewachsenen Sandwurms von Arrakis."),
    (1.6,      "Imperialer Sternzerstörer", "🚀", "scifi",   "Kiel bis Bug eines Sternzerstörers – 1,6 km Kampfmacht."),
    (8.8,      "Höhe des Mount Everest",    "🏔️", "astro",   "So hoch ist der höchste Berg der Erde – nur eben senkrecht."),
    (42.195,   "Marathon-Distanz",          "🏃", "geo",     "Die klassischen 42,195 km von Marathon nach Athen."),
    (45.0,     "Rover Opportunity",         "🔴", "scifi",   "Die Gesamtstrecke des Mars-Rovers Opportunity."),
    (50.0,     "Länge von Rama",            "🛸", "scifi",   "Der Zylinderweltraumkörper aus Arthur C. Clarkes Rendezvous mit Rama."),
    (88.0,     "10× Mount Everest",         "⛰️", "astro",   "Zehn Everests aufeinandergestapelt."),
    (98.0,     "Nord-Ostsee-Kanal",         "🌊", "geo",     "Von Kiel-Holtenau bis Brunsbüttel."),
    (100.0,    "Metrisches Century",        "💯", "geo",     "Die ersten 100 Kilometer – ein Radsport-Klassiker."),
    (117.0,    "Hadrianswall",              "🧱", "geo",     "Roms Nordgrenze quer durch Britannien."),
    (120.0,    "Durchmesser Todesstern",    "⭐", "scifi",   "Der erste Todesstern, einmal quer (~120 km)."),
    (160.9,    "Imperiales Century",        "🇺🇸", "geo",     "160,9 km – die 100 Meilen am Stück."),
    (227.0,    "Ötztaler Radmarathon",      "🚵", "geo",     "Der legendäre Alpen-Marathon: 227 km, 5.500 Höhenmeter."),
    (257.0,    "Paris–Roubaix",             "🪨", "geo",     "Die Hölle des Nordens über das Kopfsteinpflaster."),
    (273.0,    "Uferlänge des Bodensees",   "🏞️", "geo",     "Einmal komplett um den Bodensee herum."),
    (298.0,    "Mailand–Sanremo",           "🇮🇹", "geo",     "La Primavera – der längste Klassiker im Profikalender."),
    (408.0,    "Flughöhe der ISS",          "🛰️", "astro",   "So hoch über dir kreist die Internationale Raumstation."),
    (483.0,    "Die Mauer",                 "🧊", "fantasy", "300 Meilen Eis, die den Norden von Westeros trennen."),
    (640.0,    "Deutschland (West–Ost)",    "🧭", "geo",     "Einmal quer durch die Republik in der Breite."),
    (876.0,    "Deutschland (Nord–Süd)",    "🇩🇪", "geo",     "Von List auf Sylt bis Oberstdorf im Allgäu."),
    (1200.0,   "Paris–Brest–Paris",         "🚴", "geo",     "Der Ur-Brevet: 1.200 km am Stück, seit 1891."),
    (1233.0,   "Länge des Rheins",          "🌊", "geo",     "Von den Alpen bis zur Nordsee."),
    (2172.0,   "Auenland → Schicksalsberg", "💍", "fantasy", "Frodos Weg vom Auenland bis nach Mordor (ca. 2.172 km)."),
    (2850.0,   "Länge der Donau",           "🏞️", "geo",     "Vom Schwarzwald bis ans Schwarze Meer."),
    (3500.0,   "Tour de France",            "🏆", "geo",     "Die Gesamtdistanz einer ganzen Grande Boucle."),
    (6650.0,   "Länge des Nils",            "🏜️", "astro",   "Der längste Fluss der Erde."),
    (12756.0,  "Erddurchmesser",            "🌍", "astro",   "Einmal quer durch den Planeten."),
    (21196.0,  "Chinesische Mauer",         "🐉", "geo",     "Die gesamte kartierte Länge der Großen Mauer."),
    (31415.0,  "Umfang eines Halo-Rings",   "💫", "scifi",   "Einmal rund um einen Halo (~10.000 km Durchmesser)."),
    (40075.0,  "Erdumfang am Äquator",      "🌐", "astro",   "Einmal komplett um die Erde herum."),
    (384400.0, "Erde → Mond",               "🌕", "astro",   "Die ultimative Distanz: bis zum Mond."),
]

GENERIC_STEP_KM = 40.0    # mittlerer Abstand der Nahziele
GENERIC_VARIANCE = 0.4    # ± dieser Anteil (deterministische „Zufalls"-Streuung)
_NEAR_NAMED_KM = 9.0      # Nahziele so nah an einem Orden werden unterdrückt


@dataclass(frozen=True)
class Badge:
    km: float
    name: str
    icon: str
    theme: str
    blurb: str


@dataclass
class Target:
    """Ein anstehendes Ziel (Orden oder generisches Nahziel)."""
    km: float
    label: str
    icon: str
    kind: str            # "orden" | "step"
    remaining_km: float
    progress: float      # 0..1 – Fortschritt seit dem vorigen Meilenstein
    blurb: str = ""


@dataclass
class MilestoneView:
    total_km: float
    badges_total: int
    earned: list[Badge]              # freigeschaltete Orden, jüngster zuerst
    upcoming_badges: list[Badge]     # noch offene Orden, nächster zuerst
    next_targets: list[Target]       # gemischte Nahziele (Orden + Schritte), aufsteigend
    latest: Badge | None = None      # zuletzt freigeschalteter Orden
    catalog: list[Badge] = field(default_factory=list)


def _catalog() -> list[Badge]:
    return [Badge(km, name, icon, theme, blurb)
            for km, name, icon, theme, blurb in _CATALOG]


def _jitter(i: int) -> float:
    """Deterministischer Pseudo-Zufall in [-1, 1) aus dem Index (stabil über Läufe)."""
    h = math.sin((i + 1) * 12.9898) * 43758.5453
    return (h - math.floor(h)) * 2.0 - 1.0


def generic_milestones(up_to_km: float) -> list[float]:
    """Aufsteigende, generische Meilensteine bis ``up_to_km`` (auf 5 km gerundet).

    Abstände schwanken deterministisch um ``GENERIC_STEP_KM`` (±Varianz), die
    Werte sind auf „schöne" 5-km-Schritte gerundet und streng monoton steigend.
    """
    out: list[float] = []
    cum = 0.0
    i = 0
    guard = 0
    while cum <= up_to_km and guard < 100000:
        gap = GENERIC_STEP_KM * (1.0 + GENERIC_VARIANCE * _jitter(i))
        cum += max(gap, 5.0)
        nice = round(cum / 5.0) * 5.0
        if not out or nice > out[-1]:
            out.append(nice)
        i += 1
        guard += 1
    return out


def _next_generic(total_km: float, count: int) -> list[float]:
    """Die nächsten ``count`` generischen Meilensteine oberhalb ``total_km``."""
    horizon = total_km + GENERIC_STEP_KM * (count + 2) * (1 + GENERIC_VARIANCE)
    return [m for m in generic_milestones(horizon) if m > total_km][:count]


def compute(total_km: float, *, themes: set[str] | None = None,
            n_targets: int = 3) -> MilestoneView:
    """Baut die Meilenstein-Ansicht aus der Gesamtdistanz.

    ``themes`` filtert optional die Orden (None = alle). ``n_targets`` steuert,
    wie viele kommende Nahziele (Orden + generische Schritte gemischt) geliefert
    werden.
    """
    total_km = max(0.0, float(total_km))
    catalog = _catalog()
    if themes:
        cat = [b for b in catalog if b.theme in themes]
    else:
        cat = catalog

    earned = [b for b in cat if b.km <= total_km]
    upcoming = [b for b in cat if b.km > total_km]
    earned_recent = sorted(earned, key=lambda b: b.km, reverse=True)
    upcoming_sorted = sorted(upcoming, key=lambda b: b.km)

    # „Voriger Meilenstein" = Untergrenze für die Fortschrittsbalken.
    prev_named = max((b.km for b in cat if b.km <= total_km), default=0.0)

    # Kandidaten fürs nächste Ziel: kommende Orden + generische Schritte mischen.
    named_targets = [
        Target(km=b.km, label=b.name, icon=b.icon, kind="orden",
               remaining_km=b.km - total_km, progress=0.0, blurb=b.blurb)
        for b in upcoming_sorted[:n_targets + 2]
    ]
    named_kms = [b.km for b in upcoming_sorted]
    step_targets = [
        Target(km=m, label=f"{int(round(m)):,} km".replace(",", "."),
               icon="🎯", kind="step", remaining_km=m - total_km, progress=0.0)
        for m in _next_generic(total_km, n_targets + 3)
        # generische Schritte nah an einem Orden weglassen (kein Doppel-Ziel)
        if all(abs(m - nk) > _NEAR_NAMED_KM for nk in named_kms)
    ]

    merged = sorted(named_targets + step_targets, key=lambda t: t.km)[:n_targets]
    # Fortschritt je Ziel: seit dem jeweils vorausgehenden Meilenstein.
    lower = prev_named
    for t in merged:
        span = t.km - lower
        t.progress = 0.0 if span <= 0 else max(0.0, min(1.0, (total_km - lower) / span))
        lower = t.km

    return MilestoneView(
        total_km=round(total_km, 1),
        badges_total=len(cat),
        earned=earned_recent,
        upcoming_badges=upcoming_sorted,
        next_targets=merged,
        latest=earned_recent[0] if earned_recent else None,
        catalog=catalog,
    )

```

### `bikedash/maintenance.py`
```python
"""Verschleiß-/Wartungs-Tracker für Fahrrad-Komponenten.

Zählt die gefahrenen Kilometer je Bauteil (Kette, Reifen, Kassette …) auf Basis
der kumulierten Strava-Gesamtdistanz und warnt, wenn ein Wartungsintervall
erreicht ist. Jedes Bauteil merkt sich den **Kilometerstand beim letzten
Wechsel** (``installed_km``); der Verschleiß ist die Differenz zum aktuellen
Gesamtstand.

Persistenz läuft über den vorhandenen ``app_kv``-Schlüssel-Wert-Speicher
(eine JSON-Liste unter ``KV_KEY``) – nichts Neues am DB-Schema. Die Rechenlogik
ist rein und ohne DB testbar; nur ``load_state`` / ``save_state`` sprechen mit
dem Store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import store

KV_KEY = "maintenance_components"

# Bauteil-Vorlagen mit typischen Wechselintervallen (km). Startwerte als grobe
# Praktiker-Richtwerte – jederzeit im Dashboard anpassbar.
DEFAULT_COMPONENTS: list[dict] = [
    {"id": "chain_lube",  "name": "Kette schmieren", "icon": "🛢️", "interval_km": 250},
    {"id": "chain",       "name": "Kette",           "icon": "🔗", "interval_km": 3000},
    {"id": "cassette",    "name": "Kassette",        "icon": "⚙️", "interval_km": 9000},
    {"id": "tire_front",  "name": "Reifen vorn",     "icon": "🛞", "interval_km": 5000},
    {"id": "tire_rear",   "name": "Reifen hinten",   "icon": "🛞", "interval_km": 3500},
    {"id": "brake_pads",  "name": "Bremsbeläge",     "icon": "🛑", "interval_km": 2000},
    {"id": "cables",      "name": "Züge & Hüllen",   "icon": "🕸️", "interval_km": 6000},
    {"id": "bar_tape",    "name": "Lenkerband",      "icon": "🎀", "interval_km": 8000},
]

# Ampel-Schwellen als Anteil des Intervalls.
WARN_FRAC = 0.8    # ab hier „bald fällig"

STATUS_OK = "ok"
STATUS_SOON = "soon"
STATUS_DUE = "due"


@dataclass
class ComponentStatus:
    id: str
    name: str
    icon: str
    interval_km: float
    installed_km: float
    wear_km: float          # seit letztem Wechsel gefahren
    remaining_km: float     # bis zur nächsten Wartung (negativ = überfällig)
    pct: float              # Verschleiß in [0, 1+] (Anteil des Intervalls)
    status: str             # ok | soon | due


def default_state() -> list[dict]:
    """Frischer Zustand: alle Vorlagen mit Kilometerstand 0 beim Einbau."""
    return [{**c, "installed_km": 0.0} for c in DEFAULT_COMPONENTS]


def _sanitize(comp: dict) -> dict:
    return {
        "id": str(comp.get("id") or comp.get("name", "part")),
        "name": str(comp.get("name", "Bauteil")),
        "icon": str(comp.get("icon", "🔧")),
        "interval_km": max(1.0, float(comp.get("interval_km", 1000) or 1000)),
        "installed_km": max(0.0, float(comp.get("installed_km", 0.0) or 0.0)),
    }


def load_state() -> list[dict]:
    """Bauteil-Liste aus dem Store; fällt auf die Vorlagen zurück."""
    raw = store.get_kv(KV_KEY)
    if not raw:
        return default_state()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return default_state()
    if not isinstance(data, list) or not data:
        return default_state()
    return [_sanitize(c) for c in data if isinstance(c, dict)]


def save_state(state: list[dict]) -> None:
    store.set_kv(KV_KEY, json.dumps([_sanitize(c) for c in state], ensure_ascii=False))


def status_of(comp: dict, total_km: float) -> ComponentStatus:
    """Verschleiß-Status eines Bauteils beim aktuellen Gesamtkilometerstand."""
    c = _sanitize(comp)
    interval = c["interval_km"]
    installed = min(c["installed_km"], float(total_km))
    wear = max(0.0, float(total_km) - installed)
    remaining = interval - wear
    pct = wear / interval if interval > 0 else 0.0
    if pct >= 1.0:
        status = STATUS_DUE
    elif pct >= WARN_FRAC:
        status = STATUS_SOON
    else:
        status = STATUS_OK
    return ComponentStatus(
        id=c["id"], name=c["name"], icon=c["icon"], interval_km=interval,
        installed_km=installed, wear_km=round(wear, 1),
        remaining_km=round(remaining, 1), pct=pct, status=status,
    )


def statuses(state: list[dict], total_km: float) -> list[ComponentStatus]:
    """Alle Bauteile bewerten, überfälligste zuerst (höchster Verschleiß)."""
    out = [status_of(c, total_km) for c in state]
    return sorted(out, key=lambda s: s.pct, reverse=True)


def reset_component(state: list[dict], comp_id: str, total_km: float) -> list[dict]:
    """Bauteil als frisch gewechselt markieren (installed_km = aktueller Stand)."""
    new = []
    for c in state:
        c = _sanitize(c)
        if c["id"] == comp_id:
            c["installed_km"] = float(total_km)
        new.append(c)
    return new


def reset_all(state: list[dict], total_km: float) -> list[dict]:
    """Alle Bauteile ab jetzt frisch tracken."""
    return [{**_sanitize(c), "installed_km": float(total_km)} for c in state]

```

### `tests/test_milestones.py`
```python
"""Tests für die Distanz-Meilensteine & Orden (reine Logik, keine DB)."""

from __future__ import annotations

from bikedash import milestones


def test_zero_km_has_no_earned_but_targets():
    mv = milestones.compute(0)
    assert mv.earned == []
    assert mv.latest is None
    assert mv.badges_total == len(milestones._CATALOG)
    assert mv.next_targets
    assert mv.next_targets[0].remaining_km > 0


def test_earned_latest_and_bounds():
    mv = milestones.compute(300)
    assert any(b.name == "Marathon-Distanz" for b in mv.earned)
    assert all(b.km <= 300 for b in mv.earned)
    assert mv.latest is not None and mv.latest.km <= 300
    # latest ist der jüngste (höchste) freigeschaltete Orden
    assert mv.latest.km == max(b.km for b in mv.earned)


def test_targets_sorted_ahead_and_progress_bounded():
    mv = milestones.compute(150, n_targets=3)
    kms = [t.km for t in mv.next_targets]
    assert kms == sorted(kms)
    assert all(t.km > 150 for t in mv.next_targets)
    assert all(0.0 <= t.progress <= 1.0 for t in mv.next_targets)
    assert all(t.remaining_km > 0 for t in mv.next_targets)


def test_theme_filter_only_counts_that_theme():
    scifi = sum(1 for c in milestones._CATALOG if c[3] == "scifi")
    mv = milestones.compute(1e9, themes={"scifi"})
    assert mv.badges_total == scifi
    assert all(b.theme == "scifi" for b in mv.earned)
    # der volle Katalog bleibt für die Galerie erhalten
    assert len(mv.catalog) == len(milestones._CATALOG)


def test_generic_milestones_strictly_increasing_with_variance():
    ms = milestones.generic_milestones(500)
    assert ms and ms[0] > 0
    assert all(b > a for a, b in zip(ms, ms[1:]))
    gaps = [b - a for a, b in zip([0.0] + ms, ms)]
    # ~40 km ± 40 %, auf 5 km gerundet → grob in diesem Fenster
    assert all(5.0 <= g <= milestones.GENERIC_STEP_KM * 1.4 + 5 for g in gaps)


def test_generic_is_deterministic():
    assert milestones.generic_milestones(300) == milestones.generic_milestones(300)

```

### `tests/test_maintenance.py`
```python
"""Tests für den Verschleiß-/Wartungs-Tracker.

Die conftest-Fixture lenkt den Store auf eine Wegwerf-DB – Save/Load geht also
gegen eine isolierte Datenbank.
"""

from __future__ import annotations

from bikedash import maintenance


def test_empty_store_yields_defaults():
    state = maintenance.load_state()
    assert state == maintenance.default_state()
    assert "chain" in {c["id"] for c in state}


def test_status_due_when_over_interval():
    comp = {"id": "chain", "name": "Kette", "icon": "🔗",
            "interval_km": 3000, "installed_km": 0.0}
    s = maintenance.status_of(comp, 3200)
    assert s.wear_km == 3200
    assert s.remaining_km == -200
    assert s.status == maintenance.STATUS_DUE
    assert s.pct > 1.0


def test_status_soon_near_interval():
    comp = {"id": "c", "name": "C", "icon": "🔧",
            "interval_km": 1000, "installed_km": 0.0}
    assert maintenance.status_of(comp, 850).status == maintenance.STATUS_SOON
    assert maintenance.status_of(comp, 500).status == maintenance.STATUS_OK


def test_reset_component_zeroes_wear():
    state = maintenance.default_state()
    state = maintenance.reset_component(state, "chain", 5000)
    chain = next(c for c in state if c["id"] == "chain")
    assert chain["installed_km"] == 5000
    assert maintenance.status_of(chain, 5000).wear_km == 0


def test_installed_km_capped_prevents_negative_wear():
    comp = {"id": "x", "name": "X", "icon": "🔧",
            "interval_km": 1000, "installed_km": 5000}
    assert maintenance.status_of(comp, 3000).wear_km == 0


def test_save_load_roundtrip():
    state = maintenance.reset_all(maintenance.default_state(), 1234.0)
    maintenance.save_state(state)
    loaded = maintenance.load_state()
    assert loaded and all(c["installed_km"] == 1234.0 for c in loaded)


def test_statuses_sorted_by_wear_desc():
    state = [
        {"id": "a", "name": "A", "icon": "🔧", "interval_km": 1000, "installed_km": 0.0},
        {"id": "b", "name": "B", "icon": "🔧", "interval_km": 1000, "installed_km": 900.0},
    ]
    ranked = maintenance.statuses(state, 1000.0)
    assert [s.id for s in ranked] == ["a", "b"]  # a stärker verschlissen

```
