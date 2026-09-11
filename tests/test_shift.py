"""Gangempfehlung: Entscheidungsmatrix aus Puls + Kadenz."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bikedash import shift

RIDE_HTML = Path(__file__).resolve().parent.parent / "mobile" / "ride.html"

# Z2-Tagesziel wie in einer typischen today.json.
Z2 = dict(hr_low=145, hr_high=158, cad_low=85, cad_high=95)


def test_matrix_ist_vollstaendig():
    """Jede Kombination der vier Ampelzustaende hat eine Zelle."""
    for h in shift.STATUSES:
        for c in shift.STATUSES:
            assert (h, c) in shift.MATRIX, f"Zelle ({h}, {c}) fehlt"


def test_zone2_mit_guter_kadenz_aber_zu_hohem_puls_empfiehlt_leichter():
    """Der Kernfall: 90 U/min ist formal im Band, 185 bpm aber viel zu hoch."""
    a = shift.advise(185, 90, **Z2)
    assert a.action == "leichter"
    assert a.symbol == "⬇"
    assert "185" in a.why


def test_zu_niedriger_puls_bei_guter_kadenz_empfiehlt_schwerer():
    a = shift.advise(120, 90, **Z2)
    assert a.action == "schwerer"
    assert a.symbol == "⬆"


def test_alles_im_ziel_empfiehlt_halten():
    a = shift.advise(150, 90, **Z2)
    assert a.action == "halten"
    assert a.color == shift.C_HOLD


def test_hoher_puls_und_hohe_kadenz_kann_kein_gang_loesen():
    """Wer schon schnell tritt, muss Tempo rausnehmen statt zu schalten."""
    a = shift.advise(185, 105, **Z2)
    assert a.action == "lockerer"


def test_niedriger_puls_und_niedrige_kadenz_erst_schneller_treten():
    a = shift.advise(120, 70, **Z2)
    assert a.action == "schneller treten"


def test_ohne_pulsgurt_zaehlt_wie_bisher_die_kadenz():
    assert shift.advise(None, 70, **Z2).action == "leichter"
    assert shift.advise(None, 90, **Z2).action == "halten"
    assert shift.advise(None, 105, **Z2).action == "schwerer"


def test_ohne_kadenzsensor_gibt_es_trotzdem_eine_empfehlung():
    """Frueher blieb die Kachel ohne CSC-Sensor leer — jetzt reicht der Puls."""
    assert shift.advise(185, None, **Z2).action == "lockerer"
    assert shift.advise(150, None, **Z2).action == "halten"
    assert shift.advise(120, None, **Z2).action == "mehr geben"


def test_ohne_jede_messung_wartet_die_kachel():
    a = shift.advise(None, None, **Z2)
    assert a.action == "–"
    assert "warte" in a.why


def test_ruhetag_ohne_zielzone_faellt_auf_kadenz_zurueck():
    """An Ruhetagen hat die Empfehlung keine HF-Zone (hr_low/high = None)."""
    a = shift.advise(150, 70, hr_low=None, hr_high=None, cad_low=85, cad_high=95)
    assert a.action == "leichter"


def test_toleranz_verhindert_flattern_am_bandrand():
    """Knapp ueber der Grenze gilt noch als „im Ziel"."""
    assert shift.advise(158 + shift.HR_TOLERANCE_BPM, 90, **Z2).action == "halten"
    assert shift.advise(158 + shift.HR_TOLERANCE_BPM + 1, 90, **Z2).action == "leichter"


def test_platzhalter_werden_alle_ersetzt():
    for h in (None, 120, 150, 185):
        for c in (None, 70, 90, 105):
            why = shift.advise(h, c, **Z2).why
            assert "{" not in why, why


def test_payload_ist_json_serialisierbar():
    payload = shift.matrix_payload()
    assert json.loads(json.dumps(payload))["cells"]["above|in"]["action"] == "leichter"
    assert len(payload["cells"]) == len(shift.STATUSES) ** 2


def _matrix_aus_ride_html() -> dict:
    """Die Offline-Kopie der Matrix aus mobile/ride.html herausschneiden."""
    html = RIDE_HTML.read_text(encoding="utf-8")
    m = re.search(
        r"SHIFT_MATRIX_DEFAULT:BEGIN\s*\nconst SHIFT_MATRIX_DEFAULT = (.*?);\s*\n"
        r"// SHIFT_MATRIX_DEFAULT:END",
        html, re.S,
    )
    assert m, "Matrix-Block in ride.html nicht gefunden"
    return json.loads(m.group(1))


def test_ride_html_spiegelt_die_python_matrix():
    """Die PWA-Kopie darf nicht auseinanderlaufen — shift.py ist die Quelle.

    Bei einem Fehlschlag: build_today.py laufen lassen bzw. den Block in
    mobile/ride.html aus ``shift.matrix_payload()`` neu erzeugen.
    """
    assert _matrix_aus_ride_html() == json.loads(json.dumps(shift.matrix_payload()))
