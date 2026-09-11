"""Tageszeit-Empfehlung: wann heute fahren?"""

from __future__ import annotations

import datetime as dt

from bikedash import daytime, weather

MO = dt.date(2026, 9, 14)   # Montag
SA = dt.date(2026, 9, 12)   # Samstag


def hour(when: dt.datetime, *, temp=18.0, rain=0.0, prob=0, code=0,
         wind=10.0, gust=15.0, deg=270.0, uv=2.0, day=True) -> weather.Hour:
    return weather.Hour(time=when, temp_c=temp, feels_c=temp, precip_mm=rain,
                        precip_prob=prob, code=code, wind_kmh=wind, gust_kmh=gust,
                        wind_deg=deg, uv=uv, is_day=day)


def tagesraster(day: dt.date, **kw) -> list[weather.Hour]:
    """24 gleichfoermige Stunden."""
    return [hour(dt.datetime.combine(day, dt.time(h)), **kw) for h in range(24)]


# --- erlaubte Fenster -------------------------------------------------------

def test_wochentag_fenster_13_bis_20():
    assert daytime.allowed_window(MO) == (13, 20)


def test_wochenende_fenster_8_bis_20():
    assert daytime.allowed_window(SA) == (8, 20)
    assert daytime.allowed_window(dt.date(2026, 9, 13)) == (8, 20)   # Sonntag


def test_empfehlung_liegt_immer_im_erlaubten_fenster():
    for day in (MO, SA):
        lo, hi = daytime.allowed_window(day)
        p = daytime.plan_from_hours(tagesraster(day), day, duration_min=90)
        assert p.best is not None
        assert p.best.start.hour >= lo
        assert p.best.end.hour <= hi


# --- Wetter schlaegt Uhrzeit ------------------------------------------------

def test_regenfenster_wird_gemieden():
    hours = tagesraster(MO)
    for h in hours[13:17]:                      # 13–16 Uhr verregnet
        h.precip_mm, h.precip_prob, h.code = 2.5, 90, 65
    p = daytime.plan_from_hours(hours, MO, duration_min=90)
    assert p.best is not None
    assert p.best.start.hour >= 17
    assert not p.settled


def test_gewitter_wird_hart_gemieden():
    hours = tagesraster(MO)
    for h in hours[17:20]:
        h.code, h.precip_mm, h.precip_prob = 95, 4.0, 95
    p = daytime.plan_from_hours(hours, MO, duration_min=60)
    assert p.best is not None
    assert p.best.end.hour <= 17


# --- schoener Tag: der Wind entscheidet -------------------------------------

def test_bei_durchweg_gutem_wetter_entscheidet_der_wind():
    hours = tagesraster(SA)                      # ueberall gleich schoen
    for h in hours:
        h.wind_kmh, h.gust_kmh = 30.0, 40.0
    for h in hours[15:18]:                       # nur hier ist es windstill
        h.wind_kmh, h.gust_kmh = 6.0, 9.0
    p = daytime.plan_from_hours(hours, SA, duration_min=120)
    assert p.settled is True
    assert p.best is not None
    assert p.best.start.hour == 15
    assert any("Wind" in r for r in p.reasons)


def test_unruhiger_tag_ist_nicht_settled():
    hours = tagesraster(MO)
    hours[15].precip_mm, hours[15].precip_prob = 3.0, 80
    p = daytime.plan_from_hours(hours, MO, duration_min=60)
    assert p.settled is False


# --- Randfaelle -------------------------------------------------------------

def test_ruhetag_bekommt_kein_fenster():
    p = daytime.plan_from_hours(tagesraster(MO), MO, duration_min=0)
    assert p.best is None
    assert "Ruhetag" in p.reasons[0]


def test_lange_einheit_wird_auf_das_fenster_gekuerzt():
    """Mo–Fr sind nur 7 h erlaubt — eine 9-h-Einheit passt da nicht hinein."""
    p = daytime.plan_from_hours(tagesraster(MO), MO, duration_min=9 * 60)
    assert p.duration_h == 7
    assert p.best is not None
    assert p.best.start.hour == 13 and p.best.end.hour == 20
    assert any("gekuerzt" in r for r in p.reasons)


def test_ohne_vorhersage_gibt_es_keine_empfehlung():
    p = daytime.plan_from_hours([], MO, duration_min=90)
    assert p.best is None
    assert p.alternative is None


def test_dunkle_stunden_werden_gemieden():
    hours = tagesraster(SA)
    for h in hours[:10]:                         # frueh noch dunkel
        h.is_day = False
    p = daytime.plan_from_hours(hours, SA, duration_min=60)
    assert p.best is not None
    assert p.best.start.hour >= 10


def test_payload_ist_route_und_koordinatenfrei():
    p = daytime.plan_from_hours(tagesraster(SA), SA, duration_min=90)
    payload = daytime.payload(p)
    flat = repr(payload)
    assert "lat" not in flat and "lon" not in flat
    assert payload["best"]["label"].endswith("Uhr")
    assert payload["window_from"] == 8 and payload["window_to"] == 20


def test_alternative_ueberlappt_das_beste_fenster_nicht():
    p = daytime.plan_from_hours(tagesraster(SA), SA, duration_min=120)
    assert p.best is not None
    if p.alternative is not None:
        a, b = p.alternative, p.best
        assert a.end <= b.start or a.start >= b.end


def test_deutlich_schlechtere_alternative_wird_verschwiegen():
    """Ein Regenloch ist keine „Alternative" — dann lieber gar keine nennen."""
    hours = tagesraster(MO)
    for h in hours[13:17]:
        h.precip_mm, h.precip_prob, h.code = 3.0, 90, 65
    p = daytime.plan_from_hours(hours, MO, duration_min=120)
    assert p.best is not None and p.best.start.hour >= 17
    assert p.alternative is None
