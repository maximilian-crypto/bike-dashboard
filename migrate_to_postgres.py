r"""Einmalige Migration: lokale SQLite-Daten in die Cloud-DB (Neon) heben.

So musst du nach dem Umzug nicht alles neu synchronisieren, sondern nimmst deine
bereits erfassten Strava-/Whoop-Daten mit.

Benutzung (PowerShell, im Projektordner, venv aktiv):

    $env:DATABASE_URL = "postgresql://USER:PW@HOST/DB?sslmode=require"
    .\.venv\Scripts\python.exe migrate_to_postgres.py

Alternativ die URL als Argument übergeben:

    python migrate_to_postgres.py "postgresql://USER:PW@HOST/DB?sslmode=require"

Das Skript liest NUR aus der lokalen SQLite und SCHREIBT in die Ziel-DB. Es
verändert deine lokale data/bikedash.db nicht.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys


def main() -> int:
    target = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL", "")).strip()
    if not target:
        print("❌ Keine Ziel-DB. DATABASE_URL setzen oder als Argument übergeben.")
        return 1
    os.environ["DATABASE_URL"] = target  # store schreibt damit nach Postgres

    from bikedash import config, store

    src_path = config.DB_PATH
    if not src_path.exists():
        print(f"ℹ️  Keine lokale DB unter {src_path} – nichts zu migrieren.")
        return 0

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row

    def rows_of(table: str) -> list[dict]:
        try:
            return [dict(r) for r in src.execute(f"SELECT * FROM {table}")]
        except sqlite3.OperationalError:
            return []

    print(f"Lese aus {src_path} → schreibe in die Cloud-DB …")

    n = store.upsert_strava_activities(rows_of("strava_activities"))
    print(f"  Strava-Fahrten:   {n}")
    n = store.upsert_whoop_workouts(rows_of("whoop_workouts"))
    print(f"  Whoop-Workouts:   {n}")
    n = store.upsert_whoop_recovery(rows_of("whoop_recovery"))
    print(f"  Whoop-Recovery:   {n}")
    n = store.upsert_whoop_cycles(rows_of("whoop_cycles"))
    print(f"  Whoop-Zyklen:     {n}")

    # Wind-Segmente pro Fahrt übertragen.
    wind = rows_of("wind_segments")
    by_ride: dict[int, list[dict]] = {}
    for r in wind:
        by_ride.setdefault(r["ride_id"], []).append(r)
    for ride_id, segs in by_ride.items():
        store.replace_wind_segments(ride_id, segs)
    print(f"  Wind-Segmente:    {len(wind)} (in {len(by_ride)} Fahrten)")

    # Sync-Fortschritt übernehmen (damit der Cloud-Sync inkrementell weitermacht).
    for r in rows_of("sync_state"):
        store.set_state(r["key"], r["value"])
    print("  Sync-Status:      übernommen")

    # OAuth-Tokens aus tokens.json in die DB übernehmen (optional).
    if config.TOKENS_PATH.exists():
        try:
            toks = json.loads(config.TOKENS_PATH.read_text(encoding="utf-8"))
            store.set_kv("oauth_tokens", json.dumps(toks, sort_keys=True))
            print("  OAuth-Tokens:     übernommen (aus tokens.json)")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  OAuth-Tokens:     übersprungen ({exc})")

    src.close()
    print("\n✅ Migration fertig. Prüfe im Dashboard, ob die Daten da sind.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
