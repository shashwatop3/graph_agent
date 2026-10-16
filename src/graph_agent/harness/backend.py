"""What a "memory system" has to provide so the same game loop can run on any of them.

The game loop (game.py) does not know whether agents remember through the knowledge graph or
through a chat log. It asks the backend to:

  start(game)           set up for a new game
  message(message)      an agent received a message
  day(game, result)     a day was played (evidence was published)
  context(...)          the text an agent reads this turn
  toolbox(...)          the tools an agent may call this turn

The graph setups (FalkorDB, Postgres, in-memory) are `GraphBackend`; the comparison systems are in
baselines.py. Everything outside the backend (the simulator, the imposters, the model, the budget)
is identical, which is what makes the comparison fair.
"""

from functools import partial

from ..adapters import ringfire
from ..core.compiler import compile_context
from ..core.model import Belief
from ..core.store import Store
from ..core.tools import Toolbox
from ..sim.comms import Message
from ..sim.game import DayResult, Game
from .pipeline import Exposure, Pipeline
from .types import ExecuteFn, SendFn


def _transport(send: SendFn, sender_id: str, receiver_id: str, belief: Belief) -> str:
    """Hand a belief to the game's `send`, translating ids ("A3") and the belief into plain ints."""
    if belief.predicate != ringfire.ARRIVAL:
        raise ValueError("only beliefs about when fire arrives can be sent")
    # a belief you were told is passed on along its route; anything else you report
    return send(
        int(sender_id[1:]),
        int(receiver_id[1:]),
        int(belief.subject[1:]),
        int(belief.value),
        belief.origin == "told",
    )


class GraphBackend:
    """Agents remember through the knowledge graph in `store`, and corrections propagate."""

    def __init__(self, store: Store, name: str = "graph"):
        self.store = store
        self.name = name
        self.pipeline = Pipeline(store)
        self.n_agents = 0
        self.fields: dict[int, tuple[int, ...]] = {}
        self.water: int | None = None  # waterings per agent, from the game's rules

    @property
    def exposures(self) -> list[Exposure]:
        return self.pipeline.exposures

    def start(self, game: Game) -> None:
        world = game.sim.world
        self.n_agents = world.config.n_agents
        self.fields = {n: tuple(world.fields_of(n)) for n in range(self.n_agents)}
        self.water = game.sim.rules.water_per_agent
        self.pipeline.start(game)
        self.pipeline.publish_start_fires(game)

    def message(self, message: Message) -> None:
        self.pipeline.message(message)

    def day(self, game: Game, result: DayResult) -> None:
        self.pipeline.day(game, result)

    def context(self, number: int, day: int, budget: int) -> str:
        viewer = ringfire.agent_id(number)
        return compile_context(
            self.store,
            viewer,
            max(0, day - 1),  # what changed or arrived since yesterday
            role_card=ringfire.role_card(
                viewer, self.n_agents, self.fields.get(number, ()), self.water
            ),
            templates=ringfire.TEMPLATES,
            budget=budget,
        )

    def toolbox(self, number: int, send: SendFn, execute: ExecuteFn) -> Toolbox:
        return Toolbox(
            self.store,
            ringfire.agent_id(number),
            ringfire.PREDICATES,
            ringfire.TEMPLATES,
            self.pipeline.ids,
            transport=partial(_transport, send),
            executor=execute,
        )
