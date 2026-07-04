"""Strava: OAuth-Verbindung, Token-Refresh und Aktivitäten-Sync."""

from __future__ import annotations

from typing import Any

import requests

from . import auth, config, store

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API_BASE = "https://www.strava.com/api/v3"
SCOPE = "read,activity:read_all,profile:read_all"

# Strava-"type"/"sport_type"-Werte, die als Radfahren zählen.
RIDE_TYPES = {"Ride", "VirtualRide", "EBikeRide", "GravelRide", "MountainBikeRide", "Handcycle"}


def connect(cfg: dict[str, Any]) -> None:
    """Einmaliger OAuth-Login, speichert die Tokens lokal."""
    redirect = config.redirect_uri(cfg, "strava")
    result = auth.run_oauth_flow(
        provider="strava",
        authorize_url=AUTHORIZE_URL,
        auth_params={
            "client_id": str(cfg["strava"]["client_id"]),
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "approval_prompt": "auto",
        },
        port=cfg["server"]["port"],
        use_state=True,
    )
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg["strava"]["client_id"],
            "client_secret": cfg["strava"]["client_secret"],
            "code": result["code"],
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    config.set_provider_tokens(
        "strava",
        {
            "access_token": tok["access_token"],
            "refresh_token": tok["refresh_token"],
            "expires_at": tok["expires_at"],
            "athlete_id": tok.get("athlete", {}).get("id"),
        },
    )
    print("✅ Strava verbunden.")


def _valid_access_token(cfg: dict[str, Any]) -> str:
    tokens = config.get_provider_tokens("strava")
    if not tokens:
        raise RuntimeError("Strava ist nicht verbunden. Bitte zuerst:  python connect.py strava")

    # 60 s Puffer, damit der Token während des Syncs nicht abläuft.
    if tokens["expires_at"] - 60 > auth.now():
        return tokens["access_token"]

    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg["strava"]["client_id"],
            "client_secret": cfg["strava"]["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    tokens.update(
        access_token=tok["access_token"],
        refresh_token=tok["refresh_token"],
        expires_at=tok["expires_at"],
    )
    config.set_provider_tokens("strava", tokens)
    return tokens["access_token"]


def _map_activity(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["id"],
        "name": a.get("name"),
        "type": a.get("type"),
        "sport_type": a.get("sport_type"),
        "start_date": a.get("start_date"),
        "start_date_local": a.get("start_date_local"),
        "distance_m": a.get("distance"),
        "moving_time_s": a.get("moving_time"),
        "elapsed_time_s": a.get("elapsed_time"),
        "total_elevation_gain_m": a.get("total_elevation_gain"),
        "average_speed_ms": a.get("average_speed"),
        "max_speed_ms": a.get("max_speed"),
        "average_watts": a.get("average_watts"),
        "weighted_average_watts": a.get("weighted_average_watts"),
        "max_watts": a.get("max_watts"),
        "average_heartrate": a.get("average_heartrate"),
        "max_heartrate": a.get("max_heartrate"),
        "kilojoules": a.get("kilojoules"),
        "suffer_score": a.get("suffer_score"),
        "raw_json": store.dumps(a),
    }


def sync(cfg: dict[str, Any], *, full: bool = False) -> int:
    """Holt neue Aktivitäten (nur Radfahren) und speichert sie. Gibt Anzahl zurück."""
    token = _valid_access_token(cfg)
    headers = {"Authorization": f"Bearer {token}"}

    after = None
    if not full:
        after = store.get_state("strava_last_after")

    params: dict[str, Any] = {"per_page": 100, "page": 1}
    if after:
        params["after"] = int(after)

    fetched: list[dict[str, Any]] = []
    newest_epoch = int(after) if after else 0

    while True:
        resp = requests.get(
            f"{API_BASE}/athlete/activities", headers=headers, params=params, timeout=30
        )
        if resp.status_code == 429:
            raise RuntimeError("Strava-Rate-Limit erreicht. Bitte später erneut syncen.")
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for a in batch:
            if a.get("type") in RIDE_TYPES or a.get("sport_type") in RIDE_TYPES:
                fetched.append(_map_activity(a))
            ts = a.get("start_date")
            if ts:
                import datetime as _dt

                epoch = int(
                    _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                )
                newest_epoch = max(newest_epoch, epoch)
        params["page"] += 1

    n = store.upsert_strava_activities(fetched)
    if newest_epoch:
        store.set_state("strava_last_after", str(newest_epoch))
    return n


STREAM_KEYS = "latlng,velocity_smooth,time,grade_smooth,heartrate"


def fetch_streams(cfg: dict[str, Any], ride_id: int) -> dict[str, Any]:
    """Holt die Zeitreihen (GPS, Tempo, Zeit, Steigung, HF) einer Fahrt."""
    token = _valid_access_token(cfg)
    resp = requests.get(
        f"{API_BASE}/activities/{ride_id}/streams",
        headers={"Authorization": f"Bearer {token}"},
        params={"keys": STREAM_KEYS, "key_by_type": "true"},
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("Strava-Rate-Limit erreicht. Bitte später erneut.")
    if resp.status_code in (404, 401):
        return {}
    resp.raise_for_status()
    return resp.json()


def is_connected() -> bool:
    return config.get_provider_tokens("strava") is not None
