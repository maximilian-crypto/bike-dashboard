import datetime as dt

from bikedash import backup, store

from .helpers import ride


def test_create_and_list_and_prune():
    store.upsert_strava_activities([ride(1, dt.datetime(2026, 6, 1, 9))])

    path = backup.create_backup()
    assert path.exists()
    assert path.suffix == ".db"

    backups = backup.list_backups()
    assert len(backups) == 1

    # Backup ist eine gültige, lesbare Kopie
    assert path.stat().st_size > 0
    assert backup.db_bytes()  # Original existiert


def test_prune_keeps_newest(monkeypatch):
    store.upsert_strava_activities([ride(1, dt.datetime(2026, 6, 1, 9))])
    # mehrere Backups mit eindeutigen Namen anlegen
    for i in range(5):
        p = backup.BACKUP_DIR
        backup.create_backup()
    # künstlich auf >keep auffüllen
    backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for i in range(20):
        (backup.BACKUP_DIR / f"bikedash-2020010{i % 9}-00000{i}.db").write_bytes(b"x")
    removed = backup.prune_backups(keep=3)
    assert removed > 0
    assert len(backup.list_backups()) == 3
