"""Erzeugt den Morgen-Report und schickt ihn (falls konfiguriert) ans Handy.

Benutzung:
    python send_report.py            # bauen + sofort pushen (manuell / Test)
    python send_report.py --print    # nur anzeigen, nicht senden
    python send_report.py --if-due   # nur senden, wenn fällig (Sync-Workflow):
                                     # heutige Whoop-Recovery da oder Frist erreicht,
                                     # und heute noch nicht gesendet
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

    if "--if-due" in sys.argv:
        status, why = report.send_if_due(cfg)
        print(f"Morgen-Report: {status} ({why})")
        return 0

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
