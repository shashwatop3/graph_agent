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
from ..core.compiler import compile_context, estimate_tokens
from ..core.model import Belief
from ..core.store import Store
from ..core.tools import Toolbox
from ..sim.comms import Message
from ..sim.game import DayResult, Game
from .pipeline import (
    CardRules,
    Exposure,
    Pipeline,
    card_rules,
    hidden_map_line,
    map_line,
    outlook,
    role_card,
)
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
    """Agents remember through the knowledge graph in `store`, and corrections propagate.

    Besides what the store compiles, an agent is shown the map (the same lines the baselines show)
    and, under "Worth telling", the beliefs its neighbours have not had from it yet, each with the
    send call that passes it on. Without those, agents reading only their own memory hardly ever
    sent anything: knowing a fire is coming is useless to the one agent who cannot act on it.
    """

    MAX_HINTS = 8

    def __init__(self, store: Store, name: str = "graph", warn_quorum: int | None = None):
        self.store = store
        self.name = name
        self.pipeline = Pipeline(store, warn_quorum=warn_quorum)
        self.edges: list[tuple[int, int, int]] = []  # the paths agents know: (src, dst, days)
        self.n_agents = 0
        self.fields: dict[int, tuple[int, ...]] = {}
        self.rules: CardRules | None = None  # what the role card says about the rules
        self.game: Game | None = None
        self.map_lines: list[str] = []
        self.sent: set[tuple[str, str, str, object]] = set()  # (from, to, field, day) passed on

    @property
    def exposures(self) -> list[Exposure]:
        return self.pipeline.exposures

    def start(self, game: Game) -> None:
        world = game.sim.world
        self.n_agents = world.config.n_agents
        self.fields = {n: tuple(world.fields_of(n)) for n in range(self.n_agents)}
        self.rules = card_rules(game)
        self.game = game
        self.map_lines = [
            map_line(e.src, e.dst, e.weight, world.owner(e.src))
            for e in world.edges
            if not e.hidden
        ]
        self.edges = [(e.src, e.dst, e.weight) for e in world.edges if not e.hidden]
        self.pipeline.start(game)
        self.pipeline.publish_start_fires(game)

    def message(self, message: Message) -> None:
        self.pipeline.message(message)

    def day(self, game: Game, result: DayResult) -> None:
        for edge in result.report.revealed_hidden:
            self.map_lines.append(hidden_map_line(edge.src, edge.dst, edge.weight))
            self.edges.append((edge.src, edge.dst, edge.weight))
        self.pipeline.day(game, result)

    def seen_fires(self, number: int) -> list[tuple[int, int]]:
        """(field, day) of every fire this agent has been shown: its live evidence beliefs."""
        viewer = ringfire.agent_id(number)
        return [
            (int(b.subject[1:]), b.value)
            for b in self.store.beliefs(viewer, predicate=ringfire.ARRIVAL)
            if b.origin == "observed"
            and b.status in ("active", "suspect")
            and isinstance(b.value, int)
        ]

    def known_liars(self, number: int) -> list[str]:
        """Whom this agent no longer trusts, and why: caught itself, or warned by others."""
        viewer = ringfire.agent_id(number)
        lines: dict[str, str] = {}
        for exposure in self.pipeline.exposures:
            if exposure.viewer == viewer and exposure.agent not in lines:
                lines[exposure.agent] = (
                    f"- {exposure.agent}: {exposure.reason} (day {exposure.day})"
                )
        return sorted(lines.values())

    def link_hints(self, number: int) -> list[str]:
        """For a ring neighbour this agent no longer trusts, the first trusted agent beyond it on
        that side: a link to it closes the ring of honest agents around the liar."""
        if self.game is None:
            return []
        viewer = ringfire.agent_id(number)
        distrusted = {agent for v, agent in self.pipeline.exposed if v == viewer}
        hints: list[str] = []
        for step in (-1, 1):
            skipped: list[str] = []
            other = (number + step) % self.n_agents
            while ringfire.agent_id(other) in distrusted and other != number:
                skipped.append(ringfire.agent_id(other))
                other = (other + step) % self.n_agents
            if skipped and other != number and not self.game.net.linked(number, other):
                hints.append(
                    f'- act(type="link", target="A{other}"): route around '
                    f"{', '.join(skipped)}, whom you no longer trust"
                )
        return hints

    def worth_telling(self, number: int, day: int) -> list[str]:
        """Live beliefs that are still current (about yesterday or later) that a neighbour has not
        had from this agent and did not pass on itself: fires it saw, and claims it heard by two
        or more routes. A claim heard only once is not passed on: it may be a lie, and an honest
        agent repeating it spreads the lie further."""
        if self.game is None:
            return []
        viewer = ringfire.agent_id(number)
        distrusted = {agent for v, agent in self.pipeline.exposed if v == viewer}
        neighbours = [
            ringfire.agent_id(n)
            for n in self.game.net.neighbours(number)
            if ringfire.agent_id(n) not in distrusted
        ]
        beliefs = [
            b
            for b in self.store.beliefs(viewer, predicate=ringfire.ARRIVAL)
            if b.status in ("active", "suspect")
            and b.origin in ("observed", "told")
            and isinstance(b.value, int)
            and b.value >= day - 1
        ]
        beliefs.sort(key=lambda b: (-int(b.value), b.id))  # pyright: ignore[reportArgumentType]
        routes = {b.id: self.store.support_routes(viewer, b.id) for b in beliefs}
        # whoever passed a claim to this agent already has it, whichever belief it supports
        knows: dict[tuple[str, object], set[str]] = {}
        for belief in beliefs:
            agents = {a for r in routes[belief.id] for a in r}
            knows.setdefault((belief.subject, belief.value), set()).update(agents)
        hints: list[str] = []
        for belief in beliefs:
            if belief.origin == "told" and len(routes[belief.id]) < 2:
                continue
            on_route = knows[(belief.subject, belief.value)]
            for neighbour in neighbours:
                if neighbour in on_route:
                    continue
                if (viewer, neighbour, belief.subject, belief.value) in self.sent:
                    continue
                hints.append(
                    f'- send(to="{neighbour}", belief_id="{belief.id}"): fire reaches '
                    f"{belief.subject} on day {belief.value}"
                )
        return hints[: self.MAX_HINTS]

    def context(self, number: int, day: int, budget: int) -> str:
        viewer = ringfire.agent_id(number)
        extra = "## Map\n" + "\n".join(self.map_lines)
        own = self.fields.get(number, ())
        extra += "\n\n" + outlook(self.edges, self.seen_fires(number), own, day)
        liars = self.known_liars(number)
        if liars:
            extra += "\n\n## Known liars (you no longer trust them)\n" + "\n".join(liars)
        hints = self.link_hints(number) + self.worth_telling(number, day)
        if hints:
            extra += (
                "\n\n## Worth doing (route around liars; tell neighbours what they have not had "
                "from you)\n" + "\n".join(hints)
            )
        compiled = compile_context(
            self.store,
            viewer,
            max(0, day - 1),  # what changed or arrived since yesterday
            role_card=role_card(viewer, self.n_agents, self.fields.get(number, ()), self.rules),
            templates=ringfire.TEMPLATES,
            budget=max(0, budget - estimate_tokens(extra)),
        )
        return f"{compiled}\n\n{extra}"

    def _send(self, send: SendFn, sender_id: str, receiver_id: str, belief: Belief) -> str:
        reply = _transport(send, sender_id, receiver_id, belief)
        self.sent.add((sender_id, receiver_id, belief.subject, belief.value))
        return reply

    def toolbox(self, number: int, send: SendFn, execute: ExecuteFn) -> Toolbox:
        return Toolbox(
            self.store,
            ringfire.agent_id(number),
            self.pipeline.predicates,
            ringfire.TEMPLATES,
            self.pipeline.ids,
            transport=partial(self._send, send),
            executor=execute,
        )
