"""Scripted games from JSON, so a run with a known outcome can be written down and replayed.

A scenario is a plain dict (usually loaded from a .json file). All keys except "world" are optional:

    {
      "seed": 0,
      "world": {"n_agents": 6, "fields_per_agent": 1, "n_hidden_edges": 0,
                "edges": [[0, 1, 1], [1, 2, 1]],          # optional: replace the generated edges
                "initial_fires": [[0, 1.0]]},             # optional: replace the generated fires
      "rules": {"burn_days": 3},                          # FireRules overrides
      "evidence": "public",                               # or "private": see Game
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
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from .comms import Behaviour, Claim, Imposter, Message
from .fire import FireRules
from .game import DayResult, Game
from .world import Edge, World, WorldConfig, generate_world


class WorldSpec(TypedDict, total=False):
    n_agents: int
    fields_per_agent: int
    spread_weight: list[int]
    n_hidden_edges: int
    hidden_weight: list[int]
    min_hidden_span: int
    n_initial_fires: int
    initial_intensity: float
    edges: list[list[int]]  # [src, dst, weight] or [src, dst, weight, hidden]
    initial_fires: list[list[float]]  # [field, intensity]
    horizon: int  # days the game lasts
    random_ignition_chance: float  # chance each day that one random field ignites


class RulesSpec(TypedDict, total=False):
    burn_days: int
    growth_if_unwatered: float
    min_intensity: float
    max_intensity: float
    water_per_agent: int | None
    water_cooldown: int
    regrow_days: int | None
    waste_penalty: float
    dynamics: Literal["binary", "linear"]
    step: float
    lost_after: int
    arrive: Literal["step", "source"]
    relight: bool


class ImposterSpec(TypedDict):
    agent: int
    behaviour: str


class ClaimSpec(TypedDict):
    field_id: int
    day: int


class SendSpec(TypedDict):
    day: int
    sender: int
    receiver: int
    claim: ClaimSpec
    label: NotRequired[str]
    relays: NotRequired[str]


class Scenario(TypedDict):
    world: WorldSpec
    seed: NotRequired[int]
    rules: NotRequired[RulesSpec]
    evidence: NotRequired[str]
    imposters: NotRequired[list[ImposterSpec]]
    links: NotRequired[list[list[int]]]
    watering: NotRequired[dict[str, list[int]]]
    sends: NotRequired[list[SendSpec]]


def load_scenario(path: str | Path) -> Scenario:
    return json.loads(Path(path).read_text())


def build_world(spec: WorldSpec, seed: int) -> World:
    unknown = spec.keys() - WorldSpec.__annotations__.keys()
    if unknown:
        raise TypeError(f"unknown world setting(s): {', '.join(sorted(unknown))}")
    defaults = WorldConfig()
    spread = spec.get("spread_weight")
    hidden = spec.get("hidden_weight")
    config = WorldConfig(
        n_agents=spec.get("n_agents", defaults.n_agents),
        fields_per_agent=spec.get("fields_per_agent", defaults.fields_per_agent),
        spread_weight=(spread[0], spread[1]) if spread else defaults.spread_weight,
        n_hidden_edges=spec.get("n_hidden_edges", defaults.n_hidden_edges),
        hidden_weight=(hidden[0], hidden[1]) if hidden else defaults.hidden_weight,
        min_hidden_span=spec.get("min_hidden_span", defaults.min_hidden_span),
        n_initial_fires=spec.get("n_initial_fires", defaults.n_initial_fires),
        initial_intensity=spec.get("initial_intensity", defaults.initial_intensity),
        horizon=spec.get("horizon", defaults.horizon),
        random_ignition_chance=spec.get("random_ignition_chance", defaults.random_ignition_chance),
    )
    world = generate_world(config, seed)
    edges = spec.get("edges")
    if edges is not None:
        world = replace(
            world,
            edges=tuple(
                Edge(e[0], e[1], e[2], hidden=bool(e[3]) if len(e) > 3 else False) for e in edges
            ),
        )
    fires = spec.get("initial_fires")
    if fires is not None:
        world = replace(world, initial_fires=tuple((int(f), float(i)) for f, i in fires))
    return world


def build_game(scenario: Scenario) -> Game:
    """The game a scenario describes: world, rules, imposters and any starting shortcut links."""
    game = Game(
        build_world(scenario["world"], scenario.get("seed", 0)),
        FireRules(**scenario.get("rules", {})),
        tuple(
            Imposter(i["agent"], Behaviour(i["behaviour"])) for i in scenario.get("imposters", [])
        ),
        private_evidence=scenario.get("evidence", "public") == "private",
    )
    for a, b in scenario.get("links", []):
        game.net.add_link(a, b)
    return game


def run_scenario(
    scenario: Scenario,
    max_days: int = 1000,
    on_start: Callable[[Game], None] | None = None,  # called once with the game before day 0
    on_send: Callable[[Game, Message], None] | None = None,  # for every message that was sent
    on_day: Callable[[Game, DayResult], None] | None = None,  # after every day is played
) -> Game:
    """Play the scenario to the end and return the finished game.

    The three optional callbacks let something outside the simulator (the harness, feeding an
    adapter and a store) watch the game as it happens, without the simulator knowing about it.
    """
    game = build_game(scenario)
    watering = {int(day): agents for day, agents in scenario.get("watering", {}).items()}
    sends: dict[int, list[SendSpec]] = {}
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
