"""The fire game as the console's setup page animates it: the first days of the free stand-in game
(the console's default settings, seed 1), day by day.

    uv run python -m graph_agent.packs.ringfire.snapshot > viewer/console/src/setups/fireDays.json

Each day: every field's fire strength that night, the fields watered and put out, each warning
sent (who to whom, whether it carries the liars' claim, whether the receiver believed it), who
caught whom lying, who was offline, and the links. tests/ringfire/test_snapshot.py checks the
committed file is what a run gives.
"""

import json
from typing import Any

from graph_agent.frame.events import EventLog
from graph_agent.stores.memory import MemoryStore

from .console import RINGFIRE

DAYS = 10


def fire_days(days: int = DAYS) -> dict[str, Any]:
    team = RINGFIRE.team("ringfire", {})
    log = EventLog()
    session = RINGFIRE.start(team, RINGFIRE.stand_in(team), MemoryStore(), log, {})
    runtime = session.runtime
    runtime.start()
    try:
        for _ in range(days):
            runtime.step()
    finally:
        runtime.close()
    liars = sorted(n.id for n in team.nodes if n.type == "scripted")
    out: list[dict[str, Any]] = []
    offline: dict[str, int] = {}
    for day in range(days):
        here = [e for e in log.events if e.tick == day]
        world = next(e.data for e in here if e.kind == "world")
        for e in here:
            if e.kind == "offline":
                offline[str(e.data["agent"])] = int(e.data["until"])
        sends: dict[tuple[str, str], dict[str, Any]] = {}
        for e in here:
            if e.kind != "message":
                continue
            route = [str(a) for a in e.data["route"]]
            key = (str(e.data["sender"]), str(e.data["receiver"]))
            lie = route[0] in liars
            seen = sends.setdefault(
                key, {"from": key[0], "to": key[1], "lie": False, "believed": False}
            )
            seen["lie"] = seen["lie"] or lie
            seen["believed"] = seen["believed"] or bool(e.data["believed"])
        out.append(
            {
                "day": day,
                "strength": {str(f): s for f, s in world["strength"]},
                "watered": world["watered"],
                "put_out": world["extinguished"],
                "sends": list(sends.values()),
                "caught": sorted(
                    {
                        (str(e.data["viewer"]), str(e.data["agent"]))
                        for e in here
                        if e.kind == "exposure"
                    }
                ),
                "offline": sorted(a for a, until in offline.items() if until > day),
                "links": sorted(sorted(link) for link in world["links"]),
            }
        )
    return {
        "agents": len([n for n in team.nodes if n.id.startswith("A")]),
        "liars": liars,
        "days": out,
    }


if __name__ == "__main__":
    print(json.dumps(fire_days(), indent=1))
