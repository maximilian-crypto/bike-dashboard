"""OAuth2-Login-Flow für Strava und Whoop.

Beim Verbinden startet kurz ein lokaler Webserver, der die Weiterleitung
des Anbieters (mit dem ?code=...) abfängt. Der Browser öffnet sich
automatisch; nach der Bestätigung tauschen wir den Code gegen Tokens.
"""

from __future__ import annotations

import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

_SUCCESS_HTML = (
    "<html><body style='font-family:sans-serif;text-align:center;margin-top:15%'>"
    "<h2>✅ Verbunden!</h2><p>Du kannst dieses Fenster schließen "
    "und zum Terminal zurückkehren.</p></body></html>"
)
_ERROR_HTML = (
    "<html><body style='font-family:sans-serif;text-align:center;margin-top:15%'>"
    "<h2>❌ Fehler</h2><p>{msg}</p></body></html>"
)


class _CallbackServer:
    """Fängt genau eine OAuth-Weiterleitung auf einem festen Port ab."""

    def __init__(self, port: int, path_prefix: str) -> None:
        self.port = port
        self.path_prefix = path_prefix
        self.result: dict[str, str] = {}
        self._event = threading.Event()

        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if not parsed.path.startswith(server.path_prefix):
                    self.send_response(404)
                    self.end_headers()
                    return
                params = urllib.parse.parse_qs(parsed.query)
                if "error" in params:
                    server.result = {"error": params["error"][0]}
                    body = _ERROR_HTML.format(msg=params["error"][0])
                elif "code" in params:
                    server.result = {
                        "code": params["code"][0],
                        "state": params.get("state", [""])[0],
                    }
                    body = _SUCCESS_HTML
                else:
                    server.result = {"error": "keine Antwort erhalten"}
                    body = _ERROR_HTML.format(msg="keine Antwort erhalten")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
                server._event.set()

            def log_message(self, *_args: Any) -> None:  # Stille
                pass

        self._httpd = HTTPServer(("localhost", port), Handler)

    def wait_for_code(self, timeout: float = 300.0) -> dict[str, str]:
        thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        thread.start()
        got = self._event.wait(timeout)
        self._httpd.shutdown()
        if not got:
            raise TimeoutError("Zeitüberschreitung beim Warten auf die Anmeldung.")
        return self.result


def run_oauth_flow(
    *,
    provider: str,
    authorize_url: str,
    auth_params: dict[str, str],
    port: int,
    use_state: bool = True,
) -> dict[str, str]:
    """Öffnet den Browser, fängt die Weiterleitung ab, gibt code/state zurück."""
    state = secrets.token_urlsafe(16)
    if use_state:
        auth_params = {**auth_params, "state": state}

    url = f"{authorize_url}?{urllib.parse.urlencode(auth_params)}"
    server = _CallbackServer(port, f"/{provider}/")

    print(f"\nÖffne den Browser, um {provider.capitalize()} zu verbinden …")
    print("Falls sich nichts öffnet, kopiere diese URL in den Browser:\n")
    print(url + "\n")
    webbrowser.open(url)

    result = server.wait_for_code()
    if "error" in result:
        raise RuntimeError(f"{provider}: Anmeldung fehlgeschlagen ({result['error']}).")
    if use_state and result.get("state") != state:
        raise RuntimeError(f"{provider}: state stimmt nicht überein (Sicherheitsabbruch).")
    return result


def now() -> int:
    return int(time.time())
