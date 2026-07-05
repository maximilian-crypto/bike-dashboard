from bikedash import store, zones


def test_max_hr_prefers_whoop():
    store.set_state("whoop_max_hr", "190")
    assert zones.max_hr_from_data() == 190
    assert "Whoop" in zones.source_note()


def test_percent_max_boundaries_without_resting():
    # Ohne Ruhepuls -> %-der-Max-HF (Whoop-Grenzen 40/60/70/80/90/100 %).
    z = zones.zones(200)
    assert z[0].low_bpm == 80 and z[0].high_bpm == 120    # Z1 40-60%
    assert z[1].low_bpm == 120 and z[1].high_bpm == 140   # Z2 60-70%
    assert z[4].high_bpm == 200                            # Z5 bis 100%
    assert zones.zone_for(2, 200).number == 2


def test_karvonen_hrr_boundaries():
    # Mit Ruhepuls -> Herzfrequenzreserve (Karvonen). HRR = 200-100 = 100.
    z = zones.zones(200, 100)
    assert z[1].low_bpm == 160 and z[1].high_bpm == 170   # Z2: 100 + 60-70% * 100
    assert z[0].low_bpm == 140                             # Z1: 100 + 40% * 100
    assert z[4].high_bpm == 200                            # Z5 bis Max


def test_hrr_matches_real_user():
    # Realfall: Max 198, Ruhe 70 -> Z2 soll ~147-160 sein (deckt sich mit Whoop).
    z2 = zones.zone_for(2, 198, 70)
    assert 145 <= z2.low_bpm <= 149
    assert 158 <= z2.high_bpm <= 161


def test_intensity_frac():
    # HRR-Anteil: HF genau in der Mitte -> 0.5
    assert abs(zones.intensity_frac(150, 200, 100) - 0.5) < 1e-6
    # Ohne Ruhepuls -> %max
    assert abs(zones.intensity_frac(150, 200) - 0.75) < 1e-6


def test_lthr_zones_use_threshold_bands():
    # Mit LTHR -> Friel-Schwellenzonen: Z4 endet bei LTHR, Z5 beginnt dort.
    z = zones.zones(max_hr=190, rest_hr=50, lthr=160)
    assert z[3].high_bpm == 160          # Z4 bis 1.00*LTHR
    assert z[4].low_bpm == 160           # Z5 ab LTHR
    assert z[1].low_bpm == round(0.81 * 160)   # Z2 ab 81% LTHR
    # LTHR hat Vorrang vor HRR (andere Grenzen als der %HRR-Modus).
    assert zones.zones(max_hr=190, rest_hr=50)[3].high_bpm != 160
    assert zones.method_label(rest_hr=50, lthr=160) == "Schwelle/LTHR"


def test_lt1_lt2_from_lthr():
    assert zones.lt1_lt2(160) == (131, 160)   # LT1 ≈ 0.82*160=131.2 -> 131, LT2 = LTHR


def test_lthr_from_config(monkeypatch):
    from bikedash import config
    monkeypatch.delenv("ATHLETE_LTHR", raising=False)
    config.save_config({"athlete": {"lthr": 158}})   # CONFIG_PATH ist per conftest isoliert
    assert zones.lthr_from_config() == 158
