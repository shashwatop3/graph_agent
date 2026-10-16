"""Scripted games from JSON, so a run with a known outcome can be written down and replayed.

A scenario is a plain dict (usually loaded from a .json file). All keys except "world" are optional:

    {
      "seed": 0,
      "world": {"n_agents": 6, "fields_per_agent": 1, "n_hidden_edges": 0,
                "edges": [[0, 1, 1], [1, 2, 1]],          # optional: replace the generated edges
                "initial_fires": [[0, 1.0]]},             # optional: replace the generated fires
      "rules": {"burn_days": 3},                          # FireRules overrides
      "imposters": [{"agent": 2, "behaviour": "subtle_bias"}],
      "links": [[0, 3]],                                  # shortcut links present from the start
      "watering": {"2": [1]},                             # day -> agents that water
      "sends": [{"day": 0, "label": "a", "sender": 0, "receiver": 1,
                 "claim": {"field_id": 3, "day": 3}},
                {"day": 1, "sender": 1, "receiver": 2, "relays": "a",
                 "claim": {"field_id": 3, "day": 3}}]
    }
"""

import json
from dataclasses import replace
from pathlib import Path

from .comms import Behaviour, Claim, Imposter, Message
from .fire import FireRules
from .game import Game
from .world import Edge, World, WorldConfig, generate_world


def load_scenario(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def build_world(spec: dict, seed: int) -> World:
    spec = dict(spec)
    edges = spec.pop("edges", None)
    fires = spec.pop("initial_fires", None)
    for key in ("spread_weight", "hidden_weight"):
        if key in spec:
            spec[key] = tuple(spec[key])
    world = generate_world(WorldConfig(**spec), seed)
    if edges is not None:
        edges = tuple(
            Edge(e[0], e[1], e[2], hidden=bool(e[3]) if len(e) > 3 else False) for e in edges
        )
        world = replace(world, edges=edges)
    if fires is not None:
        world = replace(world, initial_fires=tuple((f, float(i)) for f, i in fires))
    return world


def build_game(scenario: dict) -> Game:
    """The game a scenario describes: world, rules, imposters and any starting shortcut links."""
    game = Game(
        build_world(scenario["world"], scenario.get("seed", 0)),
        FireRules(**scenario.get("rules", {})),
        tuple(
            Imposter(i["agent"], Behaviour(i["behaviour"])) for i in scenario.get("imposters", [])
        ),
    )
    for a, b in scenario.get("links", []):
        game.net.add_link(a, b)
    return game


def run_scenario(
    scenario: dict,
    max_days: int = 1000,
    on_start=None,  # called once with the game before day 0
    on_send=None,  # called with (game, message) for every message that was sent
    on_day=None,  # called with (game, day result) after every day is played
) -> Game:
    """Play the scenario to the end and return the finished game.

    The three optional callbacks let something outside the simulator (the harness, feeding an
    adapter and a store) watch the game as it happens, without the simulator knowing about it.
    """
    game = build_game(scenario)
    watering = {int(day): agents for day, agents in scenario.get("watering", {}).items()}
    sends: dict[int, list[dict]] = {}
    for s in scenario.get("sends", []):
        sends.setdefault(s["day"], []).append(s)
    last_event = max([*sends, *watering], default=0)

    if on_start:
        on_start(game)
    sent: dict[str, Message | None] = {}
    while not (game.finished and game.day > last_event):
        if game.day >= max_days:
            raise RuntimeError(f"scenario still running after {max_days} days")
        for s in sends.get(game.day, []):
            relaying = sent[s["relays"]] if "relays" in s else None
            if "relays" in s and relaying is None:
                raise ValueError(f"cannot relay {s['relays']!r}: it was swallowed by an imposter")
            message = game.send(s["sender"], s["receiver"], Claim(**s["claim"]), relaying)
            if "label" in s:
                sent[s["label"]] = message
            if message is not None and on_send:
                on_send(game, message)
        result = game.step(watering.get(game.day, ()))
        if on_day:
            on_day(game, result)
    return game
