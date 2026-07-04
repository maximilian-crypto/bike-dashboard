"""Whoop (API v2): OAuth-Verbindung, Token-Refresh, Sync von Recovery,
Zyklen (Tagesbelastung) und Workouts.

Whoop liefert die Körper-/Belastungsseite: Recovery-Score, Ruhepuls, HRV
und die tägliche Strain — als Kontext zu den Strava-Fahrten.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import requests

from . import auth, config, store

AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_BASE = "https://api.prod.whoop.com/developer/v2"
SCOPE = (
    "read:recovery read:cycles read:sleep read:workout "
    "read:profile read:body_measurement offline"
)


def connect(cfg: dict[str, Any]) -> None:
    redirect = config.redirect_uri(cfg, "whoop")
    result = auth.run_oauth_flow(
        provider="whoop",
        authorize_url=AUTHORIZE_URL,
        auth_params={
            "client_id": str(cfg["whoop"]["client_id"]),
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
        },
        port=cfg["server"]["port"],
        use_state=True,
    )
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg["whoop"]["client_id"],
            "client_secret": cfg["whoop"]["client_secret"],
            "code": result["code"],
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    config.set_provider_tokens(
        "whoop",
        {
            "access_token": tok["access_token"],
            "refresh_token": tok.get("refresh_token"),
            "expires_at": auth.now() + int(tok.get("expires_in", 3600)),
        },
    )
    print("✅ Whoop verbunden.")


def _valid_access_token(cfg: dict[str, Any]) -> str:
    tokens = config.get_provider_tokens("whoop")
    if not tokens:
        raise RuntimeError("Whoop ist nicht verbunden. Bitte zuerst:  python connect.py whoop")

    if tokens["expires_at"] - 60 > auth.now():
        return tokens["access_token"]

    if not tokens.get("refresh_token"):
        raise RuntimeError("Whoop-Token abgelaufen und kein Refresh-Token. Bitte neu verbinden.")

    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg["whoop"]["client_id"],
            "client_secret": cfg["whoop"]["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "scope": SCOPE,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    tokens.update(
        access_token=tok["access_token"],
        refresh_token=tok.get("refresh_token", tokens["refresh_token"]),
        expires_at=auth.now() + int(tok.get("expires_in", 3600)),
    )
    config.set_provider_tokens("whoop", tokens)
    return tokens["access_token"]


def _paged(token: str, path: str, start: str | None) -> list[dict[str, Any]]:
    """Holt alle Seiten einer Whoop-Collection ab dem Zeitpunkt `start`."""
    headers = {"Authorization": f"Bearer {token}"}
    params: dict[str, Any] = {"limit": 25}
    if start:
        params["start"] = start
    records: list[dict[str, Any]] = []
    while True:
        resp = requests.get(f"{API_BASE}/{path}", headers=headers, params=params, timeout=30)
        if resp.status_code == 429:
            raise RuntimeError("Whoop-Rate-Limit erreicht. Bitte später erneut syncen.")
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        nxt = data.get("next_token")
        if not nxt:
            break
        params["nextToken"] = nxt
    return records


def _score(rec: dict[str, Any]) -> dict[str, Any]:
    return rec.get("score") or {}


def fetch_body_measurement(token: str) -> dict[str, Any]:
    """Holt Whoops Körpermaße inkl. der aus ~1 Jahr Daten bestimmten Max-HF."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{API_BASE}/user/measurement/body", headers=headers, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    return {}


def sync(cfg: dict[str, Any], *, full: bool = False) -> dict[str, int]:
    token = _valid_access_token(cfg)

    # Max-HF (für die HF-Zonen) bei jedem Sync auffrischen.
    body = fetch_body_measurement(token)
    if body.get("max_heart_rate"):
        store.set_state("whoop_max_hr", str(body["max_heart_rate"]))

    start = None if full else store.get_state("whoop_last_start")
    if start is None and not full:
        # Erststart: 2 Jahre zurück.
        start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=730)).isoformat()

    # --- Zyklen (Tagesbelastung) ---
    cycles_raw = _paged(token, "cycle", start)
    cycle_start: dict[int, str] = {}
    cycle_rows = []
    for c in cycles_raw:
        s = _score(c)
        cycle_start[c["id"]] = c.get("start")
        cycle_rows.append({
            "id": c["id"],
            "start": c.get("start"),
            "end": c.get("end"),
            "day_strain": s.get("strain"),
            "average_heart_rate": s.get("average_heart_rate"),
            "max_heart_rate": s.get("max_heart_rate"),
            "kilojoule": s.get("kilojoule"),
            "raw_json": store.dumps(c),
        })

    # --- Recovery ---
    rec_rows = []
    for r in _paged(token, "recovery", start):
        s = _score(r)
        cid = r.get("cycle_id")
        date = cycle_start.get(cid)
        rec_rows.append({
            "cycle_id": cid,
            "date": (date or "")[:10] if date else None,
            "recovery_score": s.get("recovery_score"),
            "resting_heart_rate": s.get("resting_heart_rate"),
            "hrv_rmssd_milli": s.get("hrv_rmssd_milli"),
            "spo2_percentage": s.get("spo2_percentage"),
            "skin_temp_celsius": s.get("skin_temp_celsius"),
            "raw_json": store.dumps(r),
        })

    # --- Workouts ---
    wk_rows = []
    for w in _paged(token, "activity/workout", start):
        s = _score(w)
        wk_rows.append({
            "id": str(w["id"]),
            "start": w.get("start"),
            "end": w.get("end"),
            "sport_id": w.get("sport_id"),
            "sport_name": w.get("sport_name"),
            "strain": s.get("strain"),
            "average_heart_rate": s.get("average_heart_rate"),
            "max_heart_rate": s.get("max_heart_rate"),
            "kilojoule": s.get("kilojoule"),
            "distance_meter": s.get("distance_meter"),
            "raw_json": store.dumps(w),
        })

    n_cycles = store.upsert_whoop_cycles(cycle_rows)
    n_rec = store.upsert_whoop_recovery([r for r in rec_rows if r["cycle_id"] is not None])
    n_wk = store.upsert_whoop_workouts(wk_rows)

    # Fortschritt merken: jüngstes gesehenes Zyklus-Ende.
    ends = [c.get("end") for c in cycles_raw if c.get("end")]
    if ends:
        store.set_state("whoop_last_start", max(ends))

    return {"cycles": n_cycles, "recovery": n_rec, "workouts": n_wk}


def is_connected() -> bool:
    return config.get_provider_tokens("whoop") is not None
