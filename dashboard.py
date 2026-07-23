"""Streamlit-Dashboard: Fahrrad-Auswertung aus Strava + Whoop,
inkl. Tagesempfehlung mit generierter Route.

Starten mit:   streamlit run dashboard.py
"""

from __future__ import annotations

import datetime as dt
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Beim Hosting kommen die Zugangsdaten aus Streamlit-Secrets. bikedash.config
# liest sie aus den Umgebungsvariablen – deshalb spiegeln wir die (flachen)
# Secrets vor dem ersten Import in os.environ. Lokal ohne secrets.toml passiert
# nichts.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float, bool)):
            os.environ.setdefault(_k, str(_v))
except Exception:
    pass

from bikedash import (
    backup, coach, config, dataprep, form, maintenance, milestones, recommend,
    report, routing, store, strava, weather, webauth, whoop, windlab, zones,
)

st.set_page_config(page_title="RIDE · Fahrrad-Dashboard", page_icon="🚴", layout="wide")

# ---------------------------------------------------------------------------
# Design-Tokens (matchen die mobile App unter mobile/ride.html 1:1)
# ---------------------------------------------------------------------------
BG = "#0a0c10"
PANEL_A, PANEL_B = "#161a23", "#11141b"
BORDER, BORDER2 = "#232936", "#2c3342"
TEXT, MUTED, FAINT = "#eef1f6", "#7e8696", "#565d6b"
ACCENT, ACCENT2 = "#ff5a36", "#ff7a52"
C_IN, C_BELOW, C_ABOVE = "#2ecc71", "#3a9bdc", "#e8503a"
C_AMBER = "#f2c40f"

BAND_COLORS = {"green": C_IN, "yellow": C_AMBER, "red": C_ABOVE, "unknown": FAINT}
BAND_TEXT = {"green": "Gut erholt", "yellow": "Mittel", "red": "Niedrig", "unknown": "Keine Daten"}
ZONE_COLORS = {1: C_BELOW, 2: C_IN, 3: C_AMBER, 4: "#ef8a2b", 5: C_ABOVE}

# Bike-Wortmarke — dieselbe SVG-Iconform wie in der mobilen App.
BRAND_SVG = (
    '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="#ff5a36" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="5.6" cy="16.3" r="3.4"/><circle cx="18.4" cy="16.3" r="3.4"/>'
    '<path d="M5.6 16.3l4-8h5.2l-3.4 8"/><path d="M9.6 8.3h6l2.8 8"/>'
    '<path d="M14.8 8.3l1-2h2"/></svg>'
)

# ---------------------------------------------------------------------------
# Globales Design: Space Grotesk, Premium-Dunkelpalette, veredelte Widgets
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');

      html, body, .stApp, [class*="css"] {{
          font-family: 'Space Grotesk', system-ui, -apple-system, sans-serif !important;
          font-variant-numeric: tabular-nums;
      }}
      .stApp {{
          background:
              radial-gradient(120% 60% at 50% -10%, #131826 0%, rgba(19,24,38,0) 60%),
              {BG} !important;
      }}
      .block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1300px; }}
      [data-testid="stSidebar"] {{ background: #0c0f15; border-right: 1px solid {BORDER}; }}
      h1, h2, h3, h4 {{ letter-spacing: -0.02em; font-weight: 600; }}
      hr {{ border-color: {BORDER} !important; }}

      /* Marken-Kopfzeile */
      .brandbar {{ display:flex; align-items:baseline; gap:10px; margin-bottom: 4px; }}
      .brandbar .word {{ font-size: 26px; font-weight: 700; letter-spacing: .16em; color: {TEXT}; }}
      .brandbar .sub {{ font-size: 14px; color: {MUTED}; font-weight: 500; padding-left: 4px;
          border-left: 1px solid {BORDER2}; padding-left: 10px; }}
      .sidebrand {{ display:flex; align-items:center; gap:9px; padding: 2px 0 4px; }}
      .sidebrand .word {{ font-size: 19px; font-weight: 700; letter-spacing: .18em; color: {TEXT}; }}
      .sidebrand-sub {{ font-size: 12px; color: {MUTED}; margin: -4px 0 14px 35px; font-weight: 500; }}

      /* Metrik-Kacheln */
      [data-testid="stMetric"] {{
          background: linear-gradient(158deg, {PANEL_A}, {PANEL_B});
          border: 1px solid {BORDER}; border-radius: 16px; padding: 14px 18px;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.03), 0 8px 20px -16px #000;
      }}
      [data-testid="stMetricLabel"] {{ color: {MUTED} !important; font-size: .78rem !important;
          text-transform: uppercase; letter-spacing: .08em; font-weight: 600 !important; }}
      [data-testid="stMetricValue"] {{ font-weight: 600 !important; letter-spacing: -.02em; }}

      /* Reiter */
      .stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {BORDER}; }}
      .stTabs [data-baseweb="tab"] {{
          height: 42px; border-radius: 10px 10px 0 0; color: {MUTED};
          font-weight: 600; letter-spacing: .01em; padding: 0 14px;
      }}
      .stTabs [aria-selected="true"] {{ color: {TEXT} !important; }}
      .stTabs [data-baseweb="tab-highlight"] {{ background-color: {ACCENT} !important; height: 2.5px; }}

      /* Buttons */
      .stButton > button, .stDownloadButton > button, .stLinkButton > a {{
          border-radius: 12px !important; border: 1px solid {BORDER2} !important;
          font-weight: 600 !important; transition: transform .08s ease;
      }}
      .stButton > button:active {{ transform: scale(.98); }}
      .stButton > button[kind="primary"] {{
          background: linear-gradient(158deg, {ACCENT2}, {ACCENT}) !important;
          border-color: {ACCENT} !important; color: #1a0a05 !important;
      }}

      /* Expander */
      [data-testid="stExpander"] {{
          background: linear-gradient(158deg, {PANEL_A}, {PANEL_B});
          border: 1px solid {BORDER}; border-radius: 16px; overflow: hidden;
      }}

      /* Hinweisboxen */
      [data-testid="stAlert"] {{ border-radius: 14px; }}

      /* Tabellen */
      [data-testid="stDataFrame"] {{ border-radius: 14px; overflow: hidden; border: 1px solid {BORDER}; }}

      /* Chat */
      [data-testid="stChatMessage"] {{
          background: linear-gradient(158deg, {PANEL_A}, {PANEL_B});
          border: 1px solid {BORDER}; border-radius: 14px;
      }}

      /* Eingaben */
      [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
      [data-baseweb="select"] > div {{
          border-radius: 10px !important; border-color: {BORDER2} !important;
      }}

      /* Empfehlungs-Karte (Heute-Tab) */
      .reco-card {{
          background: linear-gradient(158deg, {PANEL_A} 0%, {PANEL_B} 100%);
          border: 1px solid {BORDER}; border-left: 4px solid var(--accent, {ACCENT});
          border-radius: 18px; padding: 22px 26px; margin-bottom: 10px;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.03), 0 10px 24px -18px #000;
      }}
      .reco-title {{ font-size: 1.6rem; font-weight: 600; margin: 4px 0 0 0; letter-spacing: -.02em; }}
      .badge {{
          display: inline-block; padding: 3px 12px; border-radius: 999px;
          font-size: .78rem; font-weight: 700; color: {BG}; letter-spacing: .02em;
      }}
      .zone-pill {{
          display:inline-block; padding:2px 10px; border-radius:8px;
          font-size:.8rem; font-weight:700; margin-right:6px;
      }}

      /* Metrik-Werte nie hart abschneiden (gilt app-weit) */
      [data-testid="stMetricValue"] {{
          white-space: normal !important; overflow-wrap: anywhere;
          font-size: clamp(1.1rem, 1.5vw, 1.7rem) !important; line-height: 1.12;
      }}

      /* Empfehlungs-Kacheln im Heute-Tab (bruchsicher, adaptive Größe) */
      .mcards {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
          gap:10px; margin: 4px 0 8px; }}
      .mcard {{ background: linear-gradient(158deg, {PANEL_A}, {PANEL_B});
          border:1px solid {BORDER}; border-radius:14px; padding:12px 15px;
          box-shadow: inset 0 1px 0 rgba(255,255,255,.03), 0 8px 20px -18px #000;
          display:flex; flex-direction:column; min-height:86px; }}
      .mcard .l {{ font-size:.72rem; color:{MUTED}; text-transform:uppercase;
          letter-spacing:.08em; font-weight:600; }}
      .mcard .v {{ font-size: clamp(1.2rem, 1.9vw, 1.7rem); font-weight:600;
          letter-spacing:-.02em; margin-top:auto; padding-top:6px; overflow-wrap:anywhere;
          font-variant-numeric:tabular-nums; }}
      .mcard .v.accent {{ color: var(--mc, {TEXT}); }}
      .mcard .s {{ font-size:.72rem; color:{FAINT}; margin-top:3px; }}

      /* schlanke Scrollbar */
      ::-webkit-scrollbar {{ width: 9px; height: 9px; }}
      ::-webkit-scrollbar-track {{ background: transparent; }}
      ::-webkit-scrollbar-thumb {{ background: {BORDER2}; border-radius: 6px; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Plotly-Theme (gilt automatisch für alle Diagramme im Dashboard)
# ---------------------------------------------------------------------------
pio.templates["bikedash"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family="Space Grotesk, system-ui, sans-serif", color=TEXT, size=13),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=[ACCENT, C_BELOW, C_IN, C_AMBER, "#ef8a2b", C_ABOVE],
        xaxis=dict(gridcolor="#1c212b", zerolinecolor="#1c212b", linecolor=BORDER2),
        yaxis=dict(gridcolor="#1c212b", zerolinecolor="#1c212b", linecolor=BORDER2),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(t=48),
    )
)
pio.templates.default = "plotly_dark+bikedash"


def _rec_trend(rec: pd.DataFrame, col: str) -> dict | None:
    """Lineare Regression eines Erholungs-Werts über die Zeit.

    Gibt die Trend-Rate (pro Tag/Woche), Stützpunkte für die Trendlinie und
    die Anzahl gültiger Tage zurück – oder ``None``, wenn zu wenige oder zu
    dicht beieinanderliegende Datenpunkte für eine sinnvolle Analyse vorliegen.
    Nutzt bewusst ``numpy.polyfit`` (kein statsmodels-Zwang wie bei px-OLS).
    """
    if col not in rec.columns:
        return None
    d = rec[["date", col]].dropna()
    if len(d) < 3:
        return None
    t = (d["date"] - d["date"].min()).dt.total_seconds() / 86400.0  # Tage
    tvals = t.to_numpy(dtype=float)
    span = float(tvals.max())
    if span <= 0:  # alle Punkte am selben Tag → keine Steigung bestimmbar
        return None
    slope, intercept = np.polyfit(tvals, d[col].to_numpy(dtype=float), 1)
    return {
        "slope_day": float(slope),
        "per_week": float(slope) * 7,
        "xs": [d["date"].min(), d["date"].max()],
        "ys": [float(intercept), float(slope) * span + intercept],
        "n": int(len(d)),
        "days": int(round(span)),
    }


def _trend_chart(rec: pd.DataFrame, col: str, title: str, unit: str,
                 good_dir: str, stable_thresh: float, rising_meaning: str,
                 falling_meaning: str) -> None:
    """Linien-Chart mit gestrichelter Trendlinie plus Kurz-Trendanalyse.

    ``good_dir`` = ``"up"`` (steigend ist gut, z. B. HRV) oder ``"down"``
    (fallend ist gut, z. B. Ruhepuls). ``stable_thresh`` ist die Wochen-Rate,
    unterhalb derer der Trend als „stabil" gilt.
    """
    fig = px.line(rec, x="date", y=col, markers=True, title=title)
    fig.update_layout(xaxis_title="", yaxis_title=unit)
    tr = _rec_trend(rec, col)
    if tr is not None:
        fig.add_trace(go.Scatter(
            x=tr["xs"], y=tr["ys"], mode="lines", name="Trend",
            line=dict(color=C_AMBER, width=2, dash="dash"),
        ))
        fig.update_layout(legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, width="stretch")

    if tr is None:
        st.caption("Noch zu wenige Datenpunkte für eine Trendanalyse.")
        return

    rate = tr["per_week"]
    if abs(rate) < stable_thresh:
        st.caption(f"➡️ Stabil (~{rate:+.1f} {unit}/Woche über {tr['days']} Tage).")
        return
    rising = rate > 0
    is_good = (rising and good_dir == "up") or (not rising and good_dir == "down")
    arrow = "📈" if rising else "📉"
    verb = "steigt" if rising else "sinkt"
    tone = "✅" if is_good else "⚠️"
    meaning = rising_meaning if rising else falling_meaning
    st.caption(
        f"{arrow} {verb} um **{abs(rate):.1f} {unit}/Woche** über {tr['days']} "
        f"Tage {tone} — {meaning}"
    )


def _wx_icon(code: int) -> str:
    """Material-Symbol-Name für einen WMO-Wettercode."""
    if code in (0, 1):
        return "clear_day"
    if code in (2, 3):
        return "partly_cloudy_day"
    if code in (45, 48):
        return "foggy"
    if code in (71, 73, 75, 77, 85, 86):
        return "ac_unit"
    if code in (95, 96, 99):
        return "thunderstorm"
    if code >= 50:
        return "rainy"
    return "wb_sunny"


# ---------------------------------------------------------------------------
# Daten laden (gecached)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=120)
def load_rides() -> pd.DataFrame:
    return dataprep.prep_rides()


@st.cache_data(ttl=120)
def load_recovery() -> pd.DataFrame:
    return dataprep.prep_recovery()


@st.cache_data(ttl=120)
def load_cycles() -> pd.DataFrame:
    return dataprep.prep_cycles()


@st.cache_data(ttl=1800)
def load_weather():
    try:
        return weather.current(config.load_config_raw())
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=120)
def load_wind_fit():
    return windlab.analyze()


def de_num(x: float, unit: str = "", dec: int = 0) -> str:
    s = f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s}{(' ' + unit) if unit else ''}"


def route_map(rt: routing.Route) -> go.Figure:
    df = pd.DataFrame({"lat": rt.lats, "lon": rt.lons})
    center = {"lat": sum(rt.lats) / len(rt.lats), "lon": sum(rt.lons) / len(rt.lons)}
    span = max(max(rt.lats) - min(rt.lats), max(rt.lons) - min(rt.lons), 0.01)
    zoom = max(9, min(14, 12 - (span * 12)))
    try:
        fig = px.line_map(df, lat="lat", lon="lon", map_style="open-street-map",
                          zoom=zoom, center=center)
    except AttributeError:  # ältere plotly-Version
        fig = px.line_mapbox(df, lat="lat", lon="lon", mapbox_style="open-street-map",
                             zoom=zoom, center=center)
    fig.update_traces(line=dict(width=4, color=ACCENT))
    fig.add_trace(go.Scattermap(
        lat=[rt.lats[0]], lon=[rt.lons[0]], mode="markers",
        marker=dict(size=12, color=C_IN), name="Start", hoverinfo="text", text=["Start"],
    ))
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=420, showlegend=False)
    return fig


def brand_bar(sub: str = "Fahrrad-Dashboard") -> None:
    st.markdown(
        f"""<div class="brandbar">{BRAND_SVG}<span class="word">RIDE</span>
        <span class="sub">{sub}</span></div>""",
        unsafe_allow_html=True,
    )


def reco_cards(items: list[tuple]) -> None:
    """Bruchsichere Empfehlungs-Kacheln. items: (label, value, sub, accent)."""
    html = ['<div class="mcards">']
    for label, value, sub, accent in items:
        style = f' style="--mc:{accent}"' if accent else ""
        acc = " accent" if accent else ""
        sub_html = f'<div class="s">{sub}</div>' if sub else ""
        html.append(
            f'<div class="mcard"><div class="l">{label}</div>'
            f'<div class="v{acc}"{style}>{value}</div>{sub_html}</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Einrichtungs-Oberfläche (Anleitung + Eingabefelder direkt im Hub)
# ---------------------------------------------------------------------------
STRAVA_HELP = """
**So bekommst du die Strava-Zugangsdaten:**
1. Öffne die Strava-API-Seite (Button unten) – du musst bei Strava eingeloggt sein.
2. Lege eine Anwendung an:
   - **Application Name:** z. B. `Mein Fahrrad-Dashboard`
   - **Category:** `Data Importer`
   - **Website:** `http://localhost`
   - **Authorization Callback Domain:** **`localhost`**  ← nur dieses eine Wort!
3. Nach dem Speichern zeigt Strava **Client ID** und **Client Secret** – beides
   hier unten eintragen.
"""

WHOOP_HELP = """
**So bekommst du die Whoop-Zugangsdaten:**
1. Öffne das Whoop-Developer-Portal (Button unten) und melde dich an.
2. Erstelle eine neue App. Trage als **Redirect URI** exakt ein:
   `{redirect}`
3. Aktiviere die Scopes: `read:recovery`, `read:cycles`, `read:sleep`,
   `read:workout`, `read:profile`, `read:body_measurement`, `offline`.
4. Kopiere **Client ID** und **Client Secret** hier unten herein.
"""

ORS_HELP = """
**Für die generierte Karten-Route:**
1. Kostenloses Konto bei OpenRouteService anlegen (Button unten) und unter
   *Dashboard → Tokens* einen **API-Key** erstellen → hier eintragen.
2. **Heimat-Koordinaten** (Start deiner Runden): in Google Maps an deinen
   Startort **rechtsklicken** – die erste Zeile sind `Breite, Länge` (lat, lon).
"""

ORS_PROFILES = ["cycling-regular", "cycling-road", "cycling-mountain", "cycling-electric"]


def _do_connect(provider: str) -> None:
    if config.is_cloud():
        st.info(
            "Der Verbinden-Knopf mit Browser-Login läuft nur **lokal** auf deinem "
            "PC. Verbinde einmalig lokal mit der Cloud-Datenbank "
            "(`$env:DATABASE_URL=…; python connect.py`) – die Tokens landen dann in "
            "der Cloud-DB und werden hier automatisch genutzt (siehe DEPLOY.md).",
            icon=":material/info:",
        )
        return
    raw = config.load_config_raw()
    if not config.provider_creds_ok(raw, provider):
        st.error(f"Bitte zuerst gültige {provider.capitalize()}-Zugangsdaten oben speichern.",
                 icon=":material/error:")
        return
    raw.setdefault("server", {}).setdefault("port", 8721)
    try:
        with st.spinner(
            f"Browser-Login für {provider.capitalize()} … bitte im geöffneten "
            "Fenster bestätigen und dann hierher zurückkommen."
        ):
            (strava if provider == "strava" else whoop).connect(raw)
        st.success(
            f"{provider.capitalize()} verbunden. Jetzt links **Synchronisieren** klicken.",
            icon=":material/check_circle:",
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Verbindung fehlgeschlagen: {exc}", icon=":material/error:")


def render_setup() -> None:
    raw = config.load_config_raw()
    s = raw.get("strava", {})
    w = raw.get("whoop", {})
    o = raw.get("ors", {})
    a = raw.get("athlete", {})
    port = int(raw.get("server", {}).get("port", 8721))

    st.subheader(":material/tune: Einrichtung", anchor=False)
    st.caption(
        "Klappe die Schritte auf, folge der Anleitung, trage die Werte ein und "
        "klicke Speichern. Alles bleibt lokal in `config.toml`."
    )

    sc = st.columns(3)
    strava_ok, whoop_ok, ors_ok = strava.is_connected(), whoop.is_connected(), config.has_routing(raw)
    sc[0].metric("Strava", "Verbunden" if strava_ok else "Ausstehend",
                delta="bereit" if strava_ok else "einrichten",
                delta_color="normal" if strava_ok else "off")
    sc[1].metric("Whoop", "Verbunden" if whoop_ok else "Ausstehend",
                delta="bereit" if whoop_ok else "einrichten",
                delta_color="normal" if whoop_ok else "off")
    sc[2].metric("Routen (ORS)", "Bereit" if ors_ok else "Ausstehend",
                delta="aktiv" if ors_ok else "einrichten",
                delta_color="normal" if ors_ok else "off")

    with st.expander("1) Strava — Fahrtdaten", icon=":material/directions_bike:",
                     expanded=not strava_ok):
        st.markdown(STRAVA_HELP)
        st.link_button("Strava-API-Seite öffnen", "https://www.strava.com/settings/api",
                       icon=":material/open_in_new:")
        st.text_input("Strava Client ID", value=str(s.get("client_id", "")), key="cfg_strava_id")
        st.text_input("Strava Client Secret", value=str(s.get("client_secret", "")),
                      type="password", key="cfg_strava_secret")

    with st.expander("2) Whoop — Erholung & Max-HF", icon=":material/favorite:",
                     expanded=not whoop_ok):
        st.markdown(WHOOP_HELP.format(redirect=f"http://localhost:{port}/whoop/callback"))
        st.link_button("Whoop-Developer öffnen", "https://developer.whoop.com",
                       icon=":material/open_in_new:")
        st.text_input("Whoop Client ID", value=str(w.get("client_id", "")), key="cfg_whoop_id")
        st.text_input("Whoop Client Secret", value=str(w.get("client_secret", "")),
                      type="password", key="cfg_whoop_secret")

    with st.expander("3) OpenRouteService + Heimat — für die Karten-Route",
                     icon=":material/map:", expanded=not ors_ok):
        st.markdown(ORS_HELP)
        st.link_button("OpenRouteService öffnen", "https://openrouteservice.org/dev/#/signup",
                       icon=":material/open_in_new:")
        st.text_input("ORS API-Key", value=str(o.get("api_key", "")),
                      type="password", key="cfg_ors_key")
        cur_profile = str(o.get("profile", "cycling-regular"))
        st.selectbox("Fahrprofil", ORS_PROFILES,
                     index=ORS_PROFILES.index(cur_profile) if cur_profile in ORS_PROFILES else 0,
                     key="cfg_ors_profile")
        hc = st.columns(2)
        hc[0].number_input("Heimat Breite (lat)", value=float(a.get("home_lat", 0) or 0),
                           format="%.6f", key="cfg_home_lat")
        hc[1].number_input("Heimat Länge (lon)", value=float(a.get("home_lon", 0) or 0),
                           format="%.6f", key="cfg_home_lon")
        st.number_input("Wochen-Stundenziel (0 = automatisch)",
                        value=int(a.get("weekly_hours_target", 0) or 0), min_value=0,
                        key="cfg_weekly")
        st.number_input(
            "LTHR – Laktatschwellen-HF (0 = aus, dann %HRR aus Whoop-HFmax)",
            value=int(a.get("lthr", 0) or 0), min_value=0, max_value=230, key="cfg_lthr",
            help="Feldtest: 30 min solo all-out fahren, Ø-HF der letzten 20 min eintragen. "
                 "Verankert die HF-Zonen individuell an deiner Schwelle statt an der "
                 "unsicheren geschätzten Maximal-HF.",
        )

    with st.expander("4) KI-Coach + Morgen-Report (optional)", icon=":material/psychology:",
                     expanded=False):
        st.markdown(
            "**KI-Coach:** Klartext-Beratung aus deinen Daten. Braucht einen "
            "Anthropic-API-Key von [console.anthropic.com](https://console.anthropic.com).\n\n"
            "**Morgen-Report:** Push aufs Handy via **ntfy** (kostenlos). Wähle ein "
            "geheimes Thema und abonniere es in der ntfy-App auf dem Handy."
        )
        cch = raw.get("coach", {})
        rep = raw.get("report", {})
        st.text_input("Anthropic API-Key", value=str(cch.get("api_key", "")),
                      type="password", key="cfg_coach_key")
        st.text_input("Coach-Modell", value=str(cch.get("model", "claude-opus-4-8")),
                      key="cfg_coach_model")
        st.text_input("ntfy-Thema (für Handy-Push)", value=str(rep.get("ntfy_topic", "")),
                      key="cfg_ntfy_topic", help="z. B. max-bike-7f3a — in der ntfy-App abonnieren")

    if st.button("Speichern", type="primary", icon=":material/save:", width="stretch"):
        config.save_config({
            "strava": {
                "client_id": st.session_state.cfg_strava_id.strip(),
                "client_secret": st.session_state.cfg_strava_secret.strip(),
            },
            "whoop": {
                "client_id": st.session_state.cfg_whoop_id.strip(),
                "client_secret": st.session_state.cfg_whoop_secret.strip(),
            },
            "server": {"port": port},
            "ors": {
                "api_key": st.session_state.cfg_ors_key.strip(),
                "profile": st.session_state.cfg_ors_profile,
            },
            "athlete": {
                "home_lat": float(st.session_state.cfg_home_lat),
                "home_lon": float(st.session_state.cfg_home_lon),
                "weekly_hours_target": int(st.session_state.cfg_weekly),
                "lthr": int(st.session_state.cfg_lthr),
            },
            "coach": {
                "api_key": st.session_state.get("cfg_coach_key", "").strip(),
                "model": st.session_state.get("cfg_coach_model", "claude-opus-4-8").strip()
                or "claude-opus-4-8",
            },
            "report": {
                "ntfy_topic": st.session_state.get("cfg_ntfy_topic", "").strip(),
            },
        })
        st.success("In config.toml gespeichert. Jetzt unten verbinden.", icon=":material/check_circle:")

    st.divider()
    st.markdown("**Verbinden** (öffnet den Browser-Login auf diesem PC):")
    bc = st.columns(2)
    with bc[0]:
        if st.button("Mit Strava verbinden", icon=":material/link:", width="stretch"):
            _do_connect("strava")
    with bc[1]:
        if st.button("Mit Whoop verbinden", icon=":material/link:", width="stretch"):
            _do_connect("whoop")

    st.divider()
    with st.expander("Daten & Backup", icon=":material/backup:", expanded=False):
        st.caption(
            "Deine Daten liegen in `data/bikedash.db`. Hier kannst du sie sichern "
            "oder herunterladen. Bei jedem automatischen Sync wird zusätzlich "
            "einmal täglich eine Kopie nach `data/backups/` angelegt."
        )
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Backup jetzt erstellen", icon=":material/backup:", width="stretch"):
                try:
                    path = backup.create_backup()
                    backup.prune_backups(keep=14)
                    st.success(f"Backup erstellt: {path.name}", icon=":material/check_circle:")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Backup fehlgeschlagen: {exc}", icon=":material/error:")
        with b2:
            data = backup.db_bytes()
            st.download_button(
                "Datenbank herunterladen", data=data,
                file_name=f"bikedash-{dt.datetime.now():%Y%m%d-%H%M%S}.db",
                mime="application/x-sqlite3", icon=":material/download:",
                width="stretch", disabled=not data,
            )
        existing = backup.list_backups()
        if existing:
            st.caption(f"Vorhandene Backups ({len(existing)}), neueste zuerst:")
            for p in existing[:5]:
                st.markdown(f"- `{p.name}`")


# ---------------------------------------------------------------------------
# Zugangsschutz (nur aktiv, wenn APP_PASSWORD gesetzt ist → beim Hosting)
# ---------------------------------------------------------------------------
webauth.require_login()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f'<div class="sidebrand">{BRAND_SVG}<span class="word">RIDE</span></div>',
               unsafe_allow_html=True)
    st.markdown('<div class="sidebrand-sub">Fahrrad-Dashboard</div>', unsafe_allow_html=True)

last_sync = store.get_state("last_sync")
st.sidebar.caption(f"Letzter Sync: {last_sync or 'noch nie'}")

if st.sidebar.button("Jetzt synchronisieren", icon=":material/sync:", width="stretch"):
    try:
        cfg = config.load_config()
        msgs = []
        if strava.is_connected():
            msgs.append(f"Strava {strava.sync(cfg)}")
        if whoop.is_connected():
            res = whoop.sync(cfg)
            msgs.append(f"Whoop {res['recovery']}")
        store.set_state("last_sync", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        st.cache_data.clear()
        st.sidebar.success(" · ".join(msgs) if msgs else "Nichts verbunden.",
                           icon=":material/check_circle:")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"Sync-Fehler: {exc}", icon=":material/error:")

rides = load_rides()
recovery = load_recovery()
cycles = load_cycles()

if rides.empty:
    brand_bar()
    st.info(
        "Noch keine Fahrten vorhanden. Richte unten deine Verbindungen ein, "
        "verbinde Strava + Whoop und klicke dann links **Synchronisieren**.",
        icon=":material/directions_bike:",
    )
    render_setup()
    st.stop()

min_d, max_d = rides["date"].min(), rides["date"].max()
preset = st.sidebar.radio("Zeitraum", ["30 Tage", "90 Tage", "1 Jahr", "Alles"], index=3)
days_map = {"30 Tage": 30, "90 Tage": 90, "1 Jahr": 365}
start_d = max(min_d, max_d - dt.timedelta(days=days_map[preset])) if preset in days_map else min_d

mask = (rides["date"] >= start_d) & (rides["date"] <= max_d)
r = rides.loc[mask].copy()
rec = recovery[recovery["date"].dt.date >= start_d] if not recovery.empty else recovery
cyc = cycles[cycles["date"].dt.date >= start_d] if not cycles.empty else cycles


# ---------------------------------------------------------------------------
# Kopf-KPIs
# ---------------------------------------------------------------------------
brand_bar()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(":material/directions_bike: Fahrten", f"{len(r)}")
c2.metric(":material/route: Distanz", de_num(r["distance_km"].sum(), "km"))
c3.metric(":material/landscape: Höhenmeter", de_num(r["elev_m"].sum(), "m"))
c4.metric(":material/schedule: Stunden", de_num(r["moving_h"].sum(), "h", 1))
if not rec.empty and rec["recovery_score"].notna().any():
    c5.metric(":material/self_improvement: Ø Recovery", f"{rec['recovery_score'].mean():.0f} %")
else:
    c5.metric(":material/speed: Ø Tempo", f"{r['avg_speed_kmh'].mean():.1f} km/h")

(tab_today, tab1, tab2, tab3, tab_wind, tab_orden, tab_maint, tab_coach,
 tab_setup) = st.tabs(
    [":material/bolt: Heute", ":material/trending_up: Leistung & Fortschritt",
     ":material/fitness_center: Trainingsbelastung", ":material/bedtime: Erholung",
     ":material/air: Wind-Labor (Beta)", ":material/military_tech: Orden",
     ":material/build: Wartung", ":material/psychology: Coach",
     ":material/tune: Einrichtung"]
)

# Kumulierte Gesamtdistanz über die GANZE Historie (nicht der Zeitraumfilter) –
# Grundlage für Orden-Meilensteine und den Verschleiß-Tracker.
total_km_all = float(rides["distance_km"].sum())


# ===========================================================================
# Tab: Heute (Empfehlung + Route)
# ===========================================================================
with tab_today:
    rc = recommend.build()
    accent = BAND_COLORS[rc.readiness_band]

    st.markdown(
        f"""
        <div class="reco-card" style="--accent:{accent}">
          <span class="badge" style="background:{accent}">
            {BAND_TEXT[rc.readiness_band]}
            {f'· {rc.recovery_score:.0f}%' if rc.recovery_score is not None else ''}
          </span>
          <div class="reco-title">{rc.title}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    dauer = "Pause" if rc.kind == "REST" else f"{rc.duration_min[0]}–{rc.duration_min[1]} Min"
    hf_label = f"HF-Zone {rc.zone_number}" if rc.hr_low else "HF-Zone"
    hf_value = f"{rc.hr_low}–{rc.hr_high} bpm" if rc.hr_low else "–"
    tritt = rc.cadence + ("" if rc.cadence == "–" else " U/min")
    dist = (f"{rc.distance_km[0]:.0f}–{rc.distance_km[1]:.0f} km"
            if rc.distance_km[1] > 0 else "–")
    reco_cards([
        ("Dauer", dauer, None, None),
        (hf_label, hf_value, rc.zone_label, accent if rc.hr_low else None),
        ("Trittfrequenz", tritt, "U/min", None),
        ("Anstrengung", rc.rpe, "RPE 1–10", None),
        ("Ziel-Distanz", dist, None, None),
    ])

    pcol, _ = st.columns([2, 1])
    with pcol:
        prog = min(rc.week_hours / rc.target_hours, 1.0) if rc.target_hours else 0.0
        st.caption(
            f"Wochenfortschritt: {rc.week_hours:.1f} h von ~{rc.target_hours:.1f} h "
            f"· {rc.week_rides} Fahrten · {rc.week_km:.0f} km"
        )
        st.progress(prog)

    with st.expander("Warum diese Empfehlung?", icon=":material/lightbulb:", expanded=True):
        for line in rc.rationale:
            st.markdown(f"- {line}")

    # --- Wetter am Start ---
    wx = load_weather()
    if wx is not None:
        st.subheader(f":material/{_wx_icon(wx.code)}: Wetter am Start · {wx.desc}", anchor=False)
        w1, w2, w3, w4 = st.columns(4)
        w1.metric(":material/thermostat: Temperatur", f"{wx.temp_c:.0f} °C", help=f"gefühlt {wx.feels_c:.0f} °C")
        w2.metric(":material/water_drop: Niederschlag", f"{wx.precip_mm:.1f} mm",
                  help=f"{wx.precip_prob}% Wahrscheinlichkeit heute")
        w3.metric(":material/light_mode: UV-Index", f"{wx.uv:.0f}")
        w4.metric(":material/air: Wind", f"{wx.wind_kmh:.0f} km/h",
                  delta=f"aus {wx.wind_dir} · Böen {wx.gust_kmh:.0f}", delta_color="off")
        for tip in weather.advice(wx):
            st.markdown(f"- {tip}")

    # --- Route ---
    st.subheader(":material/map: Passende Route", anchor=False)
    try:
        cfg = config.load_config()
        routing_ready = config.has_routing(cfg)
    except Exception:  # noqa: BLE001
        cfg, routing_ready = None, False

    if rc.kind == "REST":
        st.info("Heute ist ein Ruhetag — keine Route nötig. Erhol dich gut.",
                icon=":material/self_improvement:")
    elif not routing_ready:
        st.info(
            "Routen-Generierung ist noch nicht eingerichtet. Trage in `config.toml` "
            "deinen **OpenRouteService-API-Key** und deine **Heimat-Koordinaten** ein "
            "(Anleitung in der README), dann erscheint hier eine Karte.",
            icon=":material/map:",
        )
    else:
        col_a, col_b = st.columns([1, 1])
        gen = col_a.button("Route generieren", icon=":material/navigation:", width="stretch")
        new_var = col_b.button("Andere Variante", icon=":material/shuffle:", width="stretch")
        # Windklug planen, sobald nennenswerter Wind weht.
        wind_deg = wx.wind_deg if (wx is not None and wx.wind_kmh >= 8) else None
        if gen or new_var:
            seed = None if gen else (st.session_state.get("route_seed", 1) + 7)
            with st.spinner("Berechne windklugen Rundkurs …"):
                try:
                    rt = routing.generate_loop(
                        cfg, rc.target_distance_mid, seed=seed, wind_from_deg=wind_deg
                    )
                    st.session_state["route"] = rt
                    st.session_state["route_seed"] = rt.seed
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Route fehlgeschlagen: {exc}", icon=":material/error:")

        rt = st.session_state.get("route")
        if rt is not None:
            mcol1, mcol2 = st.columns(2)
            mcol1.metric(":material/route: Routenlänge", f"{rt.distance_km:.1f} km")
            mcol2.metric(":material/landscape: Höhenmeter", f"{rt.ascent_m:.0f} m")
            if wind_deg is not None:
                summ = routing.wind_summary(rt, wx.wind_deg, wx.wind_kmh)
                (st.success if summ["ok"] else st.info)(
                    summ["hint"], icon=":material/air:" if summ["ok"] else ":material/info:"
                )
            st.plotly_chart(route_map(rt), width="stretch")
            prof = pd.DataFrame({"km": rt.profile_dist_km, "Höhe (m)": rt.profile_ele_m})
            figp = px.area(prof, x="km", y="Höhe (m)", title="Höhenprofil")
            figp.update_traces(line_color=ACCENT, fillcolor="rgba(255,90,54,0.18)")
            figp.update_layout(height=220, margin=dict(t=40, b=0))
            st.plotly_chart(figp, width="stretch")

    # --- HF-Zonen-Referenz ---
    mhr = zones.max_hr_from_data()
    rhr = zones.resting_hr_baseline()
    lthr = zones.lthr_from_config()
    if mhr or lthr:
        head = f"LTHR {lthr} bpm" if lthr else f"Max-HF {mhr} bpm{f' · Ruhe {rhr} bpm' if rhr else ''}"
        with st.expander(f"Deine HF-Zonen ({head} · {zones.source_note()})",
                         icon=":material/favorite:"):
            if lthr:
                lt1, lt2 = zones.lt1_lt2(lthr)
                st.caption(
                    f"Schwellenzonen (Friel) verankert an deiner **LTHR {lthr} bpm** aus dem "
                    f"Feldtest — individuell treffsicherer als %HRR. Grauzone LT1–LT2 ≈ {lt1}–{lt2} bpm."
                )
            else:
                st.caption(
                    "Berechnet wie in der Whoop-App über die **Herzfrequenzreserve** "
                    "(Karvonen): Ruhepuls + Intensität × (Max − Ruhe) — nicht simples %max."
                    if rhr else
                    "Ohne Ruhepuls über %-der-Max-HF geschätzt (verbinde Whoop für "
                    "die genauere Karvonen-Berechnung). Noch genauer: LTHR-Feldtest in der Einrichtung."
                )
            zdf = pd.DataFrame([
                {"Zone": z.label, "von (bpm)": z.low_bpm, "bis (bpm)": z.high_bpm}
                for z in zones.zones(mhr, rhr, lthr)
            ])
            st.dataframe(zdf, width="stretch", hide_index=True)


# ===========================================================================
# Tab 1: Leistung & Fortschritt
# ===========================================================================
with tab1:
    st.subheader(":material/trending_up: Entwicklung über die Zeit", anchor=False)
    weekly = (
        r.set_index("start").resample("W").agg(
            distance_km=("distance_km", "sum"), elev_m=("elev_m", "sum"),
            avg_speed_kmh=("avg_speed_kmh", "mean"), avg_watts=("average_watts", "mean"),
            rides=("id", "count")).reset_index()
    )

    colA, colB = st.columns(2)
    with colA:
        fig = px.bar(weekly, x="start", y="distance_km", title="Distanz pro Woche (km)")
        fig.update_traces(marker_color=ACCENT)
        fig.update_layout(xaxis_title="", yaxis_title="km")
        st.plotly_chart(fig, width="stretch")
    with colB:
        fig = px.line(weekly, x="start", y="avg_speed_kmh", markers=True,
                      title="Ø Geschwindigkeit pro Woche (km/h)")
        fig.update_layout(xaxis_title="", yaxis_title="km/h")
        st.plotly_chart(fig, width="stretch")

    has_power = r["average_watts"].notna().any()
    colC, colD = st.columns(2)
    with colC:
        if has_power:
            fig = px.line(weekly.dropna(subset=["avg_watts"]), x="start", y="avg_watts",
                          markers=True, title="Ø Leistung pro Woche (Watt)")
            fig.update_layout(xaxis_title="", yaxis_title="Watt")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Keine Wattdaten in deinen Fahrten (kein Leistungsmesser).", icon=":material/bolt:")
    with colD:
        hr = r.dropna(subset=["average_heartrate"])
        if not hr.empty:
            fig = px.scatter(hr, x="average_heartrate", y="avg_speed_kmh",
                             size="distance_km", color="date",
                             title="Effizienz: Tempo vs. Ø Herzfrequenz",
                             labels={"average_heartrate": "Ø HF (bpm)", "avg_speed_kmh": "km/h"})
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Keine Herzfrequenzdaten vorhanden.", icon=":material/favorite:")

    st.subheader(":material/route: Längste Fahrten", anchor=False)
    show = r.sort_values("distance_km", ascending=False).head(10)[
        ["date", "name", "distance_km", "elev_m", "moving_h", "avg_speed_kmh", "average_watts"]
    ].rename(columns={"date": "Datum", "name": "Name", "distance_km": "km", "elev_m": "Hm",
                      "moving_h": "Std", "avg_speed_kmh": "km/h", "average_watts": "Watt"})
    st.dataframe(show, width="stretch", hide_index=True)


# ===========================================================================
# Tab 2: Trainingsbelastung
# ===========================================================================
with tab2:
    st.subheader(":material/fitness_center: Wie viel & wie hart trainierst du?", anchor=False)
    daily = r.set_index("start")["load"].resample("D").sum().fillna(0)
    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_idx, fill_value=0)
    load_df = pd.DataFrame({"date": daily.index, "load": daily.values})
    load_df["akut_7d"] = load_df["load"].rolling(7, min_periods=1).mean()
    load_df["chronisch_28d"] = load_df["load"].rolling(28, min_periods=1).mean()
    load_df["ratio"] = (load_df["akut_7d"] / load_df["chronisch_28d"]).replace([float("inf")], None)

    weekly_load = (
        r.set_index("start").resample("W").agg(
            load=("load", "sum"), rides=("id", "count"), hours=("moving_h", "sum")).reset_index()
    )

    colA, colB = st.columns(2)
    with colA:
        fig = px.bar(weekly_load, x="start", y="load", title="Trainingslast pro Woche")
        fig.update_traces(marker_color=ACCENT)
        fig.update_layout(xaxis_title="", yaxis_title="Last (Relative Effort)")
        st.plotly_chart(fig, width="stretch")
    with colB:
        fig = px.bar(weekly_load, x="start", y="hours", title="Trainingsstunden pro Woche")
        fig.update_layout(xaxis_title="", yaxis_title="Stunden")
        st.plotly_chart(fig, width="stretch")

    st.subheader(":material/insights: Fitness vs. Ermüdung (Belastungsverlauf)", anchor=False)
    st.caption(
        "Die akute Last (7 Tage) zeigt die kurzfristige Ermüdung, die chronische "
        "(28 Tage) deine Grundfitness. Liegt das Verhältnis dauerhaft deutlich über "
        "~1,3, steigerst du sehr schnell (Übertrainings-/Verletzungsrisiko)."
    )
    fig = px.line(load_df, x="date", y=["akut_7d", "chronisch_28d"],
                  title="Akute (7 Tage) vs. chronische (28 Tage) Last")
    fig.update_layout(xaxis_title="", yaxis_title="Ø Last/Tag", legend_title="")
    st.plotly_chart(fig, width="stretch")

    latest_ratio = load_df["ratio"].dropna()
    if not latest_ratio.empty:
        val = latest_ratio.iloc[-1]
        if val > 1.3:
            st.warning(f"Aktuelles Verhältnis: {val:.2f} — du steigerst gerade stark. Achte auf Erholung.",
                      icon=":material/warning:")
        elif val < 0.8:
            st.info(f"Aktuelles Verhältnis: {val:.2f} — eher Ruhe-/Tapering-Phase.",
                   icon=":material/self_improvement:")
        else:
            st.success(f"Aktuelles Verhältnis: {val:.2f} — gesunder Belastungsaufbau.",
                      icon=":material/check_circle:")

    # --- Form-Kurve (Fitness / Ermüdung / Form) ---
    st.subheader(":material/balance: Form-Kurve (Fitness · Ermüdung · Form)", anchor=False)
    st.caption(
        "Banister-Modell: **Fitness (CTL)** = Last über ~42 Tage, **Ermüdung (ATL)** "
        "= über ~7 Tage, **Form (TSB)** = Fitness − Ermüdung. Positiv = frisch/spritzig, "
        "stark negativ = überlastet. Berechnet über deine gesamte Historie."
    )
    fdf = form.compute(rides)  # volle Historie für korrekten Aufbau
    if len(fdf) >= 7:
        cur = fdf.iloc[-1]
        status, hint = form.interpret(cur["tsb"])
        fc1, fc2, fc3, fc4 = st.columns(4)
        fc1.metric(":material/trending_up: Fitness (CTL)", f"{cur['ctl']:.0f}")
        fc2.metric(":material/trending_down: Ermüdung (ATL)", f"{cur['atl']:.0f}")
        fc3.metric(":material/balance: Form (TSB)", f"{cur['tsb']:+.0f}")
        fc4.metric(":material/insights: Status", status)

        view = fdf[fdf["date"].dt.date >= start_d] if len(fdf) > 60 else fdf
        figf = go.Figure()
        figf.add_trace(go.Scatter(x=view["date"], y=view["ctl"], name="Fitness (CTL)",
                                  line=dict(color=C_BELOW, width=3),
                                  fill="tozeroy", fillcolor="rgba(58,155,220,0.12)"))
        figf.add_trace(go.Scatter(x=view["date"], y=view["atl"], name="Ermüdung (ATL)",
                                  line=dict(color="#ef8a2b", width=2)))
        figf.update_layout(height=300, margin=dict(t=10, b=0), legend_title="",
                           xaxis_title="", yaxis_title="Last")
        st.plotly_chart(figf, width="stretch")

        figt = px.area(view, x="date", y="tsb", title="Form (TSB)")
        figt.update_traces(line_color=C_IN, fillcolor="rgba(46,204,113,0.15)")
        figt.add_hline(y=0, line_dash="dot", line_color=MUTED)
        figt.add_hline(y=-30, line_dash="dot", line_color=C_ABOVE)
        figt.update_layout(height=220, margin=dict(t=40, b=0), xaxis_title="", yaxis_title="TSB")
        st.plotly_chart(figt, width="stretch")
        st.info(f"**{status}:** {hint}", icon=":material/insights:")
    else:
        st.info("Noch zu wenig Historie für eine aussagekräftige Form-Kurve.", icon=":material/insights:")

    if not cyc.empty and cyc["day_strain"].notna().any():
        st.subheader(":material/monitor_heart: Whoop-Tagesbelastung (Strain)", anchor=False)
        fig = px.line(cyc, x="date", y="day_strain", title="Whoop Day Strain (0–21)")
        fig.update_layout(xaxis_title="", yaxis_title="Strain")
        st.plotly_chart(fig, width="stretch")


# ===========================================================================
# Tab 3: Erholung
# ===========================================================================
with tab3:
    if rec.empty:
        st.info(
            "Keine Whoop-Erholungsdaten. Verbinde Whoop mit `python connect.py whoop` "
            "und synchronisiere erneut.",
            icon=":material/bedtime:",
        )
    else:
        st.subheader(":material/bedtime: Erholung & Gesundheit (Whoop)", anchor=False)
        colA, colB = st.columns(2)
        with colA:
            fig = px.line(rec, x="date", y="recovery_score", markers=True,
                          title="Recovery-Score (%)")
            fig.update_layout(xaxis_title="", yaxis_title="%")
            fig.add_hline(y=66, line_dash="dot", line_color=C_IN)
            fig.add_hline(y=33, line_dash="dot", line_color=C_ABOVE)
            st.plotly_chart(fig, width="stretch")
        with colB:
            _trend_chart(
                rec, "resting_heart_rate", "Ruhepuls (bpm)", "bpm",
                good_dir="down", stable_thresh=0.25,
                rising_meaning="ein steigender Ruhepuls kann auf Ermüdung, Stress "
                "oder einen beginnenden Infekt hindeuten.",
                falling_meaning="ein fallender Ruhepuls spricht für gute Erholung "
                "und steigende Fitness.",
            )

        colC, colD = st.columns(2)
        with colC:
            _trend_chart(
                rec, "hrv_rmssd_milli", "HRV (RMSSD, ms)", "ms",
                good_dir="up", stable_thresh=0.8,
                rising_meaning="eine steigende HRV spricht für gute Erholung und "
                "wachsende Belastbarkeit.",
                falling_meaning="eine fallende HRV kann ein Warnsignal für "
                "Überlastung oder unzureichende Erholung sein.",
            )
        with colD:
            if not r.empty:
                day_load = r.set_index("start")["load"].resample("D").sum()
                rec_idx = rec.set_index(rec["date"].dt.normalize())["recovery_score"]
                merged = pd.DataFrame({"load": day_load}).join(
                    rec_idx.shift(-1).rename("recovery_next")).dropna()
                if not merged.empty and len(merged) > 3:
                    fig = px.scatter(merged, x="load", y="recovery_next",
                                     title="Belastung heute → Recovery morgen",
                                     labels={"load": "Trainingslast", "recovery_next": "Recovery Folgetag %"})
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.info("Noch zu wenige überlappende Tage für diese Auswertung.",
                           icon=":material/bedtime:")


# ===========================================================================
# Tab: Wind-Labor (Beta)
# ===========================================================================
with tab_wind:
    st.subheader(":material/air: Wind-Labor (Beta)", anchor=False)
    st.caption(
        "Wie wirkt sich Gegen-/Rückenwind auf dein Tempo aus? Ausgewertet werden "
        "flache Abschnitte deiner Fahrten gegen historische Winddaten. Heuristik — "
        "ohne Wattmessung sind Effort-Schwankungen ein Störfaktor; je mehr Fahrten "
        "analysiert sind, desto genauer wird es."
    )

    processed = len(store.wind_processed_ids())
    cwa, cwb = st.columns([1, 1])
    cwa.metric(":material/directions_bike: Fahrten mit GPS-Auswertung", f"{processed}",
               help="Indoor-/Rollen-Einheiten ohne GPS werden übersprungen.")
    if cwb.button("Mehr Fahrten analysieren", icon=":material/add:", width="stretch"):
        try:
            cfg = config.load_config()
        except Exception:  # noqa: BLE001
            cfg = config.load_config_raw()
            cfg.setdefault("server", {}).setdefault("port", 8721)
        prog = st.progress(0.0, text="Starte …")

        def _cb(i: int, t: int, name: str) -> None:
            prog.progress((i + 1) / max(t, 1), text=f"{i + 1}/{t}: {name}")

        try:
            res = windlab.run_analysis(cfg, limit=10, progress_cb=_cb)
            st.cache_data.clear()
            st.success(f"{res['processed']} Fahrten verarbeitet ({res['segments']} Abschnitte).",
                      icon=":material/check_circle:")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Analyse-Fehler: {exc}", icon=":material/error:")

    fit = load_wind_fit()
    if fit is None:
        st.info(
            "Noch zu wenige analysierte Daten. Klicke oben **Mehr Fahrten "
            "analysieren** (verarbeitet je 10 Fahrten).",
            icon=":material/air:",
        )
    else:
        loss10 = -fit.slope * 10
        k1, k2, k3 = st.columns(3)
        k1.metric(":material/air: Gegenwind-Malus", f"{loss10:.1f} km/h",
                  help="Tempoverlust je 10 km/h Gegenwind auf flachem Terrain")
        k2.metric(":material/speed: Tempo bei Windstille", f"{fit.intercept:.1f} km/h", help="flaches Terrain")
        k3.metric(":material/dataset: Datenpunkte", f"{fit.n}")
        st.markdown(
            f"**Interpretation:** Auf flachem Terrain kostet dich jede **10 km/h "
            f"Gegenwind rund {loss10:.1f} km/h** Tempo — und etwa ebenso viel "
            "gewinnst du bei Rückenwind. Das fließt in die *windkluge Routenplanung* ein."
        )

        df = fit.df
        if len(df) > 1500:
            df = df.sample(1500, random_state=1)
        fig = px.scatter(
            df, x="headwind_kmh", y="speed_kmh", opacity=0.4,
            title="Tempo vs. Gegenwind (flache Abschnitte)",
            labels={"headwind_kmh": "Windkomponente (km/h: + Gegen / − Rücken)",
                    "speed_kmh": "Tempo (km/h)"},
        )
        fig.update_traces(marker=dict(color=ACCENT, size=5))
        xs = np.array([df["headwind_kmh"].min(), df["headwind_kmh"].max()])
        fig.add_trace(go.Scatter(x=xs, y=fit.slope * xs + fit.intercept, mode="lines",
                                 line=dict(color="#ffffff", width=3)))
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, width="stretch")

        d2 = fit.df.copy()
        d2["Windlage"] = np.where(d2["headwind_kmh"] <= -5, "Rückenwind",
                                  np.where(d2["headwind_kmh"] >= 5, "Gegenwind", "Neutral/Seiten"))
        agg = (d2.groupby("Windlage")["speed_kmh"].mean()
               .reindex(["Gegenwind", "Neutral/Seiten", "Rückenwind"]).reset_index())
        figb = px.bar(agg, x="Windlage", y="speed_kmh", title="Ø Tempo nach Windlage (flach)")
        figb.update_traces(marker_color=C_BELOW)
        figb.update_layout(yaxis_title="km/h", xaxis_title="")
        st.plotly_chart(figb, width="stretch")


# ===========================================================================
# Tab: Orden (Distanz-Meilensteine)
# ===========================================================================
with tab_orden:
    st.subheader(":material/military_tech: Distanz-Meilensteine & Orden", anchor=False)
    st.caption(
        "Jede berühmte Distanz wird zum Orden, sobald deine aufsummierte "
        "Fahrleistung sie überholt – dazwischen liegen erreichbare Nahziele."
    )

    all_themes = list(milestones.THEMES.keys())
    picked = st.multiselect(
        "Themen", options=all_themes, default=all_themes,
        format_func=lambda k: milestones.THEMES[k],
    )
    themes = set(picked) if picked else None
    mv = milestones.compute(total_km_all, themes=themes)

    m1, m2, m3 = st.columns(3)
    m1.metric(":material/route: Gesamtdistanz", de_num(mv.total_km, "km", 0))
    m2.metric(":material/military_tech: Orden", f"{len(mv.earned)} / {mv.badges_total}")
    m3.metric(":material/emoji_events: Zuletzt",
              f"{mv.latest.icon} {mv.latest.name}" if mv.latest else "–")

    st.markdown("#### Nächste Ziele")
    if mv.next_targets:
        for t in mv.next_targets:
            head = f"{t.icon} **{t.label}**"
            if t.kind == "orden" and t.blurb:
                head += f" · _{t.blurb}_"
            rem = f"noch **{de_num(t.remaining_km, 'km', 0)}**"
            st.markdown(f"{head}  \n{rem} · Ziel bei {de_num(t.km, 'km', 0)}")
            st.progress(min(max(t.progress, 0.0), 1.0))
    else:
        st.success("Alle Orden gesammelt – Wahnsinn! 🏆")

    st.markdown("#### Deine Orden-Sammlung")
    view_cat = sorted(
        [b for b in mv.catalog if themes is None or b.theme in themes],
        key=lambda b: b.km,
    )
    ocols = st.columns(4)
    for i, b in enumerate(view_cat):
        earned = b.km <= mv.total_km
        opacity = "1" if earned else "0.4"
        border = C_IN if earned else BORDER
        lock = "" if earned else "🔒 "
        with ocols[i % 4]:
            st.markdown(
                f'<div style="opacity:{opacity};background:linear-gradient(158deg,{PANEL_A},{PANEL_B});'
                f'border:1px solid {border};border-radius:14px;padding:12px 14px;margin-bottom:10px;'
                f'min-height:120px">'
                f'<div style="font-size:30px;line-height:1">{b.icon}</div>'
                f'<div style="font-weight:600;margin-top:6px;font-size:14px">{lock}{b.name}</div>'
                f'<div style="color:{MUTED};font-size:12px;margin-top:1px">{de_num(b.km, "km", 0)}</div>'
                f'<div style="color:{FAINT};font-size:11px;margin-top:4px;line-height:1.35">{b.blurb}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ===========================================================================
# Tab: Wartung (Verschleiß-Tracker)
# ===========================================================================
with tab_maint:
    st.subheader(":material/build: Verschleiß & Wartung", anchor=False)
    maint_state = maintenance.load_state()
    stats = maintenance.statuses(maint_state, total_km_all)
    n_due = sum(1 for s in stats if s.status == maintenance.STATUS_DUE)
    n_soon = sum(1 for s in stats if s.status == maintenance.STATUS_SOON)

    k1, k2, k3 = st.columns(3)
    k1.metric(":material/route: Kilometerstand", de_num(total_km_all, "km", 0),
              help="Kumulierte Strava-Gesamtdistanz über die ganze Historie.")
    k2.metric(":material/warning: Fällig", f"{n_due}")
    k3.metric(":material/schedule: Bald fällig", f"{n_soon}")

    st.caption(
        "Verschleiß zählt ab dem Kilometerstand beim letzten Wechsel. Frisch "
        "eingerichtet? Einmal **„Alle ab jetzt frisch“** klicken, dann stimmt die Basis."
    )
    if st.button(":material/restart_alt: Alle ab jetzt frisch tracken"):
        maintenance.save_state(maintenance.reset_all(maint_state, total_km_all))
        st.rerun()

    STATUS_STYLE = {
        maintenance.STATUS_OK:   (C_IN, "in Ordnung"),
        maintenance.STATUS_SOON: (C_AMBER, "bald fällig"),
        maintenance.STATUS_DUE:  (C_ABOVE, "fällig"),
    }
    for s in stats:
        color, txt = STATUS_STYLE[s.status]
        c1, c2 = st.columns([4, 1])
        with c1:
            rem = (f"noch {de_num(s.remaining_km, 'km', 0)}" if s.remaining_km >= 0
                   else f"überfällig um {de_num(-s.remaining_km, 'km', 0)}")
            st.markdown(
                f"{s.icon} **{s.name}** · <span style='color:{color}'>{txt}</span>  \n"
                f"<span style='color:{MUTED};font-size:13px'>"
                f"{de_num(s.wear_km, 'km', 0)} / {de_num(s.interval_km, 'km', 0)} · {rem}"
                f"</span>",
                unsafe_allow_html=True,
            )
            st.progress(min(max(s.pct, 0.0), 1.0))
        with c2:
            if st.button("Gewechselt", key=f"maint_reset_{s.id}",
                         help="Bauteil als frisch gewechselt markieren"):
                maintenance.save_state(
                    maintenance.reset_component(maint_state, s.id, total_km_all))
                st.rerun()

    with st.expander(":material/tune: Bauteile & Intervalle bearbeiten"):
        st.caption("Zeilen hinzufügen/entfernen oder Intervalle ändern, dann speichern. "
                   "Neue Bauteile starten ab dem aktuellen Kilometerstand.")
        edit_df = pd.DataFrame([
            {"Emoji": c["icon"], "Bauteil": c["name"], "Intervall (km)": int(c["interval_km"])}
            for c in maint_state
        ])
        edited = st.data_editor(
            edit_df, num_rows="dynamic", width="stretch", key="maint_editor",
            column_config={
                "Intervall (km)": st.column_config.NumberColumn(min_value=1, step=50),
            },
        )
        if st.button(":material/save: Speichern", type="primary", key="maint_save"):
            by_name = {c["name"].strip().lower(): c for c in maint_state}
            new_state: list[dict] = []
            for _, row in edited.iterrows():
                name = str(row.get("Bauteil") or "").strip()
                if not name:
                    continue
                prev = by_name.get(name.lower())
                slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower())
                new_state.append({
                    "id": prev["id"] if prev else slug,
                    "name": name,
                    "icon": str(row.get("Emoji") or "🔧"),
                    "interval_km": float(row.get("Intervall (km)") or 1000),
                    "installed_km": float(prev["installed_km"] if prev else total_km_all),
                })
            if new_state:
                maintenance.save_state(new_state)
                st.success("Gespeichert.")
                st.rerun()


# ===========================================================================
# Tab: KI-Coach
# ===========================================================================
with tab_coach:
    st.subheader(":material/psychology: Dein KI-Coach", anchor=False)
    st.caption(
        "Stell Fragen zu deinem Training — der Coach antwortet auf Basis deiner "
        "echten Daten (Fahrten, Erholung, Form, Zonen). Trainings-, kein "
        "medizinischer Rat."
    )
    try:
        cfg_c = config.load_config_raw()
    except Exception:  # noqa: BLE001
        cfg_c = {}
    coach_ready = bool(str(cfg_c.get("coach", {}).get("api_key", "")).strip()
                       and not str(cfg_c.get("coach", {}).get("api_key", "")).startswith("DEIN")) \
        or bool(os.environ.get("ANTHROPIC_API_KEY"))

    if not coach_ready:
        st.info(
            "Der Coach braucht einen **Anthropic-API-Key**. Trage ihn in der "
            "Einrichtung ein (Abschnitt KI-Coach), dann kannst du hier chatten.",
            icon=":material/key:",
        )
    else:
        cc1, cc2 = st.columns(2)
        if cc1.button("Wochenrückblick erstellen", icon=":material/summarize:", width="stretch"):
            with st.spinner("Coach denkt nach …"):
                try:
                    review = coach.weekly_review(cfg_c)
                    st.session_state.setdefault("coach_chat", []).append(
                        {"role": "assistant", "content": review})
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Coach-Fehler: {exc}", icon=":material/error:")
        if cc2.button("Verlauf löschen", icon=":material/delete_sweep:", width="stretch"):
            st.session_state["coach_chat"] = []

        for turn in st.session_state.get("coach_chat", []):
            with st.chat_message(turn["role"]):
                st.markdown(turn["content"])

        prompt = st.chat_input("Frag deinen Coach … (z. B. 'Bin ich bereit für 100 km?')")
        if prompt:
            history = list(st.session_state.get("coach_chat", []))
            st.session_state.setdefault("coach_chat", []).append(
                {"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Coach denkt nach …"):
                    try:
                        answer = coach.ask(cfg_c, prompt, history)
                    except Exception as exc:  # noqa: BLE001
                        answer = f"Fehler: {exc}"
                    st.markdown(answer)
            st.session_state["coach_chat"].append({"role": "assistant", "content": answer})

    st.divider()
    st.markdown("**Morgen-Report aufs Handy**")
    ntfy = str(cfg_c.get("report", {}).get("ntfy_topic", "")).strip()
    if not ntfy or ntfy.startswith("DEIN"):
        st.caption(
            "Noch kein ntfy-Thema gesetzt. In der Einrichtung eintragen und "
            "die kostenlose ntfy-App auf dem Handy dasselbe Thema abonnieren lassen."
        )
    if st.button("Test-Report jetzt senden", icon=":material/notifications:", width="stretch"):
        try:
            title, msg = report.build_text(cfg_c)
            ok = report.send_push(cfg_c, title, msg)
            (st.success if ok else st.info)(
                "Push gesendet." if ok else "Vorschau erstellt (kein ntfy-Thema gesetzt).",
                icon=":material/notifications:",
            )
            st.text_area("Vorschau", f"{title}\n\n{msg}", height=160)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Report-Fehler: {exc}", icon=":material/error:")


# ===========================================================================
# Tab: Einrichtung
# ===========================================================================
with tab_setup:
    render_setup()
