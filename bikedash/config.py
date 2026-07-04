"""Konfiguration laden und Tokens speichern/lesen.

Alle Pfade sind relativ zum Projekt-Wurzelverzeichnis (eine Ebene über
diesem Paket). Zugangsdaten liegen in config.toml, die OAuth-Tokens in
tokens.json — beide werden nicht eingecheckt.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.toml"
TOKENS_PATH = ROOT / "tokens.json"
DB_PATH = ROOT / "data" / "bikedash.db"


class ConfigError(RuntimeError):
    pass


def database_url() -> str | None:
    """SQLAlchemy-URL der Cloud-Datenbank oder None (dann lokale SQLite).

    Neon/Heroku liefern ``postgres://…`` bzw. ``postgresql://…``; wir normalisieren
    auf den psycopg-3-Treiber. Die Verbindungs-URL kommt aus der Umgebung
    (``DATABASE_URL``), damit sie nie im Code/Repo landet.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def is_cloud() -> bool:
    """True, wenn wir gegen die gehostete DB laufen (Tokens/Config aus der Umgebung)."""
    return database_url() is not None


# Umgebungsvariable -> (Config-Sektion, Schlüssel, Typumwandlung).
# So lassen sich beim Hosting alle Zugangsdaten als Secrets setzen, ohne
# config.toml zu committen. Gesetzte Variablen haben Vorrang vor der Datei.
_ENV_MAP: dict[str, tuple[str, str, type]] = {
    "STRAVA_CLIENT_ID": ("strava", "client_id", str),
    "STRAVA_CLIENT_SECRET": ("strava", "client_secret", str),
    "WHOOP_CLIENT_ID": ("whoop", "client_id", str),
    "WHOOP_CLIENT_SECRET": ("whoop", "client_secret", str),
    "ORS_API_KEY": ("ors", "api_key", str),
    "ORS_PROFILE": ("ors", "profile", str),
    "ATHLETE_HOME_LAT": ("athlete", "home_lat", float),
    "ATHLETE_HOME_LON": ("athlete", "home_lon", float),
    "ATHLETE_WEEKLY_HOURS_TARGET": ("athlete", "weekly_hours_target", float),
    "ANTHROPIC_API_KEY": ("coach", "api_key", str),
    "COACH_MODEL": ("coach", "model", str),
    "NTFY_TOPIC": ("report", "ntfy_topic", str),
    "SERVER_PORT": ("server", "port", int),
}


def _overlay_env(cfg: dict[str, Any]) -> None:
    """Setzt/überschreibt Config-Werte aus den Umgebungsvariablen (in-place)."""
    for env_name, (section, key, cast) in _ENV_MAP.items():
        val = os.environ.get(env_name)
        if val is None or val == "":
            continue
        try:
            cfg.setdefault(section, {})[key] = cast(val)
        except (TypeError, ValueError):
            cfg.setdefault(section, {})[key] = val


def load_config() -> dict[str, Any]:
    cfg = load_config_raw()  # config.toml, falls vorhanden (sonst {})
    _overlay_env(cfg)        # Secrets aus der Umgebung haben Vorrang
    if not cfg:
        raise ConfigError(
            "Keine Konfiguration gefunden. Lokal: config.example.toml zu config.toml "
            "kopieren und ausfüllen. Beim Hosting: Secrets als Umgebungsvariablen setzen "
            "(STRAVA_CLIENT_ID, WHOOP_CLIENT_SECRET, … – siehe DEPLOY.md)."
        )

    for provider in ("strava", "whoop"):
        section = cfg.get(provider, {})
        cid = str(section.get("client_id", ""))
        secret = str(section.get("client_secret", ""))
        if not cid or cid.startswith("DEINE_") or not secret or secret.startswith("DEIN_"):
            raise ConfigError(
                f"In config.toml fehlen gültige Zugangsdaten für [{provider}]. "
                "Bitte client_id und client_secret eintragen (siehe README)."
            )
    cfg.setdefault("server", {}).setdefault("port", 8721)
    return cfg


def load_config_raw() -> dict[str, Any]:
    """Config laden OHNE Validierung (für die Einrichtungs-Oberfläche)."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def save_config(data: dict[str, dict[str, Any]]) -> None:
    """Schreibt config.toml aus der Oberfläche (eine Ebene Tabellen)."""
    parts: list[str] = []
    for section, table in data.items():
        parts.append(f"[{section}]")
        for k, v in table.items():
            parts.append(f"{k} = {_toml_value(v)}")
        parts.append("")
    CONFIG_PATH.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")


def provider_creds_ok(cfg: dict[str, Any], provider: str) -> bool:
    sec = cfg.get(provider, {})
    cid = str(sec.get("client_id", ""))
    secret = str(sec.get("client_secret", ""))
    return bool(cid) and not cid.startswith("DEIN") and bool(secret) and not secret.startswith("DEIN")


def redirect_uri(cfg: dict[str, Any], provider: str) -> str:
    port = cfg.get("server", {}).get("port", 8721)
    return f"http://localhost:{port}/{provider}/callback"


def has_routing(cfg: dict[str, Any]) -> bool:
    """True, wenn ORS-Key und Heimat-Koordinaten gesetzt sind."""
    ors = cfg.get("ors", {})
    ath = cfg.get("athlete", {})
    key = str(ors.get("api_key", ""))
    lat = float(ath.get("home_lat", 0) or 0)
    lon = float(ath.get("home_lon", 0) or 0)
    return bool(key) and not key.startswith("DEIN_") and (lat != 0.0 or lon != 0.0)


def athlete(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("athlete", {})


def ors(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("ors", {})


# ---------------------------------------------------------------------------
# Token-Speicher  (tokens.json)
# ---------------------------------------------------------------------------

# Beim Hosting liegen die OAuth-Tokens in der Datenbank (überleben Neustarts der
# vergesslichen Cloud-Festplatte); lokal weiterhin in tokens.json. Der Import von
# store erfolgt verzögert, um einen Import-Zyklus (store -> config) zu vermeiden.


def load_tokens() -> dict[str, Any]:
    if is_cloud():
        from . import store
        raw = store.get_kv("oauth_tokens")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not TOKENS_PATH.exists():
        return {}
    try:
        return json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_tokens(tokens: dict[str, Any]) -> None:
    if is_cloud():
        from . import store
        store.set_kv("oauth_tokens", json.dumps(tokens, sort_keys=True))
        return
    TOKENS_PATH.write_text(
        json.dumps(tokens, indent=2, sort_keys=True), encoding="utf-8"
    )


def set_provider_tokens(provider: str, data: dict[str, Any]) -> None:
    tokens = load_tokens()
    tokens[provider] = data
    save_tokens(tokens)


def get_provider_tokens(provider: str) -> dict[str, Any] | None:
    return load_tokens().get(provider)
