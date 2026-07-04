"""Pytest-Setup: lenkt ALLE Tests auf eine isolierte Wegwerf-DB um.

So kann ein Test niemals die echte data/bikedash.db berühren. Die autouse-
Fixture greift automatisch in jedem Test.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    from bikedash import backup, config, store

    db = tmp_path / "test.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setattr(backup, "DB_PATH", db)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(config, "TOKENS_PATH", tmp_path / "tokens.json")
    yield
