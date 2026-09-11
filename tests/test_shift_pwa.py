"""Fuehrt die Shift-Logik AUS mobile/ride.html in Node aus.

tests/test_shift.py prueft die Python-Seite und dass die Matrix-Kopie in der PWA
identisch ist. Hier laeuft der echte Browser-Code: Ampel-Einstufung, Nachschlagen
in der Matrix, Platzhalter-Ersetzung und die Verweilzeit gegen Flackern.

Ohne Node wird der Test uebersprungen (die Python-Seite bleibt abgedeckt).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RIDE_HTML = Path(__file__).resolve().parent.parent / "mobile" / "ride.html"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node nicht installiert")

# Stubs fuer alles, was der Block aus der PWA-Umgebung erwartet.
HARNESS_HEAD = """
let hrVal=null, cadVal=null, cadLo=85, cadHi=95;
let hrLoBand=145, hrHiBand=158;
const GA={ hr:{ band:()=>[hrLoBand,hrHiBand] } };
const TILES={};
function $(id){ return TILES[id] || (TILES[id]={textContent:'', style:{setProperty(){}}}); }
let NOW=1000000;
Date.now=()=>NOW;
"""

HARNESS_TAIL = """
function snap(){ return {action:$('shift').textContent, why:$('shiftSub').textContent,
                         sym:$('shiftBadge').textContent}; }
const out=[];
function run(hr,cad,advance){ NOW+=advance||0; hrVal=hr; cadVal=cad; updateShift(); out.push(snap()); }
const [,,plan]=process.argv;
for(const step of JSON.parse(plan)) run(step[0], step[1], step[2]);
console.log(JSON.stringify(out));
"""


def _shift_block() -> str:
    html = RIDE_HTML.read_text(encoding="utf-8")
    m = re.search(r"// SHIFT_MATRIX_DEFAULT:BEGIN.*?\nfunction num\(v\)\{[^\n]*\n", html, re.S)
    assert m, "Shift-Block in ride.html nicht gefunden"
    return m.group(0)


def _run(plan: list[list], tmp_path: Path) -> list[dict]:
    script = tmp_path / "shift_harness.mjs"
    script.write_text(HARNESS_HEAD + _shift_block() + HARNESS_TAIL, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(script), json.dumps(plan)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_pwa_zone2_hohe_kadenz_hoher_puls(tmp_path):
    """Der Kernfall des Nutzers, ausgefuehrt im echten PWA-Code."""
    (res,) = _run([[185, 90, 0]], tmp_path)
    assert res["action"] == "leichter"
    assert res["sym"] == "⬇"
    assert "185" in res["why"] and "{" not in res["why"]


def test_pwa_alles_im_ziel(tmp_path):
    (res,) = _run([[150, 90, 0]], tmp_path)
    assert res["action"] == "halten"


def test_pwa_ohne_kadenzsensor_nur_puls(tmp_path):
    a, b = _run([[185, None, 0], [120, None, 0]], tmp_path)
    assert a["action"] == "lockerer"
    assert b["action"] == "mehr geben"


def test_pwa_ohne_pulsgurt_nur_kadenz(tmp_path):
    a, b = _run([[None, 70, 0], [None, 105, 0]], tmp_path)
    assert a["action"] == "leichter"
    assert b["action"] == "schwerer"


def test_pwa_ohne_sensoren_wartet(tmp_path):
    (res,) = _run([[None, None, 0]], tmp_path)
    assert res["action"] == "–"
    assert "warte" in res["why"]


def test_pwa_verweilzeit_verhindert_flackern(tmp_path):
    """Ein kurzer Pulsausreisser darf die Kachel nicht sofort umwerfen."""
    steps = [
        [150, 90, 0],        # eingeschwungen: halten
        [185, 90, 1000],     # 1 s spaeter Ausreisser -> noch halten
        [185, 90, 7000],     # nach der Verweilzeit -> umschalten
    ]
    a, b, c = _run(steps, tmp_path)
    assert a["action"] == "halten"
    assert b["action"] == "halten", "zu frueh umgeschaltet"
    assert c["action"] == "leichter"


def test_pwa_sensorwechsel_schaltet_sofort(tmp_path):
    """Faellt ein Sensor weg, wird nicht auf die Verweilzeit gewartet."""
    a, b = _run([[150, 90, 0], [150, None, 100]], tmp_path)
    assert a["action"] == "halten"
    assert "keine Kadenz" in b["why"]
