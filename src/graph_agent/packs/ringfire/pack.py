"""Ring Fire on the frame: the game as a team of nodes.

    world      the fire simulator, as an environment node: it plays each day, publishes the fire
               reports as items (to each field's audience), and carries messages over the ring
    A0 .. An   one node per segment keeper: an agent node (model), or a scripted imposter
    checker    refutes told claims that evidence contradicts, and claims whose day passed
    warner     group correction, with a quorum (only in the "-group" systems)

The rules that used to be glue (harness/pipeline.py and harness/backend.py) are the generic
checker and warner nodes plus the hooks of `RingFirePack`: what a refutation says, when a claim
expires, when a first-hand claim is refuted, and what an agent reads besides its compiled memory
(the map, the fire outlook, known liars and what is worth passing on).

A frame run gives the same game as `harness.game.run_game` with `GraphBackend`: the same contexts,
tool calls, messages, exposures and score (tests/test_frame_ringfire.py checks it), so the two
share a model cache.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from graph_agent.core.compiler import compile_context, estimate_tokens
from graph_agent.core.model import Action, Belief
from graph_agent.core.store import Store, told_sources
from graph_agent.core.tools import Toolbox
from graph_agent.frame.nodes import WarnerNode
from graph_agent.frame.policies import blamed_on_route
from graph_agent.frame.runtime import Blame, Delivery, Item, Node, Outgoing, Runtime, Stage
from graph_agent.frame.spec import LinkSpec, NodeSpec, Settings, TeamSpec, Trigger
from graph_agent.harness.agent import TurnResult
from graph_agent.harness.llm import ModelClient
from graph_agent.harness.trace import NO_TRACE, Trace

from . import adapter as ringfire
from .benchmark.game import GameResult
from .benchmark.pipeline import (
    CardRules,
    Exposure,
    card_rules,
    episode,
    hidden_map_line,
    map_line,
    outlook,
    role_card,
)
from .benchmark.types import ExecuteFn, SendFn
from .sim.comms import Behaviour, Claim, LinkError, Message
from .sim.fire import fields_saved
from .sim.game import DayResult, Game
from .sim.saboteur import planned_lies
from .sim.scenario import Scenario, SendSpec, build_game

MAX_HINTS = 8


def number(node_id: str) -> int:
    return int(node_id[1:])


# ---- the team -----------------------------------------------------------------------------------


def team_for(
    scenario: Scenario,
    *,
    quorum: int | None = None,
    wake: bool = False,
    rerouter: bool = False,
    budget: int = 4000,
    max_steps: int = 6,
    blame: Literal["direct_teller", "whole_route", "first_hop"] = "direct_teller",
    repair: bool = False,
    trace_provenance: bool = False,
) -> TeamSpec:
    """The team a scenario describes, as a team file: the canvas shows exactly this.

    `blame`, `repair`: who an agent stops trusting when a claim proves false, and whether it trusts
    a relay again once the claim's maker is caught (see frame/policies.py).
    `wake`: agents run only when something new reached them (an item, a message, a change, an
    exposure) or a fire is due at one of their fields, instead of every day.
    `rerouter`: a code node routes around exposed liars by itself (builds the shortcut links).
    """
    game = build_game(scenario)
    n = game.sim.world.config.n_agents
    imposters = game.net.imposters
    triggers = (
        [
            Trigger(on="item"),
            Trigger(on="message"),
            Trigger(on="change"),
            Trigger(on="exposure"),
            Trigger(on="due", within=1, predicate=ringfire.ARRIVAL),
        ]
        if wake
        else [Trigger(on="tick")]
    )
    nodes = [
        NodeSpec(id="world", type="ringfire.world", label="Fire world", role="environment"),
    ]
    for a in range(n):
        if a in imposters:
            nodes.append(
                NodeSpec(
                    id=f"A{a}",
                    type="scripted",
                    label=f"A{a} (imposter)",
                    role=f"imposter: {imposters[a].value}",
                    config={"script": "imposter"},
                )
            )
        else:
            nodes.append(
                NodeSpec(
                    id=f"A{a}",
                    type="agent",
                    label=f"A{a}",
                    role="segment keeper",
                    triggers=triggers,
                )
            )
    nodes.append(NodeSpec(id="checker", type="checker", label="Evidence checker"))
    if quorum is not None:
        nodes.append(
            NodeSpec(id="warner", type="warner", label="Warnings", config={"quorum": quorum})
        )
    if rerouter:
        nodes.append(
            NodeSpec(id="rerouter", type="ringfire.rerouter", label="Rerouter", role="responder")
        )
    links: list[LinkSpec] = []
    for f in range(game.sim.world.n_fields):
        links.append(LinkSpec(kind="owns", src=f"A{game.sim.world.owner(f)}", dst=f"F{f}"))
    for link in sorted(game.net.links, key=sorted):
        a, b = sorted(link)
        links.append(LinkSpec(kind="talks_to", src=f"A{a}", dst=f"A{b}"))
    for a in range(n):
        links.append(LinkSpec(kind="feeds", src="world", dst=f"A{a}"))
    return TeamSpec(
        name=f"Ring Fire, {n} agents, seed {scenario.get('seed', 0)}",
        pack="ringfire",
        settings=Settings(
            mode="wake" if wake else "lockstep",
            budget=budget,
            max_steps=max_steps,
            quorum=quorum,
            blame=blame,
            repair=repair,
            trace_provenance=trace_provenance,
            extra={"scenario": scenario, "layout": "ring"},
        ),
        nodes=nodes,
        links=links,
    )


# ---- the ring as the team's network --------------------------------------------------------------


class RingNetwork:
    """The game's own network (it can grow: agents build links)."""

    def __init__(self, game: Game):
        self.game = game

    def neighbours(self, node: str) -> list[str]:
        if not node.startswith("A"):
            return []
        return [f"A{n}" for n in self.game.net.neighbours(number(node))]

    def linked(self, a: str, b: str) -> bool:
        return self.game.net.linked(number(a), number(b))

    def link(self, a: str, b: str) -> None:
        self.game.net.add_link(number(a), number(b))


# ---- the pack -----------------------------------------------------------------------------------


@dataclass
class RingFirePack:
    """Everything Ring Fire adds to the generic nodes, and the game state they share."""

    game: Game
    store: Store
    trace: Trace = NO_TRACE
    name: str = "ringfire"
    rt: Runtime | None = None
    templates: dict[str, str] = field(default_factory=lambda: dict(ringfire.TEMPLATES))
    shown: set[tuple[int, int, int]] = field(default_factory=set[tuple[int, int, int]])
    sent: set[tuple[str, str, str, object]] = field(
        default_factory=set[tuple[str, str, str, object]]
    )
    received: dict[tuple[int, int, int], Message] = field(
        default_factory=dict[tuple[int, int, int], Message]
    )
    water_today: set[int] = field(default_factory=set[int])
    decided: set[int] = field(default_factory=set[int])  # agents that chose water or wait today
    put_out: set[tuple[int, int]] = field(default_factory=set[tuple[int, int]])  # (field, day)
    edges: list[tuple[int, int, int]] = field(default_factory=list[tuple[int, int, int]])
    map_lines: list[str] = field(default_factory=list[str])
    days: list[DayResult] = field(default_factory=list[DayResult])
    start_fires_published: bool = False

    def __post_init__(self) -> None:
        self.predicates = ringfire.predicates(episode(self.game))
        world = self.game.sim.world
        self.n_agents = world.config.n_agents
        self.fields = {n: tuple(world.fields_of(n)) for n in range(self.n_agents)}
        self.rules: CardRules = card_rules(self.game)
        self.map_lines = [
            map_line(e.src, e.dst, e.weight, world.owner(e.src))
            for e in world.edges
            if not e.hidden
        ]
        self.edges = [(e.src, e.dst, e.weight) for e in world.edges if not e.hidden]

    @property
    def runtime(self) -> Runtime:
        assert self.rt is not None, "the pack is used before its runtime exists"
        return self.rt

    def fields_saved(self) -> int:
        return fields_saved(self.game.sim)

    @property
    def linear(self) -> bool:
        return self.game.sim.rules.dynamics == "linear"

    def score(self, runtime: Runtime) -> dict[str, Any]:
        """The running score the console shows."""
        liars = {f"A{a}" for a in self.game.net.imposters}
        honest = {n for n in runtime.nodes if n.startswith("A")} - liars
        pairs = runtime.exposed_pairs
        return {
            "fields_saved": self.fields_saved(),
            "fields": self.game.sim.world.n_fields,
            # honest agents wrongly distrusted by honest agents, now and at any time
            "honest_blamed": sum(1 for v, a in pairs if v in honest and a in honest),
            "honest_blamed_ever": sum(
                1 for e in runtime.exposures if e.viewer in honest and e.agent in honest
            ),
            "liars_caught": sum(1 for v, a in pairs if v in honest and a in liars),
            # waterings that met fire at one of the agent's fields, and waterings that did not
            "water_on_fire": sum(len(d.report.water_on_fire) for d in self.days),
            "water_wasted": sum(len(d.report.water_wasted) for d in self.days),
            "fields_lost": sum(1 for f in self.game.sim.fields if f.state.value == "burnt"),
            "restored": len(runtime.restored),
            "exposures": len(runtime.exposures),
            "turns": len(runtime.turns),
            "tokens_in": sum(t.tokens_in for _, _, t in runtime.turns),
        }

    def world_view(self) -> dict[str, Any]:
        """The fields, as the console's Ring Fire lens draws them."""
        game = self.game
        sim = game.sim
        return {
            "lens": "ringfire",
            "n_agents": sim.world.config.n_agents,
            "fields": [
                {
                    "id": f,
                    "owner": sim.world.owner(f),
                    "state": sim.fields[f].state.value,
                    "ignitions": list(sim.fields[f].ignitions),
                    "strength": sim.fields[f].intensity
                    if sim.fields[f].state.value == "burning"
                    else 0,
                }
                for f in range(sim.world.n_fields)
            ],
            "imposters": {str(a): b.value for a, b in game.net.imposters.items()},
            "water_left": {str(a): sim.water_left(a) for a in range(sim.world.config.n_agents)},
            "linear": self.linear,
            "max_strength": sim.rules.max_intensity,
        }

    # ---- recording ----------------------------------------------------------------------------

    def record_item(self, viewer: str, item: Item) -> list[Belief]:
        published = ringfire.EvidencePayload(
            day=item.payload["day"], field_id=item.payload["field"]
        )
        if item.payload.get("put_out"):
            published["put_out"] = True
        rt = self.runtime
        belief = ringfire.record_evidence(self.store, rt.ids, published, number(viewer))
        self.note_support(viewer, belief.id)
        return [belief]

    def note_support(self, viewer: str, belief_id: str) -> None:
        """Remember which observation supports the belief (the console's "why" reads it)."""
        observation = self.runtime.ids.last("O")
        if observation is not None:
            self.runtime.supports.setdefault((viewer, belief_id), []).append(observation)

    def show(self, viewer_number: int, field_number: int, day: int, put_out: bool = False) -> None:
        """Show one agent that fire reached a field (and, with `put_out`, that it went out at
        once because the owner watered): an item, routed to it alone."""
        self.shown.add((viewer_number, field_number, day))
        item = Item(
            id=f"E{field_number}-{day}-{viewer_number}",
            kind="fire_report",
            tick=day,
            source="world",
            about=[ringfire.field_id(field_number)],
            to=[f"A{viewer_number}"],
            payload={"day": day, "field": field_number, **({"put_out": True} if put_out else {})},
        )
        self.runtime.route(item, [f"A{viewer_number}"])

    # ---- the checker's and the warner's rules -------------------------------------------------

    def describe_refutation(self, belief: Belief, evidence: Belief) -> str:
        return f"told {belief.subject} on day {belief.value}; evidence says day {evidence.value}"

    def expired(
        self, viewer: str, tick: int, routes: dict[str, list[tuple[str, ...]]] | None = None
    ) -> list[Blame]:
        policy = self.runtime.settings.blame
        return ringfire.agents_with_expired_claims(
            self.store, viewer, tick, lambda route: blamed_on_route(route, policy), routes
        )

    def refuted(self, viewer: str, message: Outgoing, tick: int) -> str | None:
        """Why what the viewer has been shown proves a first-hand claim wrong, or None: it saw the
        fire on another day (within one fire's span), or the day has been played with no fire,
        which it would have seen, since being told about a field puts it in the audience."""
        sim_message: Message = message.payload
        field_number, claimed = sim_message.claim.field_id, sim_message.claim.day
        seen = sorted(d for n, f, d in self.shown if n == number(viewer) and f == field_number)
        if claimed in seen:
            return None
        window = episode(self.game)
        why: str | None = None
        for d in seen:
            if window is None or abs(d - claimed) <= window:
                why = f"evidence says day {d}"
                break
        else:
            why = "no fire came that day" if claimed <= tick else None
        return None if why is None else f"told F{field_number} on day {claimed}; {why}"

    # ---- acting -------------------------------------------------------------------------------

    def execute(self, action: Action) -> str:
        reply = self._do(action)
        self.trace.emit("action", type=action.type, target=action.target, reply=reply)
        return reply

    def _do(self, action: Action) -> str:
        agent = number(action.owner)
        sim = self.game.sim
        if action.type in ("water", "wait") and self.linear and agent in self.decided:
            raise ValueError("you already decided about water today; it is final")
        if action.type == "water":
            if sim.water_left(agent) == 0:
                raise ValueError("you have no waterings left")
            if not sim.can_water_today(agent):
                cooldown = sim.rules.water_cooldown
                if cooldown == 1:
                    raise ValueError("you watered yesterday, so you cannot water today")
                raise ValueError(
                    f"you watered less than {cooldown + 1} days ago, so you cannot water today"
                )
            self.water_today.add(agent)
            self.decided.add(agent)
            if self.linear:
                return self.what_happens(agent, watered=True)
            return "you will water your fields today"
        if action.type == "wait":
            self.water_today.discard(agent)
            self.decided.add(agent)
            if self.linear:
                return self.what_happens(agent, watered=False)
            return "you will not water today"
        if action.type == "link":
            if not action.target or not action.target.startswith("A"):
                raise ValueError("a link needs a target agent, such as A4")
            self.game.net.add_link(agent, number(action.target))
            return f"you are now linked to {action.target}"
        raise ValueError(f"unknown action type {action.type!r}; use 'water', 'wait' or 'link'")

    def what_happens(self, agent: int, watered: bool) -> str:
        """The result of today's choice at each of the agent's fields (linear fire): the fire at
        a field depends only on its owner's watering, so it is known before the day is played."""
        sim, lines = self.game.sim, list[str]()
        for f in self.fields.get(agent, ()):
            o = sim.outcome(f, watered)
            before, after = f"{o.before:g}", f"{o.after:g}"
            lines.append(
                {
                    "quiet": f"F{f}: no fire here today"
                    + ("; this watering is wasted" if watered else ""),
                    "arrived": f"F{f}: fire arrived today, burning at strength {after}",
                    "put_out": f"F{f}: fire arrived today and you put it out at once",
                    "grew": f"F{f}: fire grew from {before} to {after}",
                    "fell": f"F{f}: fire fell from {before} to {after}",
                    "out": f"F{f}: you put the fire out ({before} to 0)",
                    "held": f"F{f}: fire stays at full strength {after}",
                    "lost": f"F{f}: lost, it burned at full strength too long",
                }[o.event]
            )
        return "; ".join(lines) or "you have no fields"

    def fields_now(self, n: int) -> str:
        """Agent `n`'s own fields as they stand this morning (linear fire)."""
        sim, lines = self.game.sim, list[str]()
        cap, lost_after = sim.rules.max_intensity, sim.rules.lost_after
        for f in self.fields.get(n, ()):
            field_ = sim.fields[f]
            if field_.state.value == "burning":
                at_cap = (
                    f", {field_.days_at_cap} of {lost_after} days at full strength"
                    if field_.days_at_cap
                    else ""
                )
                lines.append(f"F{f}: burning at strength {field_.intensity:g} of {cap:g}{at_cap}")
            elif field_.state.value == "burnt":
                lines.append(f"F{f}: lost on day {field_.burnt_on}")
            else:
                lines.append(f"F{f}: not burning")
        return "## Your fields this morning\n" + "\n".join(lines)

    # ---- what an agent reads ------------------------------------------------------------------

    def seen_fires(self, n: int) -> list[tuple[int, int]]:
        viewer = ringfire.agent_id(n)
        return [
            (int(b.subject[1:]), b.value)
            for b in self.store.beliefs(viewer, predicate=ringfire.ARRIVAL)
            if b.origin == "observed"
            and b.status in ("active", "suspect")
            and isinstance(b.value, int)
        ]

    def known_liars(self, n: int) -> list[str]:
        viewer = ringfire.agent_id(n)
        lines: dict[str, str] = {}
        for exposure in self.runtime.exposures:
            if exposure.viewer == viewer and exposure.agent not in lines:
                lines[exposure.agent] = (
                    f"- {exposure.agent}: {exposure.reason} (day {exposure.day})"
                )
        return sorted(lines.values())

    def link_hints(self, n: int) -> list[str]:
        viewer = ringfire.agent_id(n)
        distrusted = self.runtime.distrusted(viewer)
        hints: list[str] = []
        for target, skipped in self.reroutes(n, distrusted):
            hints.append(
                f'- act(type="link", target="A{target}"): route around '
                f"{', '.join(skipped)}, whom you no longer trust"
            )
        return hints

    def reroutes(self, n: int, distrusted: set[str]) -> list[tuple[int, list[str]]]:
        """For each ring neighbour `n` no longer trusts, the first trusted agent beyond it on that
        side, and the agents skipped: a link to it closes the honest ring around the liar."""
        found: list[tuple[int, list[str]]] = []
        for step in (-1, 1):
            skipped: list[str] = []
            other = (n + step) % self.n_agents
            while ringfire.agent_id(other) in distrusted and other != n:
                skipped.append(ringfire.agent_id(other))
                other = (other + step) % self.n_agents
            if skipped and other != n and not self.game.net.linked(n, other):
                found.append((other, skipped))
        return found

    def worth_telling(self, n: int, day: int) -> list[str]:
        """Live, current beliefs a trusted neighbour has not had from this agent: fires it saw, and
        claims heard by two or more routes (a claim heard once may be a lie: not passed on)."""
        viewer = ringfire.agent_id(n)
        distrusted = self.runtime.distrusted(viewer)
        neighbours = [
            ringfire.agent_id(m)
            for m in self.game.net.neighbours(n)
            if ringfire.agent_id(m) not in distrusted
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
        return hints[:MAX_HINTS]

    def context_for(self, n: int, day: int, budget: int) -> str:
        """What agent `n` reads on `day`, besides "It is day N." (the probes ask with this too)."""
        viewer = ringfire.agent_id(n)
        extra = "## Map\n" + "\n".join(self.map_lines)
        extra += "\n\n" + outlook(
            self.edges,
            self.seen_fires(n),
            self.fields.get(n, ()),
            day,
            window=0 if self.linear else episode(self.game),  # a fire put out can come again
        )
        if self.linear:
            extra += "\n\n" + self.fields_now(n)
        liars = self.known_liars(n)
        if liars:
            extra += "\n\n## Known liars (you no longer trust them)\n" + "\n".join(liars)
        hints = self.link_hints(n) + self.worth_telling(n, day)
        if hints:
            extra += (
                "\n\n## Worth doing (route around liars; tell neighbours what they have not had "
                "from you)\n" + "\n".join(hints)
            )
        compiled = compile_context(
            self.store,
            viewer,
            max(0, day - 1),
            role_card=role_card(viewer, self.n_agents, self.fields.get(n, ()), self.rules),
            templates=ringfire.TEMPLATES,
            budget=max(0, budget - estimate_tokens(extra)),
        )
        return f"{compiled}\n\n{extra}"

    def context(self, node: NodeSpec, tick: int, budget: int) -> str:
        return self.context_for(number(node.id), tick, budget) + f"\n\nIt is day {tick}."


# ---- messages over the ring ---------------------------------------------------------------------


class RingTransport:
    """Messages go through the game's network, which checks the link, records the true route, and
    applies an imposter's corruption. A belief the sender was told is passed on along its route."""

    def __init__(self, pack: RingFirePack):
        self.pack = pack

    def _trace_held(self, message: Message) -> None:
        rt = self.pack.runtime
        if rt.holding:
            self.pack.trace.emit(
                "message",
                sender=message.sender,
                receiver=message.receiver,
                route=list(message.route),
                field=message.claim.field_id,
                claim_day=message.claim.day,
                altered_by=list(message.altered_by),
                held=True,
            )

    def outgoing(self, message: Message) -> Outgoing:
        self._trace_held(message)
        return Outgoing(
            sender=f"A{message.sender}",
            receiver=f"A{message.receiver}",
            tick=message.day,
            route=tuple(f"A{a}" for a in message.route),
            subject=ringfire.field_id(message.claim.field_id),
            predicate=ringfire.ARRIVAL,
            value=message.claim.day,
            payload=message,
        )

    def send(self, sender: str, receiver: str, belief: Belief, tick: int) -> Outgoing | None:
        if belief.predicate != ringfire.ARRIVAL:
            raise ValueError("only beliefs about when fire arrives can be sent")
        s, r = number(sender), number(receiver)
        node = self.pack.runtime.nodes.get(sender)
        if self.pack.linear and node is not None and node.kind == "model":
            if s not in self.pack.decided:
                raise ValueError(
                    "first decide about water today (act type 'water' or 'wait'), then send"
                )
        field_number, day = int(belief.subject[1:]), int(belief.value)
        relaying = (
            self.pack.received.get((s, field_number, day)) if belief.origin == "told" else None
        )
        rt = self.pack.runtime
        if relaying is None and belief.origin == "derived" and rt.settings.trace_provenance:
            # a conclusion drawn from what it was told: the claim travels on the told claim's route
            heard = [
                self.pack.received.get((s, int(told.subject[1:]), int(told.value)))
                for told in told_sources(self.pack.store, sender, belief.id)
            ]
            relaying = min(
                (m for m in heard if m is not None), key=lambda m: len(m.route), default=None
            )
        try:
            message = self.pack.game.send(s, r, Claim(field_number, day), relaying)
        except LinkError as error:
            raise ValueError(f"{error}; build a link first (act: link)") from error
        self.pack.sent.add((sender, receiver, belief.subject, belief.value))
        return None if message is None else self.outgoing(message)

    def deliver(self, message: Outgoing) -> Belief | None:
        sim_message: Message = message.payload
        self.pack.trace.emit(
            "message",
            sender=sim_message.sender,
            receiver=sim_message.receiver,
            route=list(sim_message.route),
            field=sim_message.claim.field_id,
            claim_day=sim_message.claim.day,
            altered_by=list(sim_message.altered_by),
            held=False,
        )
        key = (sim_message.receiver, sim_message.claim.field_id, sim_message.claim.day)
        self.pack.received[key] = sim_message
        rt = self.pack.runtime
        belief = ringfire.record_message(
            self.pack.store,
            rt.ids,
            {
                "sender": sim_message.sender,
                "receiver": sim_message.receiver,
                "route": list(sim_message.route),
                "day": sim_message.day,
                "claim": {"field_id": sim_message.claim.field_id, "day": sim_message.claim.day},
            },
            distrusted=rt.distrusted(message.receiver),
        )
        if belief is not None:
            self.pack.note_support(message.receiver, belief.id)
        return belief

    def reply(self, sender: str, receiver: str, message: Outgoing | None) -> str:
        return f"sent to {receiver}"


# ---- the world node -----------------------------------------------------------------------------


class WorldNode(Node):
    """The fire simulator as an environment node."""

    kind = "source"
    description = "The Ring Fire simulator: plays each day and reports fires to each audience."

    def __init__(self, spec: NodeSpec, runtime: Runtime):
        super().__init__(spec, runtime)
        pack = runtime.pack
        assert isinstance(pack, RingFirePack)
        self.pack = pack
        scenario: Scenario = runtime.settings.extra["scenario"]
        self.scripted: dict[int, list[SendSpec]] = {}
        for s in scenario.get("sends", []):
            self.scripted.setdefault(s["day"], []).append(s)
        self.result: DayResult | None = None
        self.seen_exposures = 0

    def start(self) -> None:
        pack, game = self.pack, self.pack.game
        world = game.sim.world
        fields = [(f, world.owner(f)) for f in range(world.n_fields)]
        spread = [(e.src, e.dst, e.weight) for e in world.edges if not e.hidden]
        ringfire.setup_map(pack.store, world.config.n_agents, fields, spread)
        for f in range(world.n_fields):
            self.rt.entities[ringfire.field_id(f)] = "Field"
        for field_number, _ in world.initial_fires:  # agents can act on day 0
            for n in game.audience(field_number, 0):
                pack.show(n, field_number, 0)
        pack.start_fires_published = True
        pack.trace.emit(
            "game_start",
            system=self.rt.settings.extra.get("system", "frame"),
            model=self.rt.client.model if self.rt.client is not None else "none",
            scenario=self.rt.settings.extra["scenario"],
            budget=self.rt.settings.budget,
            max_steps=self.rt.settings.max_steps,
            n_fields=world.n_fields,
            edges=[[e.src, e.dst, e.weight, e.hidden] for e in world.edges],
            initial_fires=[list(f) for f in world.initial_fires],
            random_ignitions=[list(r) for r in world.random_ignitions],
            imposters={str(a): b.value for a, b in game.net.imposters.items()},
        )

    def tick_start(self, tick: int) -> None:
        pack = self.pack
        pack.water_today.clear()
        pack.decided.clear()
        pack.trace.bind(day=tick)
        pack.trace.emit("day_start", scripted_sends=len(self.scripted.get(tick, [])))
        for s in self.scripted.get(tick, []):  # the imposters' scripted lies, delivered at once
            message = pack.game.send(s["sender"], s["receiver"], Claim(**s["claim"]))
            if message is not None:
                self.rt.post(RingTransport(pack).outgoing(message))

    def delivered(self, delivery: Delivery) -> None:
        """Someone is told about a field that has already burnt: the engine shows them the truth at
        once, so a late claim can still be checked. For a field that burns again, only the fires
        the claim could be about are shown."""
        if delivery.belief is None:
            return
        pack = self.pack
        sim_message: Message = delivery.message.payload
        n, field_number = sim_message.receiver, sim_message.claim.field_id
        window = episode(pack.game)
        for ignited_on in pack.game.sim.fields[field_number].ignitions:
            if window is not None and abs(ignited_on - sim_message.claim.day) > window:
                continue
            if (n, field_number, ignited_on) in pack.shown:
                continue
            pack.show(n, field_number, ignited_on)
        for day in sorted(d for f, d in pack.put_out if f == field_number):  # fire came, went out
            if window is not None and abs(day - sim_message.claim.day) > window:
                continue
            if (n, field_number, day) not in pack.shown:
                pack.show(n, field_number, day, put_out=True)

    def tick_end(self, tick: int, stage: Stage) -> None:
        pack, game = self.pack, self.pack.game
        if stage == "step":
            self.result = game.step(set(pack.water_today))
            pack.days.append(self.result)
            for edge in self.result.report.revealed_hidden:
                pack.map_lines.append(hidden_map_line(edge.src, edge.dst, edge.weight))
                pack.edges.append((edge.src, edge.dst, edge.weight))
        elif stage == "observe" and self.result is not None:
            for edge in self.result.report.revealed_hidden:
                ringfire.reveal_hidden_edge(pack.store, edge.src, edge.dst, edge.weight)
            initial = {f for f, _ in game.sim.world.initial_fires}
            for evidence in self.result.evidence:
                if evidence.put_out:
                    pack.put_out.add((evidence.field_id, evidence.day))
                if tick == 0 and pack.start_fires_published and evidence.day == 0:
                    if evidence.field_id in initial:
                        continue  # already shown to everyone before the day began
                for n in evidence.audience:
                    if (n, evidence.field_id, evidence.day) in pack.shown:
                        continue
                    pack.show(n, evidence.field_id, evidence.day, evidence.put_out)
        elif stage == "report" and self.result is not None:
            report = self.result.report
            pack.trace.emit(
                "day_end",
                ignited=[[e.field_id, e.intensity, list(e.audience)] for e in self.result.evidence],
                burnt_out=list(report.burnt_out),
                regrown=list(report.regrown),
                hit_while_watered=list(report.hit_while_watered),
                revealed_hidden=[[e.src, e.dst] for e in report.revealed_hidden],
                watered=sorted(pack.water_today),
                links=[sorted(link) for link in game.net.links],
            )
            self.rt.log.emit(
                tick,
                "world",
                ignited=[e.field_id for e in self.result.evidence],
                burnt_out=list(report.burnt_out),
                regrown=list(report.regrown),
                saved=list(report.hit_while_watered),
                watered=sorted(pack.water_today),
                water_on_fire=list(report.water_on_fire),
                water_wasted=list(report.water_wasted),
                extinguished=list(report.extinguished),
                strength=[list(x) for x in report.strength],
                links=[sorted(link) for link in game.net.links],
            )
            for exposure in self.rt.exposures[self.seen_exposures :]:
                pack.trace.emit(
                    "exposure",
                    viewer=exposure.viewer,
                    distrusted=exposure.agent,
                    reason=exposure.reason,
                    changes=[
                        [c.belief_id, c.old_status, c.new_status, c.path_len]
                        for c in exposure.changes
                    ],
                )
            self.seen_exposures = len(self.rt.exposures)


# ---- imposters ----------------------------------------------------------------------------------


@dataclass
class Imposters:
    """The imposters' turns: a saboteur's planned lies, then passing on whatever they received."""

    pack: RingFirePack
    relayed: set[tuple[int, int, int]] = field(default_factory=set[tuple[int, int, int]])
    lied_about: set[tuple[int, int, int]] = field(default_factory=set[tuple[int, int, int]])

    def turn(self, node: Node, tick: int) -> None:
        pack, game = self.pack, self.pack.game
        me = number(node.id)
        transport = RingTransport(pack)
        if game.net.imposters[me] is Behaviour.SABOTEUR:
            for receiver, claim in planned_lies(game, me, self.lied_about):
                sent = game.send(me, receiver, claim)
                pack.trace.emit(
                    "imposter_lie",
                    imposter=me,
                    to=receiver,
                    field=claim.field_id,
                    claim_day=claim.day,
                    delivered=sent is not None,
                )
                if sent is not None:
                    node.rt.post(transport.outgoing(sent))
        for key, message in list(pack.received.items()):
            if key[0] != me or key in self.relayed:
                continue
            self.relayed.add(key)
            for neighbour in game.net.neighbours(me):
                if neighbour == message.sender or neighbour in message.route:
                    continue
                sent = game.send(me, neighbour, message.claim, message)
                pack.trace.emit(
                    "imposter_relay",
                    imposter=me,
                    to=neighbour,
                    field=message.claim.field_id,
                    claim_day=message.claim.day,
                    delivered=sent is not None,
                )
                if sent is not None:
                    node.rt.post(transport.outgoing(sent))


# ---- the rerouter: a responder in code -----------------------------------------------------------


class RerouterNode(Node):
    """Acts on a cascade: once an agent stops trusting a ring neighbour, it links that agent to the
    first trusted agent beyond, so the honest ring closes around the liar without waiting for the
    agent to think of it."""

    description = "Links honest agents around a neighbour they no longer trust."

    def tick_end(self, tick: int, stage: Stage) -> None:
        if stage != "report":
            return
        pack = self.rt.pack
        assert isinstance(pack, RingFirePack)
        for n in range(pack.n_agents):
            viewer = f"A{n}"
            if self.rt.nodes[viewer].kind == "scripted":
                continue
            for target, skipped in pack.reroutes(n, self.rt.distrusted(viewer)):
                pack.game.net.add_link(n, target)
                self.rt.log.emit(
                    tick,
                    "action",
                    node=self.id,
                    tool="link",
                    arguments={"from": viewer, "to": f"A{target}"},
                    result=f"linked {viewer} to A{target} around {', '.join(skipped)}",
                    status="done",
                )
                self.rt.wake(viewer, "change")


CATALOGUE = {"ringfire.world": WorldNode, "ringfire.rerouter": RerouterNode}


# ---- running a game -----------------------------------------------------------------------------


@dataclass
class FrameView:
    """What the scorer and the probes read from a frame run (the part of GraphBackend they use)."""

    pack: RingFirePack
    runtime: Runtime
    name: str = "frame"

    @property
    def store(self) -> Store:
        return self.pack.store

    @property
    def exposures(self) -> list[Exposure]:
        return self.runtime.exposures

    def context(self, number: int, day: int, budget: int) -> str:
        return self.pack.context_for(number, day, budget)

    # The rest of harness.types.Backend: a frame run drives itself, so nothing calls these.
    def start(self, game: Game) -> None:
        raise NotImplementedError("a frame run is driven by its runtime")

    def message(self, message: Message) -> None:
        raise NotImplementedError("a frame run is driven by its runtime")

    def day(self, game: Game, result: DayResult) -> None:
        raise NotImplementedError("a frame run is driven by its runtime")

    def toolbox(self, number: int, send: SendFn, execute: ExecuteFn) -> Toolbox:
        raise NotImplementedError("a frame run builds its tools per node")

    def graph_parts(self) -> tuple[Store, set[tuple[str, str]], int]:
        """(store, the (viewer, agent) distrust pairs, how many warnings were sent)."""
        warner = self.runtime.nodes.get("warner")
        warnings = len(warner.warnings) if isinstance(warner, WarnerNode) else 0
        return self.store, self.runtime.exposed_pairs, warnings


AfterDay = Callable[[Game, Any, int], None]


def build_runtime(
    team: TeamSpec,
    store: Store,
    client: ModelClient | None,
    trace: Trace = NO_TRACE,
) -> tuple[Runtime, RingFirePack]:
    scenario: Scenario = team.settings.extra["scenario"]
    game = build_game(scenario)
    pack = RingFirePack(game, store, trace)
    runtime = Runtime(
        team,
        pack,
        store,
        client,
        catalogue=dict(CATALOGUE),
        trace=trace,
        network=RingNetwork(game),
    )
    pack.rt = runtime
    runtime.transport = RingTransport(pack)
    runtime.scripts["imposter"] = Imposters(pack).turn
    return runtime, pack


def run_frame_game(
    scenario: Scenario,
    store: Store,
    client: ModelClient,
    *,
    budget: int = 4000,
    max_days: int = 100,
    max_steps: int = 6,
    after_day: AfterDay | None = None,
    trace: Trace = NO_TRACE,
    quorum: int | None = None,
    wake: bool = False,
    rerouter: bool = False,
    system: str = "frame",
    team: TeamSpec | None = None,
    on_runtime: Callable[[Runtime], None] | None = None,
) -> tuple[GameResult, FrameView]:
    """Play the scenario on the frame. Same arguments and result as harness.game.run_game."""
    team = team or team_for(
        scenario, quorum=quorum, wake=wake, rerouter=rerouter, budget=budget, max_steps=max_steps
    )
    team.settings.extra["system"] = system
    runtime, pack = build_runtime(team, store, client, trace)
    view = FrameView(pack, runtime, system)
    game = pack.game
    if after_day is not None:
        runtime.after_tick.append(lambda day: after_day(game, view, day))
    runtime.after_tick.append(lambda day: trace.unbind("day"))
    runtime.finished = lambda: game.finished
    if on_runtime is not None:
        on_runtime(runtime)
    runtime.run(max_ticks=max_days)
    turns: list[tuple[int, str, TurnResult]] = list(runtime.turns)
    result = GameResult(game=game, exposures=runtime.exposures, turns=turns, days=pack.days)
    return result, view
