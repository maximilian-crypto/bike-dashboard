"""Der Sync-Workflow muss jede Einstellung kennen, die der gehostete Pfad liest.

Befund 07./15.11.2026: Der Report-Schritt baute in der Warteschleife den
Tagesplan neu, kannte aber INTERVALS_* und ORS_API_KEY nicht — die Zwift-
Zustellung wurde dann „übersprungen". Seitdem stehen alle Werte EINMAL auf
Job-Ebene, und dieser Test hält das fest (CLAUDE.md 8b, Punkt 4).
"""

from __future__ import annotations

import re
from pathlib import Path

from bikedash import config

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "sync.yml"

# Werte, die in Actions bewusst nicht gebraucht werden (nur Dashboard/lokal).
NOT_IN_ACTIONS = {"ANTHROPIC_API_KEY", "COACH_MODEL", "SERVER_PORT", "ORS_PROFILE"}


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job_env(text: str) -> set[str]:
    m = re.search(r"\n    env:\n((?:      .*\n|\s*\n)+?)    steps:", text)
    assert m, "sync.yml braucht einen env:-Block auf Job-Ebene"
    return set(re.findall(r"^      ([A-Z_]+):", m.group(1), flags=re.M))


def test_every_setting_reaches_the_job():
    env = _job_env(_text())
    wanted = (set(config._ENV_MAP) - NOT_IN_ACTIONS) | {"DATABASE_URL"}
    assert wanted - env == set(), f"fehlt in sync.yml: {sorted(wanted - env)}"


def test_job_env_reads_matching_secret():
    for name in _job_env(_text()):
        assert re.search(rf"^      {name}: \${{{{ secrets\.{name} }}}}", _text(), flags=re.M), name


def test_no_step_has_its_own_env_list():
    # Eigene Listen je Schritt laufen auseinander — genau das war der Fehler.
    assert not re.search(r"^        env:", _text(), flags=re.M)
