"""Passwort-Schutz für das gehostete Dashboard.

Das Streamlit-Dashboard bekommt beim Hosting eine öffentliche URL. Damit nicht
jeder deine Gesundheitsdaten sieht, liegt ein Passwort-Gate davor:

* Das Passwort steht als Secret ``APP_PASSWORD`` (Umgebungsvariable oder
  ``st.secrets``) – nie im Code.
* Ist kein ``APP_PASSWORD`` gesetzt (lokale Entwicklung), ist das Gate aus.
* Fehlversuche werden pro Sitzung gezählt und nach mehreren Versuchen kurz
  gesperrt (einfache Brute-Force-Bremse). Der Vergleich läuft konstant-zeitig.
"""

from __future__ import annotations

import hmac
import os
import time

import streamlit as st

_MAX_TRIES = 5          # danach Sperre
_LOCK_SECONDS = 60      # Sperrdauer nach zu vielen Fehlversuchen


def _secret(name: str) -> str:
    """Secret aus der Umgebung oder aus st.secrets lesen (leerer String = fehlt)."""
    val = os.environ.get(name)
    if val:
        return val
    try:
        return str(st.secrets[name])  # type: ignore[index]
    except Exception:
        return ""


def require_login() -> None:
    """Blockiert die Seite, bis das richtige Passwort eingegeben wurde.

    Ohne gesetztes ``APP_PASSWORD`` passiert nichts (lokaler Betrieb)."""
    password = _secret("APP_PASSWORD")
    if not password:
        return  # kein Gate lokal

    if st.session_state.get("_authed"):
        return

    st.markdown(
        "<div style='max-width:360px;margin:12vh auto 0;text-align:center'>"
        "<div style='font-size:30px;font-weight:700;letter-spacing:.16em'>🚴 RIDE</div>"
        "<div style='color:#7e8696;margin:4px 0 20px'>Bitte anmelden</div></div>",
        unsafe_allow_html=True,
    )
    box = st.container()
    _, mid, _ = box.columns([1, 2, 1])

    lock_until = st.session_state.get("_login_lock_until", 0.0)
    remaining = int(lock_until - time.time())
    if remaining > 0:
        mid.error(f"Zu viele Fehlversuche. Bitte {remaining}s warten.")
        st.stop()

    with mid.form("login", clear_on_submit=True):
        entered = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Anmelden", use_container_width=True)

    if submitted:
        if hmac.compare_digest(entered, password):
            st.session_state["_authed"] = True
            st.session_state.pop("_login_fails", None)
            st.session_state.pop("_login_lock_until", None)
            st.rerun()
        else:
            fails = st.session_state.get("_login_fails", 0) + 1
            st.session_state["_login_fails"] = fails
            if fails >= _MAX_TRIES:
                st.session_state["_login_lock_until"] = time.time() + _LOCK_SECONDS
                st.session_state["_login_fails"] = 0
                mid.error("Zu viele Fehlversuche – kurz gesperrt.")
            else:
                mid.error(f"Falsches Passwort ({fails}/{_MAX_TRIES}).")

    st.stop()
