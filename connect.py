"""Strava und/oder Whoop verbinden (einmaliger OAuth-Login).

Benutzung:
    python connect.py            # beide verbinden
    python connect.py strava     # nur Strava
    python connect.py whoop      # nur Whoop
"""

from __future__ import annotations

import sys

from bikedash import config, strava, whoop


def main() -> int:
    try:
        cfg = config.load_config()
    except config.ConfigError as exc:
        print(f"\n⚠️  {exc}\n")
        return 1

    which = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    if which not in {"strava", "whoop", "both"}:
        print("Benutzung: python connect.py [strava|whoop]")
        return 2

    try:
        if which in {"strava", "both"}:
            strava.connect(cfg)
        if which in {"whoop", "both"}:
            whoop.connect(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ Verbindung fehlgeschlagen: {exc}\n")
        return 1

    print("\nFertig. Jetzt Daten holen mit:  python sync.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
