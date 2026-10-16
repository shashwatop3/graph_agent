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

from typing import Protocol

from ..adapters import ringfire
from ..core.compiler import compile_context
from ..core.store import Store
from ..core.tools import Toolbox
from .pipeline import Exposure, Pipeline


class Backend(Protocol):
    name: str
    exposures: list[Exposure]

    def start(self, game) -> None: ...

    def message(self, message) -> None: ...

    def day(self, game, result) -> None: ...

    def context(self, number: int, day: int, budget: int) -> str: ...

    def toolbox(self, number: int, send, execute): ...


class GraphBackend:
    """Agents remember through the knowledge graph in `store`, and corrections propagate."""

    def __init__(self, store: Store, name: str = "graph"):
        self.store = store
        self.name = name
        self.pipeline = Pipeline(store)
        self.n_agents = 0

    @property
    def exposures(self) -> list[Exposure]:
        return self.pipeline.exposures

    def start(self, game) -> None:
        self.n_agents = game.sim.world.config.n_agents
        self.pipeline.start(game)
        self.pipeline.publish_start_fires(game)

    def message(self, message) -> None:
        self.pipeline.message(message)

    def day(self, game, result) -> None:
        self.pipeline.day(game, result)

    def context(self, number: int, day: int, budget: int) -> str:
        viewer = ringfire.agent_id(number)
        return compile_context(
            self.store,
            viewer,
            max(0, day - 1),  # what changed or arrived since yesterday
            role_card=ringfire.role_card(viewer, self.n_agents),
            templates=ringfire.TEMPLATES,
            budget=budget,
        )

    def toolbox(self, number: int, send, execute) -> Toolbox:
        def transport(sender_id: str, receiver_id: str, belief) -> str:
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

        return Toolbox(
            self.store,
            ringfire.agent_id(number),
            ringfire.PREDICATES,
            ringfire.TEMPLATES,
            self.pipeline.ids,
            transport=transport,
            executor=execute,
        )
