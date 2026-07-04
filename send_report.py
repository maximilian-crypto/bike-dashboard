"""Erzeugt den Morgen-Report und schickt ihn (falls konfiguriert) ans Handy.

Für eine geplante Windows-Aufgabe gedacht (z. B. täglich 6:30 Uhr) — siehe README.
Benutzung:
    python send_report.py            # bauen + pushen
    python send_report.py --print    # nur anzeigen, nicht senden
"""

from __future__ import annotations

import sys

from bikedash import config, report


def main() -> int:
    try:
        cfg = config.load_config()
    except config.ConfigError as exc:
        print(f"⚠️  {exc}")
        return 1

    title, message = report.build_text(cfg)
    print(title)
    print(message)

    if "--print" in sys.argv:
        return 0

    if report.send_push(cfg, title, message):
        print("\n✅ Push gesendet.")
    else:
        print("\nℹ️  Kein Push gesendet (kein ntfy-Thema in der Einrichtung gesetzt).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
