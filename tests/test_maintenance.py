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


# --- Indoor-Gewichtung -----------------------------------------------------

def test_indoor_km_ignored_without_factor():
    """Ohne indoor_factor zählen Rollen-Kilometer gar nicht (Reifen, Bremsen …)."""
    comp = {"id": "tire_rear", "name": "Reifen", "icon": "🛞",
            "interval_km": 3500, "installed_km": 0.0, "indoor_factor": 0.0}
    s = maintenance.status_of(comp, 1000.0, 2000.0)
    assert s.wear_km == 1000
    assert s.indoor_km_counted == 0


def test_indoor_km_counted_partially_for_chain():
    """Die Kette wird auf der Rolle belastet – aber anteilig."""
    comp = {"id": "chain", "name": "Kette", "icon": "🔗",
            "interval_km": 3000, "installed_km": 0.0, "indoor_factor": 0.6}
    s = maintenance.status_of(comp, 1000.0, 1000.0)
    assert s.wear_km == 1600          # 1000 Straße + 0,6 × 1000 Rolle
    assert s.indoor_km_counted == 600


def test_defaults_wear_only_drivetrain_indoors():
    """Vorlagen: Indoor belastet Antrieb und Lenkerband, sonst nichts."""
    zero = {c["id"] for c in maintenance.DEFAULT_COMPONENTS
            if c["indoor_factor"] == 0.0}
    assert {"cassette", "tire_front", "tire_rear", "brake_pads", "cables"} <= zero
    nonzero = {c["id"] for c in maintenance.DEFAULT_COMPONENTS
               if c["indoor_factor"] > 0.0}
    assert nonzero == {"chain", "chain_lube", "bar_tape"}


def test_reset_stores_component_own_odometer():
    """Nach dem Wechsel muss der Verschleiß je Bauteil wieder bei null stehen."""
    state = maintenance.reset_all(maintenance.default_state(), 4000.0, 1000.0)
    for comp in state:
        assert maintenance.status_of(comp, 4000.0, 1000.0).wear_km == 0
    chain = next(c for c in state if c["id"] == "chain")
    tire = next(c for c in state if c["id"] == "tire_rear")
    assert chain["installed_km"] == 4600.0   # 4000 + 0,6 × 1000
    assert tire["installed_km"] == 4000.0    # Rolle zählt hier nicht


def test_reset_component_uses_indoor_factor():
    state = maintenance.reset_component(
        maintenance.default_state(), "chain", 1000.0, 500.0)
    chain = next(c for c in state if c["id"] == "chain")
    assert chain["installed_km"] == 1300.0   # 1000 + 0,6 × 500


def test_indoor_factor_clamped_and_defaulted():
    assert maintenance.status_of(
        {"id": "x", "name": "X", "icon": "🔧", "interval_km": 100,
         "installed_km": 0.0, "indoor_factor": 5.0}, 0.0, 100.0).wear_km == 100
    # Altbestand ohne das Feld: Rolle zählt nicht mit.
    assert maintenance.status_of(
        {"id": "y", "name": "Y", "icon": "🔧", "interval_km": 100,
         "installed_km": 0.0}, 0.0, 100.0).wear_km == 0


def test_save_load_roundtrip_keeps_indoor_factor():
    maintenance.save_state(maintenance.default_state())
    loaded = maintenance.load_state()
    chain = next(c for c in loaded if c["id"] == "chain")
    assert chain["indoor_factor"] == 0.6
