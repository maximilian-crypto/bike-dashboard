"""Tests für Leistungszonen und die abfahrbare Einheiten-Struktur."""

from __future__ import annotations

from bikedash import power

FTP = 170


def test_zones_scale_with_ftp():
    zs = power.zones(FTP)
    assert len(zs) == 5
    z2 = zs[1]
    assert z2.number == 2 and "Grundlage" in z2.label
    assert z2.low_w == round(0.56 * FTP) and z2.high_w == round(0.75 * FTP)


def test_no_ftp_no_zones():
    assert power.zones(None) == []
    assert power.zones(0) == []
    assert power.zone_for(2, None) is None


def test_recovery_zone_is_a_rideable_band_not_zero():
    """„Fahre 0 bis 94 Watt" wäre als Vorgabe unbrauchbar."""
    z1 = power.zone_for(1, FTP)
    assert z1 is not None and z1.low_w > 0
    assert z1.low_w < z1.high_w


def test_threshold_session_becomes_intervals():
    blocks = power.structure("THRESHOLD", 70, FTP, "85–100")
    work = [b for b in blocks if b.label.startswith("Intervall")]
    assert len(work) >= power.MIN_REPS
    assert all(b.minutes == 8 and b.zone == 4 for b in work)
    assert blocks[0].label == "Einfahren" and blocks[-1].label == "Ausfahren"
    # Zwischen den Intervallen liegen Pausen, nach dem letzten nicht.
    assert blocks[-2].label.startswith("Intervall")


def test_endurance_session_is_continuous():
    blocks = power.structure("ENDURANCE", 90, FTP)
    assert [b.label for b in blocks] == ["Einfahren", "Hauptteil", "Ausfahren"]
    main = blocks[1]
    assert main.zone == 2
    assert main.low_w == round(0.56 * FTP)


def test_structure_respects_prescribed_duration():
    """Die Einheit darf das Wochenziel nicht sprengen."""
    for minutes in (40, 60, 75, 90, 120):
        for kind in ("RECOVERY", "ENDURANCE", "TEMPO", "THRESHOLD"):
            total = power.total_minutes(power.structure(kind, minutes, FTP))
            assert total <= minutes, (kind, minutes, total)


def test_short_session_falls_back_to_continuous():
    """Zu wenig Zeit für zwei Intervalle → sauberer Dauerreiz statt Stückwerk."""
    blocks = power.structure("THRESHOLD", 30, FTP)
    assert not any(b.label.startswith("Intervall") for b in blocks)
    assert any(b.label == "Hauptteil" and b.zone == 4 for b in blocks)


def test_warmup_never_disappears_on_short_sessions():
    blocks = power.structure("THRESHOLD", 25, FTP)
    assert blocks[0].label == "Einfahren" and blocks[0].minutes >= 3
    assert blocks[-1].label == "Ausfahren" and blocks[-1].minutes >= 3


def test_no_structure_without_ftp_or_for_rest():
    assert power.structure("ENDURANCE", 90, None) == []
    assert power.structure("REST", 0, FTP) == []
    assert power.structure("ENDURANCE", 0, FTP) == []


def test_describe_is_phone_sized():
    txt = power.describe(power.structure("THRESHOLD", 70, FTP, "85–100"))
    assert "×8'" in txt and "W" in txt and "ein" in txt and "aus" in txt
    assert len(txt) < 60
    assert power.describe([]) == ""
