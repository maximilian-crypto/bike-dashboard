"""Stundenraster von Open-Meteo einlesen (ohne Netz, gegen eine Beispielantwort).

Die Beispielantwort hat genau die Form, die Open-Meteo fuer die in
``weather.hourly_forecast`` angefragten Variablen liefert.
"""

from __future__ import annotations

import datetime as dt

import pytest
import requests

from bikedash import weather

CFG = {"athlete": {"home_lat": 52.52, "home_lon": 13.405}}

ANTWORT = {
    "latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin",
    "hourly_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h"},
    "hourly": {
        "time": ["2026-09-14T12:00", "2026-09-14T13:00", "2026-09-14T14:00"],
        "temperature_2m": [17.4, 18.9, 19.6],
        "apparent_temperature": [16.1, 17.8, 18.4],
        "precipitation": [0.0, 0.0, 1.2],
        "precipitation_probability": [3, 12, 68],
        "weather_code": [1, 3, 61],
        "wind_speed_10m": [11.5, 14.2, 22.0],
        "wind_gusts_10m": [23.4, 28.1, 41.0],
        "wind_direction_10m": [230, 245, 260],
        "uv_index": [3.1, 2.8, 1.4],
        "is_day": [1, 1, 1],
    },
}


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


@pytest.fixture
def antwort(monkeypatch):
    def _set(payload, boom=None):
        def fake_get(url, params=None, timeout=None):
            if boom:
                raise boom
            return FakeResp(payload)
        monkeypatch.setattr(weather.requests, "get", fake_get)
    return _set


def test_stunden_werden_vollstaendig_eingelesen(antwort):
    antwort(ANTWORT)
    hours = weather.hourly_forecast(CFG)
    assert len(hours) == 3

    h = hours[2]
    assert h.time == dt.datetime(2026, 9, 14, 14)
    assert h.temp_c == 19.6 and h.feels_c == 18.4
    assert h.precip_mm == 1.2 and h.precip_prob == 68
    assert h.wind_kmh == 22.0 and h.gust_kmh == 41.0
    assert h.wind_dir == "W"
    assert h.desc == "leichter Regen"
    assert h.is_day is True


def test_ohne_heimatkoordinate_kein_abruf():
    assert weather.hourly_forecast({}) == []
    assert weather.hourly_forecast({"athlete": {"home_lat": 0, "home_lon": 0}}) == []


def test_netzfehler_liefert_leere_liste(antwort):
    antwort(None, boom=requests.RequestException("kein Netz"))
    assert weather.hourly_forecast(CFG) == []


def test_luecken_in_der_antwort_kippen_den_abruf_nicht(antwort):
    """Open-Meteo laesst einzelne Variablen weg, wenn sie nicht verfuegbar sind."""
    knapp = {"hourly": {"time": ["2026-09-14T12:00", "2026-09-14T13:00"],
                        "temperature_2m": [17.4, 18.9]}}
    antwort(knapp)
    hours = weather.hourly_forecast(CFG)
    assert len(hours) == 2
    assert hours[0].temp_c == 17.4
    assert hours[0].feels_c == 17.4      # faellt auf die Lufttemperatur zurueck
    assert hours[0].wind_kmh == 0.0
    assert hours[0].is_day is True


def test_leere_antwort_ist_unkritisch(antwort):
    antwort({})
    assert weather.hourly_forecast(CFG) == []
