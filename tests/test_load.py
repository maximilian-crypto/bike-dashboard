"""Tests für die Banister-TRIMP-Last (bikedash.load)."""

import math

from bikedash import load


def test_trimp_monotone_in_intensity():
    # Gleiche Dauer, höhere Ø-HF → höhere Last.
    low = load.banister_trimp(3600, 130, 190, 50)
    high = load.banister_trimp(3600, 165, 190, 50)
    assert low is not None and high is not None
    assert high > low


def test_trimp_monotone_in_duration():
    short = load.banister_trimp(1800, 150, 190, 50)
    long = load.banister_trimp(3600, 150, 190, 50)
    assert long > short
    # Doppelte Dauer bei gleicher HF → exakt doppelte Last.
    assert math.isclose(long, 2 * short, rel_tol=1e-9)


def test_trimp_needs_valid_inputs():
    assert load.banister_trimp(0, 150, 190, 50) is None        # keine Dauer
    assert load.banister_trimp(3600, None, 190, 50) is None    # keine HF
    assert load.banister_trimp(3600, 150, 190, None) is None   # kein Ruhepuls
    assert load.banister_trimp(3600, 150, 50, 190) is None     # max <= rest


def test_hrr_fraction_clamped():
    assert load.hrr_fraction(250, 190, 50) == 1.0   # über Max → geklemmt
    assert load.hrr_fraction(40, 190, 50) == 0.0    # unter Ruhe → geklemmt
    assert math.isclose(load.hrr_fraction(120, 190, 50), 0.5, rel_tol=1e-9)
