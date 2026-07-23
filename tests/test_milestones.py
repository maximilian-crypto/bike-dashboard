"""Tests für die Distanz-Meilensteine & Orden (reine Logik, keine DB)."""

from __future__ import annotations

from bikedash import milestones


def test_zero_km_has_no_earned_but_targets():
    mv = milestones.compute(0)
    assert mv.earned == []
    assert mv.latest is None
    assert mv.badges_total == len(milestones._CATALOG)
    assert mv.next_targets
    assert mv.next_targets[0].remaining_km > 0


def test_earned_latest_and_bounds():
    mv = milestones.compute(300)
    assert any(b.name == "Marathon-Distanz" for b in mv.earned)
    assert all(b.km <= 300 for b in mv.earned)
    assert mv.latest is not None and mv.latest.km <= 300
    # latest ist der jüngste (höchste) freigeschaltete Orden
    assert mv.latest.km == max(b.km for b in mv.earned)


def test_targets_sorted_ahead_and_progress_bounded():
    mv = milestones.compute(150, n_targets=3)
    kms = [t.km for t in mv.next_targets]
    assert kms == sorted(kms)
    assert all(t.km > 150 for t in mv.next_targets)
    assert all(0.0 <= t.progress <= 1.0 for t in mv.next_targets)
    assert all(t.remaining_km > 0 for t in mv.next_targets)


def test_theme_filter_only_counts_that_theme():
    scifi = sum(1 for c in milestones._CATALOG if c[3] == "scifi")
    mv = milestones.compute(1e9, themes={"scifi"})
    assert mv.badges_total == scifi
    assert all(b.theme == "scifi" for b in mv.earned)
    # der volle Katalog bleibt für die Galerie erhalten
    assert len(mv.catalog) == len(milestones._CATALOG)


def test_generic_milestones_strictly_increasing_with_variance():
    ms = milestones.generic_milestones(500)
    assert ms and ms[0] > 0
    assert all(b > a for a, b in zip(ms, ms[1:]))
    gaps = [b - a for a, b in zip([0.0] + ms, ms)]
    # ~40 km ± 40 %, auf 5 km gerundet → grob in diesem Fenster
    assert all(5.0 <= g <= milestones.GENERIC_STEP_KM * 1.4 + 5 for g in gaps)


def test_generic_is_deterministic():
    assert milestones.generic_milestones(300) == milestones.generic_milestones(300)
