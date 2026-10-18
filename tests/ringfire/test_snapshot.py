"""The fire sim page's playback (viewer/console/src/setups/fireDays.json) is what a run gives."""

import json
from pathlib import Path

from graph_agent.packs.ringfire.snapshot import fire_days

DRAWN = Path(__file__).parents[2] / "viewer/console/src/setups/fireDays.json"


def test_the_setup_pages_playback_is_what_a_run_gives():
    """Made by `python -m graph_agent.packs.ringfire.snapshot`."""
    assert json.loads(DRAWN.read_text()) == json.loads(json.dumps(fire_days()))


def test_the_playback_shows_the_lie_and_its_catch():
    days = fire_days()["days"]
    assert any(s["lie"] for s in days[1]["sends"])  # day 1: the liars' claim goes round
    assert {agent for _, agent in days[2]["caught"]} == {"A2", "A4"}  # day 2: both caught
