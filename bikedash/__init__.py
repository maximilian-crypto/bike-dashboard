"""bikedash — lokales Dashboard für Strava- + Whoop-Fahrraddaten."""

import time as _time

__version__ = "0.1.0"

# Ladezeitpunkt des Pakets. dashboard.py vergleicht ihn mit dem Dateistand, um
# nach einem Deploy veraltete Module im laufenden Prozess zu erkennen.
_LOADED_AT = _time.time()
