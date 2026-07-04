import datetime as dt

import pandas as pd

from bikedash import form


def _rides(days, load):
    base = dt.datetime(2026, 1, 1, 9)
    return pd.DataFrame({
        "start": [base + dt.timedelta(days=i) for i in range(days)],
        "load": [load] * days,
    })


def test_constant_load_converges():
    df = form.compute(_rides(120, 50.0))
    assert list(df.columns) == ["date", "ctl", "atl", "tsb"]
    last = df.iloc[-1]
    # ATL (7-Tage) ist schnell ~50; CTL (42-Tage) nähert sich nach 120 Tagen
    # erst ~47 an -> TSB leicht negativ. Genau dieses Verhalten prüfen.
    assert abs(last["ctl"] - 50.0) < 4
    assert abs(last["atl"] - 50.0) < 1
    assert abs(last["tsb"]) < 4


def test_taper_raises_form():
    # 60 Tage Last, dann 14 Tage Pause -> TSB deutlich positiv
    base = dt.datetime(2026, 1, 1, 9)
    rows = [{"start": base + dt.timedelta(days=i), "load": 60.0} for i in range(60)]
    rows += [{"start": base + dt.timedelta(days=60 + i), "load": 0.0} for i in range(14)]
    df = form.compute(pd.DataFrame(rows))
    assert df.iloc[-1]["tsb"] > 10


def test_empty():
    df = form.compute(pd.DataFrame(columns=["start", "load"]))
    assert df.empty
