"""Neue Daten von Strava und Whoop holen.

Benutzung:
    python sync.py            # nur Neues seit dem letzten Sync (schnell)
    python sync.py --full     # alles neu holen

Dieses Skript ist ideal für eine geplante Windows-Aufgabe (siehe README),
damit der Sync automatisch läuft.
"""

from __future__ import annotations

import sys
from datetime import datetime

from bikedash import backup, config, store, strava, whoop


def main() -> int:
    try:
        cfg = config.load_config()
    except config.ConfigError as exc:
        print(f"\n⚠️  {exc}\n")
        return 1

    full = "--full" in sys.argv
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] Sync gestartet ({'voll' if full else 'inkrementell'}) …")

    ok = True

    if strava.is_connected():
        try:
            n = strava.sync(cfg, full=full)
            print(f"  Strava:  {n} Fahrten aktualisiert.")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  Strava:  FEHLER – {exc}")
    else:
        print("  Strava:  nicht verbunden (python connect.py strava).")

    if whoop.is_connected():
        try:
            res = whoop.sync(cfg, full=full)
            print(
                f"  Whoop:   {res['recovery']} Recovery, "
                f"{res['cycles']} Zyklen, {res['workouts']} Workouts aktualisiert."
            )
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  Whoop:   FEHLER – {exc}")
    else:
        print("  Whoop:   nicht verbunden (python connect.py whoop).")

    c = store.counts()
    print(
        f"  Gesamt in DB: {c['strava_activities']} Fahrten, "
        f"{c['whoop_recovery']} Recovery-Tage."
    )

    # Einmal täglich eine Sicherung anlegen.
    try:
        today_str = datetime.now().strftime("%Y%m%d")
        if not any(today_str in p.name for p in backup.list_backups()):
            bp = backup.create_backup()
            backup.prune_backups(keep=14)
            print(f"  Backup:  {bp.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"  Backup übersprungen: {exc}")

    store.set_state("last_sync", stamp)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
