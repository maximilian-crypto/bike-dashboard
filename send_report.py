"""Erzeugt den Morgen-Report und schickt ihn (falls konfiguriert) ans Handy.

Benutzung:
    python send_report.py            # bauen + sofort pushen (manuell / Test)
    python send_report.py --print    # nur anzeigen, nicht senden
    python send_report.py --if-due   # nur senden, wenn fällig (Sync-Workflow):
                                     # heutige Whoop-Recovery da oder Frist erreicht,
                                     # und heute noch nicht gesendet
    python send_report.py --if-due --wait  # wie --if-due, aber wartet der Report
                                     # noch auf die Recovery, fasst derselbe Lauf
                                     # alle 10 min nach (bis zur Frist 10:00)
    python send_report.py --weekly-if-due  # Wochenrückblick, wenn fällig
                                     # (So ab 18 Uhr, Mo bis 12 Uhr nachholen)
    python send_report.py --weekly   # Wochenrückblick der laufenden Woche zeigen
                                     # (mit --print nur anzeigen)
"""

from __future__ import annotations

import sys

import datetime as dt

from bikedash import config, report, weekly


def _refresh(cfg) -> None:
    """Whoop nachladen und den Tagesplan (inkl. Zwift) neu bauen — die
    Recovery kann die Empfehlung ändern."""
    import build_today
    from bikedash import whoop

    res = whoop.sync(cfg)
    print(f"  Nachgeladen: {res['recovery']} Recovery, {res.get('sleep', 0)} Schlafdaten.")
    build_today.build()


def main() -> int:
    try:
        cfg = config.load_config()
    except config.ConfigError as exc:
        print(f"⚠️  {exc}")
        return 1

    if "--if-due" in sys.argv or "--weekly-if-due" in sys.argv:
        if "--if-due" in sys.argv and "--wait" in sys.argv:
            status, why = report.send_waiting(cfg, lambda: _refresh(cfg))
            print(f"Morgen-Report: {status} ({why})")
        elif "--if-due" in sys.argv:
            status, why = report.send_if_due(cfg)
            print(f"Morgen-Report: {status} ({why})")
        if "--weekly-if-due" in sys.argv:
            status, why = weekly.send_if_due(cfg)
            print(f"Wochenrückblick: {status} ({why})")
        return 0

    if "--weekly" in sys.argv:
        today = dt.date.today()
        title, message = weekly.build_text(today - dt.timedelta(days=today.weekday()))
    else:
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
