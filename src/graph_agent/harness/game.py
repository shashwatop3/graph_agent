"""A full game with language-model agents (or a stand-in for them).

Each day, every agent in turn gets its context compiled from the store, takes its turn (the model
calls tools), and then the day is played: fire spreads, evidence is published, and the adapter's
rule decides whom each agent stops trusting. Order is fixed (agent 0, 1, 2, ...) and each turn's
tool calls run in the order the model gave them, so the same model answers give the same game.

Imposters never use the model. Their lies are scripted (the scenario's "sends") and their other
behaviour is a plain rule: pass on whatever they receive to every neighbour not already on its
route. The network then applies their corruption (a shifted day, or silence).
"""

from dataclasses import dataclass, field

from ..adapters import ringfire
from ..core.compiler import compile_context
from ..core.store import Store
from ..core.tools import Toolbox
from ..sim.comms import Claim, LinkError
from ..sim.fire import fields_saved
from ..sim.scenario import build_game
from .agent import TurnResult, run_turn
from .llm import ModelClient
from .pipeline import Exposure, Pipeline


@dataclass
class GameResult:
    game: object
    exposures: list[Exposure]
    turns: list[tuple[int, str, TurnResult]] = field(default_factory=list)  # (day, agent, result)

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
    scenario: dict,
    store: Store,
    client: ModelClient,
    *,
    budget: int = 4000,
    max_days: int = 100,
    max_steps: int = 6,
) -> GameResult:
    game = build_game(scenario)
    pipeline = Pipeline(store)
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    n_agents = game.sim.world.config.n_agents
    imposters = game.net.imposters
    water_today: set[int] = set()
    relayed: set[tuple] = set()

    scripted_sends: dict[int, list[dict]] = {}
    for send in scenario.get("sends", []):
        scripted_sends.setdefault(send["day"], []).append(send)

    # ---- what the tools do in the game -----------------------------------------------------

    def transport(sender_id: str, receiver_id: str, belief) -> str:
        if belief.predicate != ringfire.ARRIVAL:
            raise ValueError("only beliefs about when fire arrives can be sent")
        field_number, day = int(belief.subject[1:]), int(belief.value)
        # a belief you were told is passed on along its route; anything else you report yourself
        relaying = pipeline.received.get((sender_id, field_number, day))
        if belief.origin != "told":
            relaying = None
        try:
            message = game.send(
                int(sender_id[1:]), int(receiver_id[1:]), Claim(field_number, day), relaying
            )
        except LinkError as error:
            raise ValueError(f"{error}; build a link first (act: link)") from error
        if message is not None:
            pipeline.message(message)
        return f"sent to {receiver_id}"

    def executor(action) -> str:
        agent = int(action.owner[1:])
        if action.type == "water":
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
        number: Toolbox(
            store,
            ringfire.agent_id(number),
            ringfire.PREDICATES,
            ringfire.TEMPLATES,
            pipeline.ids,
            transport=transport,
            executor=executor,
        )
        for number in range(n_agents)
        if number not in imposters
    }

    def imposter_turn(number: int) -> None:
        viewer = ringfire.agent_id(number)
        for key, message in list(pipeline.received.items()):
            if key[0] != viewer or key in relayed:
                continue
            relayed.add(key)
            for neighbour in game.net.neighbours(number):
                if neighbour == message.sender or neighbour in message.route:
                    continue
                sent = game.send(number, neighbour, message.claim, message)
                if sent is not None:
                    pipeline.message(sent)

    # ---- the days --------------------------------------------------------------------------

    result = GameResult(game=game, exposures=pipeline.exposures)
    while not game.finished and game.day < max_days:
        day = game.day
        water_today.clear()
        for send in scripted_sends.get(day, []):  # the imposters' scripted lies
            message = game.send(send["sender"], send["receiver"], Claim(**send["claim"]))
            if message is not None:
                pipeline.message(message)
        for number in range(n_agents):
            if number in imposters:
                imposter_turn(number)
                continue
            viewer = ringfire.agent_id(number)
            context = (
                compile_context(
                    store,
                    viewer,
                    max(0, day - 1),
                    role_card=ringfire.role_card(viewer, n_agents),
                    templates=ringfire.TEMPLATES,
                    budget=budget,
                )
                + f"\n\nIt is day {day}."
            )
            boxes[number].now = day
            result.turns.append((day, viewer, run_turn(client, boxes[number], context, max_steps)))
        pipeline.day(game, game.step(set(water_today)))
    return result
