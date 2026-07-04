"""Datenhaltung für Strava- und Whoop-Daten.

Zwei Backends, gleiche Schnittstelle:

* **Lokal** – SQLite-Datei unter data/bikedash.db (Standard, nichts einzurichten).
* **Cloud** – PostgreSQL, sobald die Umgebungsvariable ``DATABASE_URL`` gesetzt
  ist (z. B. Neon). So kann dasselbe Programm gehostet werden, ohne dass die
  Daten auf einer "vergesslichen" Cloud-Festplatte liegen.

Schreibzugriffe sind "upserts": neue Datensätze werden eingefügt, bekannte
aktualisiert. Ein erneuter Sync ist damit idempotent. Die konkrete SQL ist so
gewählt, dass sie auf beiden Backends identisch läuft (``ON CONFLICT``).
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from . import config
from .config import DB_PATH  # Modul-global, damit Tests ihn umbiegen können

# ``{INT}`` wird je Backend ersetzt: BIGINT in Postgres (Strava-IDs sprengen
# den 32-Bit-Bereich), INTEGER in SQLite (dort ohnehin 64-bittig).
SCHEMA = """
CREATE TABLE IF NOT EXISTS strava_activities (
    id                       {INT} PRIMARY KEY,
    name                     TEXT,
    type                     TEXT,
    sport_type               TEXT,
    start_date               TEXT,
    start_date_local         TEXT,
    distance_m               REAL,
    moving_time_s            {INT},
    elapsed_time_s           {INT},
    total_elevation_gain_m   REAL,
    average_speed_ms         REAL,
    max_speed_ms             REAL,
    average_watts            REAL,
    weighted_average_watts   REAL,
    max_watts                REAL,
    average_heartrate        REAL,
    max_heartrate            REAL,
    kilojoules               REAL,
    suffer_score             REAL,
    raw_json                 TEXT
);

CREATE TABLE IF NOT EXISTS whoop_workouts (
    id                  TEXT PRIMARY KEY,
    start               TEXT,
    "end"               TEXT,
    sport_id            {INT},
    sport_name          TEXT,
    strain              REAL,
    average_heart_rate  REAL,
    max_heart_rate      REAL,
    kilojoule           REAL,
    distance_meter      REAL,
    raw_json            TEXT
);

CREATE TABLE IF NOT EXISTS whoop_recovery (
    cycle_id            {INT} PRIMARY KEY,
    date                TEXT,
    recovery_score      REAL,
    resting_heart_rate  REAL,
    hrv_rmssd_milli     REAL,
    spo2_percentage     REAL,
    skin_temp_celsius   REAL,
    raw_json            TEXT
);

CREATE TABLE IF NOT EXISTS whoop_cycles (
    id                  {INT} PRIMARY KEY,
    start               TEXT,
    "end"               TEXT,
    day_strain          REAL,
    average_heart_rate  REAL,
    max_heart_rate      REAL,
    kilojoule           REAL,
    raw_json            TEXT
);

CREATE TABLE IF NOT EXISTS sync_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE TABLE IF NOT EXISTS app_kv (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE TABLE IF NOT EXISTS wind_segments (
    ride_id        {INT},
    t_idx          {INT},
    lat            REAL,
    lon            REAL,
    speed_kmh      REAL,
    grade          REAL,
    heading        REAL,
    wind_kmh       REAL,
    wind_from_deg  REAL,
    headwind_kmh   REAL,
    crosswind_kmh  REAL,
    PRIMARY KEY (ride_id, t_idx)
);
"""

# ``"end"`` ist in SQL ein reserviertes Wort → in den Spaltennamen quoten.
_QUOTED_COLS = {"end"}

_ENGINES: dict[str, Engine] = {}


def _resolve_url() -> tuple[str, bool]:
    """Gibt (SQLAlchemy-URL, is_sqlite) zurück."""
    url = config.database_url()
    if url:
        return url, False
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + str(DB_PATH), True


def _engine() -> Engine:
    url, is_sqlite = _resolve_url()
    eng = _ENGINES.get(url)
    if eng is None:
        eng = create_engine(url, pool_pre_ping=not is_sqlite, future=True)
        _init_schema(eng, is_sqlite)
        _ENGINES[url] = eng
    return eng


def _init_schema(engine: Engine, is_sqlite: bool) -> None:
    int_type = "INTEGER" if is_sqlite else "BIGINT"
    ddl = SCHEMA.replace("{INT}", int_type)
    with engine.begin() as conn:
        for stmt in ddl.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))


def _col_ref(col: str) -> str:
    return f'"{col}"' if col in _QUOTED_COLS else col


def _upsert(table: str, rows: list[dict[str, Any]], pk: str | tuple[str, ...]) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    pk_cols = (pk,) if isinstance(pk, str) else pk
    collist = ", ".join(_col_ref(c) for c in cols)
    values = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(
        f"{_col_ref(c)}=excluded.{_col_ref(c)}" for c in cols if c not in pk_cols
    )
    conflict = ", ".join(_col_ref(c) for c in pk_cols)
    sql = (
        f"INSERT INTO {table} ({collist}) VALUES ({values}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
    )
    with _engine().begin() as conn:
        conn.execute(text(sql), rows)
    return len(rows)


def upsert_strava_activities(rows: list[dict[str, Any]]) -> int:
    return _upsert("strava_activities", rows, "id")


def upsert_whoop_workouts(rows: list[dict[str, Any]]) -> int:
    return _upsert("whoop_workouts", rows, "id")


def upsert_whoop_recovery(rows: list[dict[str, Any]]) -> int:
    return _upsert("whoop_recovery", rows, "cycle_id")


def upsert_whoop_cycles(rows: list[dict[str, Any]]) -> int:
    return _upsert("whoop_cycles", rows, "id")


def replace_wind_segments(ride_id: int, rows: list[dict[str, Any]]) -> int:
    """Ersetzt die Wind-Abschnitte einer Fahrt (idempotent pro Fahrt)."""
    with _engine().begin() as conn:
        conn.execute(
            text("DELETE FROM wind_segments WHERE ride_id = :rid"), {"rid": ride_id}
        )
        if rows:
            cols = list(rows[0].keys())
            collist = ", ".join(cols)
            values = ", ".join(f":{c}" for c in cols)
            conn.execute(
                text(f"INSERT INTO wind_segments ({collist}) VALUES ({values})"), rows
            )
    return len(rows)


def wind_processed_ids() -> set[int]:
    with _engine().connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT ride_id FROM wind_segments"))
        return {r[0] for r in rows}


def get_state(key: str) -> str | None:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT value FROM sync_state WHERE key = :k"), {"k": key}
        ).fetchone()
        return row[0] if row else None


def set_state(key: str, value: str) -> None:
    with _engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sync_state (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
            ),
            {"k": key, "v": value},
        )


def get_kv(key: str) -> str | None:
    """Kleiner Schlüssel-Wert-Speicher (u. a. für OAuth-Tokens in der Cloud)."""
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT value FROM app_kv WHERE key = :k"), {"k": key}
        ).fetchone()
        return row[0] if row else None


def set_kv(key: str, value: str) -> None:
    with _engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app_kv (key, value) VALUES (:k, :v) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
            ),
            {"k": key, "v": value},
        )


def delete_kv(key: str) -> None:
    with _engine().begin() as conn:
        conn.execute(text("DELETE FROM app_kv WHERE key = :k"), {"k": key})


def read_table(table: str) -> pd.DataFrame:
    """Tabelle als DataFrame lesen (für das Dashboard)."""
    _engine()  # stellt sicher, dass das Schema existiert
    with _engine().connect() as conn:
        return pd.read_sql_query(text(f"SELECT * FROM {table}"), conn)


def counts() -> dict[str, int]:
    out: dict[str, int] = {}
    with _engine().connect() as conn:
        for t in ("strava_activities", "whoop_workouts", "whoop_recovery", "whoop_cycles"):
            out[t] = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()
    return out


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
