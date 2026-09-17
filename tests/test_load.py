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


# --- Einheitliche TSS-Skala ------------------------------------------------

MAX, REST, LTHR = 188, 52, 165


def test_threshold_hr_prefers_lthr():
    assert load.threshold_hr(MAX, REST, LTHR) == 165.0


def test_threshold_hr_estimated_from_hrr():
    """Ohne Feldtest: Obergrenze von Z4 im Zonenmodell (0,90 HRR)."""
    assert load.threshold_hr(MAX, REST) == REST + 0.90 * (MAX - REST)
    assert load.threshold_hr(MAX, None) == MAX * 0.90
    assert load.threshold_hr(None, REST) is None


def test_hour_at_threshold_is_100():
    """Der Ankerpunkt der Skala – per Definition 100."""
    tss = load.hr_tss(3600, LTHR, MAX, REST, LTHR)
    assert abs(tss - 100.0) < 0.01


def test_hr_tss_preserves_trimp_ratios():
    """Die Normierung ändert nur die Maßeinheit, nicht das Verhältnis."""
    a = (3600, 150.0)
    b = (5400, 135.0)
    r_trimp = (load.banister_trimp(*a, MAX, REST)
               / load.banister_trimp(*b, MAX, REST))
    r_tss = (load.hr_tss(*a, MAX, REST, LTHR)
             / load.hr_tss(*b, MAX, REST, LTHR))
    assert abs(r_trimp - r_tss) < 1e-9


def test_hr_tss_is_cooler_than_raw_trimp():
    """Rohes TRIMP läuft heisser als TSS – genau der Skalenfehler von vorher."""
    trimp = load.banister_trimp(3600, LTHR, MAX, REST)
    assert trimp > 150            # ~157 bei dieser Schwellenlage
    assert load.hr_tss(3600, LTHR, MAX, REST, LTHR) == 100


def test_hr_tss_none_without_hr():
    assert load.hr_tss(3600, None, MAX, REST, LTHR) is None
    assert load.hr_tss(3600, 150.0, None, None, None) is None


def test_power_tss_hour_at_ftp_is_100():
    assert abs(load.power_tss(3600, 250, 250) - 100.0) < 0.01


def test_power_tss_scales_with_intensity_squared():
    """TSS wächst quadratisch mit der Intensität: 1 h bei 0,8 IF = 64."""
    assert abs(load.power_tss(3600, 200, 250) - 64.0) < 0.01
    # Doppelte Dauer, gleiche Intensität = doppelte Last.
    assert abs(load.power_tss(7200, 200, 250) - 128.0) < 0.01


def test_power_tss_needs_ftp_and_watts():
    assert load.power_tss(3600, 200, None) is None
    assert load.power_tss(3600, None, 250) is None
    assert load.power_tss(3600, 200, 0) is None
