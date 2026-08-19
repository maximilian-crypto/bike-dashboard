"""Tests für den Verschleiß-/Wartungs-Tracker.

Die conftest-Fixture lenkt den Store auf eine Wegwerf-DB – Save/Load geht also
gegen eine isolierte Datenbank.
"""

from __future__ import annotations

from bikedash import maintenance


def test_empty_store_yields_defaults():
    state = maintenance.load_state()
    assert state == maintenance.default_state()
    assert "chain" in {c["id"] for c in state}


def test_status_due_when_over_interval():
    comp = {"id": "chain", "name": "Kette", "icon": "🔗",
            "interval_km": 3000, "installed_km": 0.0}
    s = maintenance.status_of(comp, 3200)
    assert s.wear_km == 3200
    assert s.remaining_km == -200
    assert s.status == maintenance.STATUS_DUE
    assert s.pct > 1.0


def test_status_soon_near_interval():
    comp = {"id": "c", "name": "C", "icon": "🔧",
            "interval_km": 1000, "installed_km": 0.0}
    assert maintenance.status_of(comp, 850).status == maintenance.STATUS_SOON
    assert maintenance.status_of(comp, 500).status == maintenance.STATUS_OK


def test_reset_component_zeroes_wear():
    state = maintenance.default_state()
    state = maintenance.reset_component(state, "chain", 5000)
    chain = next(c for c in state if c["id"] == "chain")
    assert chain["installed_km"] == 5000
    assert maintenance.status_of(chain, 5000).wear_km == 0


def test_installed_km_capped_prevents_negative_wear():
    comp = {"id": "x", "name": "X", "icon": "🔧",
            "interval_km": 1000, "installed_km": 5000}
    assert maintenance.status_of(comp, 3000).wear_km == 0


def test_save_load_roundtrip():
    state = maintenance.reset_all(maintenance.default_state(), 1234.0)
    maintenance.save_state(state)
    loaded = maintenance.load_state()
    assert loaded and all(c["installed_km"] == 1234.0 for c in loaded)


def test_statuses_sorted_by_wear_desc():
    state = [
        {"id": "a", "name": "A", "icon": "🔧", "interval_km": 1000, "installed_km": 0.0},
        {"id": "b", "name": "B", "icon": "🔧", "interval_km": 1000, "installed_km": 900.0},
    ]
    ranked = maintenance.statuses(state, 1000.0)
    assert [s.id for s in ranked] == ["a", "b"]  # a stärker verschlissen
