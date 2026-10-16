"""A full game with language-model agents (or a stand-in for them), on any memory backend.

Each day, every agent in turn gets its context from the backend, takes its turn (the model calls
tools), and then the day is played: fire spreads, evidence is published, the backend updates. Order
is fixed (agent 0, 1, 2, ...) and each turn's tool calls run in the order the model gave them, so
the same model answers give the same game.

Messages sent during the turns are held until every agent has had its turn, then delivered together
(before the fire is played). So nobody reads a message on the day it was sent by an agent with a
lower number: the order of the turns decides nothing about who hears what first. The scripted sends
at the start of the day come before every turn, so they are delivered at once.

Imposters never use the model. Their lies are scripted (the scenario's "sends") and their other
behaviour is a plain rule: pass on whatever they receive to every neighbour not already on its
route. The network then applies their corruption (a shifted day, or silence).
"""

from dataclasses import dataclass, field

from ..core.model import Action
from ..sim.comms import Claim, LinkError, Message
from ..sim.fire import fields_saved
from ..sim.game import DayResult, Game
from ..sim.scenario import Scenario, SendSpec, build_game
from .agent import TurnResult, run_turn
from .llm import ModelClient
from .pipeline import Exposure
from .types import AfterDay, Backend


@dataclass
class GameResult:
    game: Game
    exposures: list[Exposure]
    # (day, agent, result)
    turns: list[tuple[int, str, TurnResult]] = field(
        default_factory=list[tuple[int, str, TurnResult]]
    )
    # the engine's result for every day played
    days: list[DayResult] = field(default_factory=list[DayResult])

    @property
    def fields_saved(self) -> int:
        return fields_saved(self.game.sim)

    @property
    def tokens_in(self) -> int:
        return sum(t.tokens_in for _, _, t in self.turns)

    @property
    def tokens_out(self) -> int:
        return sum(t.tokens_out for _, _, t in self.turns)


def run_game(
    scenario: Scenario,
    backend: Backend,
    client: ModelClient,
    *,
    budget: int = 4000,
    max_days: int = 100,
    max_steps: int = 6,
    after_day: AfterDay | None = None,
) -> GameResult:
    """Play the scenario to the end. `after_day(game, backend, day)`, if given, is called after
    every day (the experiment harness uses it to ask the agents probe questions)."""
    game = build_game(scenario)
    backend.start(game)
    n_agents = game.sim.world.config.n_agents
    imposters = game.net.imposters
    water_today: set[int] = set()
    relayed: set[tuple[int, int, int]] = set()
    # the latest message each agent received about a claim, so it can pass it on with its route
    received: dict[tuple[int, int, int], Message] = {}

    scripted_sends: dict[int, list[SendSpec]] = {}
    for scripted in scenario.get("sends", []):
        scripted_sends.setdefault(scripted["day"], []).append(scripted)

    # ---- what the tools do in the game -----------------------------------------------------

    held: list[
        Message
    ] = []  # messages sent during this day's turns, delivered once they are all over
    holding = False

    def deliver(message: Message) -> None:
        if holding:
            held.append(message)
            return
        received[(message.receiver, message.claim.field_id, message.claim.day)] = message
        backend.message(message)

    def send(sender: int, receiver: int, field_number: int, day: int, relay: bool) -> str:
        """Tell `receiver` that fire reaches `field_number` on `day`. Relays keep their route."""
        relaying = received.get((sender, field_number, day)) if relay else None
        try:
            message = game.send(sender, receiver, Claim(field_number, day), relaying)
        except LinkError as error:
            raise ValueError(f"{error}; build a link first (act: link)") from error
        if message is not None:
            deliver(message)
        return f"sent to A{receiver}"

    def execute(action: Action) -> str:
        agent = int(action.owner[1:])
        if action.type == "water":
            if game.sim.water_left(agent) == 0:
                raise ValueError("you have no waterings left")
            if not game.sim.can_water_today(agent):
                raise ValueError("you watered yesterday, so you cannot water today")
            water_today.add(agent)
            return "you will water your fields today"
        if action.type == "link":
            if not action.target or not action.target.startswith("A"):
                raise ValueError("a link needs a target agent, such as A4")
            game.net.add_link(agent, int(action.target[1:]))
            return f"you are now linked to {action.target}"
        raise ValueError(f"unknown action type {action.type!r}; use 'water' or 'link'")

    boxes = {
        number: backend.toolbox(number, send, execute)
        for number in range(n_agents)
        if number not in imposters
    }

    def imposter_turn(number: int) -> None:
        for key, message in list(received.items()):
            if key[0] != number or key in relayed:
                continue
            relayed.add(key)
            for neighbour in game.net.neighbours(number):
                if neighbour == message.sender or neighbour in message.route:
                    continue
                sent = game.send(number, neighbour, message.claim, message)
                if sent is not None:
                    deliver(sent)

    # ---- the days --------------------------------------------------------------------------

    result = GameResult(game=game, exposures=backend.exposures)
    while not game.finished and game.day < max_days:
        day = game.day
        water_today.clear()
        for scripted in scripted_sends.get(day, []):  # the imposters' scripted lies
            message = game.send(
                scripted["sender"], scripted["receiver"], Claim(**scripted["claim"])
            )
            if message is not None:
                deliver(message)
        holding = True
        for number in range(n_agents):
            if number in imposters:
                imposter_turn(number)
                continue
            context = backend.context(number, day, budget) + f"\n\nIt is day {day}."
            boxes[number].now = day
            turn = run_turn(client, boxes[number], context, max_steps)
            result.turns.append((day, f"A{number}", turn))
        holding = False
        for message in held:
            deliver(message)
        held.clear()
        day_result = game.step(set(water_today))
        result.days.append(day_result)
        backend.day(game, day_result)
        if after_day is not None:
            after_day(game, backend, day)
    return result
