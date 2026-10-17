"""The runtime: builds the live nodes from a team, runs the clock, and carries messages and items.

One tick, in order:

  1. tick_start   every node, in team order (a schedule fires; scripted sends go out at once)
  2. turns        every node that wants a turn takes it, in team order. Messages sent during the
                  turns are held until all turns are over (`hold_messages`), so the order of the
                  turns decides nothing about who hears what first
  3. delivery     the held messages are delivered, in the order they were sent
  4. tick_end     every node, once per stage, in team order:
                    step            the environment plays the tick
                    before_observe  e.g. warnings sent yesterday arrive
                    observe         items are routed to their owners and recorded; the checker
                                    tests what was told against what was observed
                    after_observe   e.g. claims whose time passed are checked; warnings go out
                    report          the tick is summed up
  5. after_tick   hooks the caller passed (probes, live streaming)

The runtime knows nothing about any domain. What a message or an item means is the pack's business
(packs/), and so is what the environment does.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol

from ..core.ids import Ids
from ..core.model import Agent, Belief, Edge, Entity, Observation
from ..core.registry import Predicate
from ..core.store import Exposure, Invalidation, Store, told_sources
from ..harness.agent import TurnResult
from ..harness.llm import ModelClient
from ..harness.trace import NO_TRACE, Trace
from .events import EventLog
from .spec import NodeSpec, TeamSpec
from .tools import ToolProvider, ToolSpec, allowed

Stage = Literal["step", "before_observe", "observe", "after_observe", "report"]
STAGES: tuple[Stage, ...] = ("step", "before_observe", "observe", "after_observe", "report")

Blame = tuple[str, str]  # (node id, why the viewer stops trusting it)
Route = tuple[str, ...]  # the nodes a claim passed through, in order


@dataclass
class Item:
    """Something a stream produced: a mail, a calendar change, a sensor reading.

    `about` names the entities it concerns; the router sends it to their owners. `to` addresses it
    to nodes directly instead (None: route by ownership). `claims` are what it states, as
    (subject, predicate, value), when the stream already knows them; otherwise the pack extracts
    them. `source` is who it came from: an outside sender is a node in the graph too, so it can be
    distrusted like any agent.
    """

    id: str
    kind: str
    tick: int
    source: str
    about: list[str] = field(default_factory=list[str])
    to: list[str] | None = None
    payload: dict[str, Any] = field(default_factory=dict[str, Any])
    claims: list[tuple[str, str, Any]] = field(default_factory=list[tuple[str, str, Any]])


@dataclass
class Outgoing:
    """A message the transport accepted and will deliver (now, or when the turns are over)."""

    sender: str
    receiver: str
    tick: int
    route: tuple[str, ...]
    subject: str
    predicate: str
    value: Any
    source_belief: str | None = None  # the sender's belief it came from
    payload: Any = None  # whatever the pack's transport needs to record it


@dataclass
class Delivery:
    """A delivered message, and the belief the receiver formed (None: it did not believe it)."""

    message: Outgoing
    belief: Belief | None


class Transport(Protocol):
    """How a belief travels from one node to another. `send` checks and prepares the message
    (raise ValueError to refuse, return None if it was swallowed); `deliver` records it."""

    def send(self, sender: str, receiver: str, belief: Belief, tick: int) -> Outgoing | None: ...

    def deliver(self, message: Outgoing) -> Belief | None: ...

    def reply(self, sender: str, receiver: str, message: Outgoing | None) -> str: ...


class Network(Protocol):
    """Who can talk to whom."""

    def neighbours(self, node: str) -> list[str]: ...

    def linked(self, a: str, b: str) -> bool: ...

    def link(self, a: str, b: str) -> None: ...


class Pack(Protocol):
    """What a domain gives the generic nodes."""

    name: str
    predicates: dict[str, Predicate]
    templates: dict[str, str]

    def context(self, node: NodeSpec, tick: int, budget: int) -> str: ...

    def record_item(self, viewer: str, item: Item) -> list[Belief]: ...


# ---- nodes --------------------------------------------------------------------------------------


class Node:
    """A live node. Every hook does nothing unless a node type overrides it."""

    kind: ClassVar[Literal["source", "code", "model", "scripted"]] = "code"
    description: ClassVar[str] = ""

    def __init__(self, spec: NodeSpec, runtime: "Runtime"):
        self.spec = spec
        self.rt = runtime

    @property
    def id(self) -> str:
        return self.spec.id

    def start(self) -> None:
        """Before the first tick."""

    def tick_start(self, tick: int) -> None:
        """A tick begins."""

    def wants_turn(self, tick: int) -> bool:
        return False

    def turn(self, tick: int) -> None:
        """Take a turn (model and scripted nodes)."""

    def delivered(self, delivery: Delivery) -> None:
        """A message was delivered to some node (every node hears of every delivery)."""

    def observed(self, viewer: str, belief: Belief, item: Item) -> None:
        """`viewer` recorded `belief` from `item`."""

    def exposed(self, exposure: Exposure) -> None:
        """Somebody stopped trusting somebody."""

    def tick_end(self, tick: int, stage: Stage) -> None:
        """The tick is over: called once per stage."""


NodeFactory = Callable[[NodeSpec, "Runtime"], Node]


# ---- defaults for runs that do not bring their own -----------------------------------------------


class TeamNetwork:
    """The talks_to links of the team, as an undirected graph that can grow."""

    def __init__(self, team: TeamSpec):
        self.links = {
            frozenset((link.src, link.dst)) for link in team.links if link.kind == "talks_to"
        }

    def neighbours(self, node: str) -> list[str]:
        return sorted(next(iter(link - {node})) for link in self.links if node in link)

    def linked(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self.links

    def link(self, a: str, b: str) -> None:
        self.links.add(frozenset((a, b)))


class GraphTransport:
    """The service is the transport: it records the route, so nobody can fake or forget it.

    A belief the sender was told travels on along the route it came by (plus the sender); anything
    else starts a new route at the sender. The receiver gets an observation with that route and a
    told belief it supports; the same claim heard again by another route supports the same belief.
    A message whose route passes through a node the receiver distrusts is recorded but not believed.
    """

    def __init__(self, runtime: "Runtime"):
        self.rt = runtime

    def send(self, sender: str, receiver: str, belief: Belief, tick: int) -> Outgoing | None:
        if receiver not in self.rt.nodes:
            raise ValueError(f"unknown node {receiver}")
        if not self.rt.network.linked(sender, receiver):
            raise ValueError(f"{sender} cannot talk to {receiver}; they are not linked")
        for holder, copy in self.rt.copies.get((sender, belief.id), []):
            held = self.rt.store.belief(holder, copy)
            if holder == receiver and held is not None and held.status in ("active", "suspect"):
                raise ValueError(f"{receiver} already has this from you (their {copy})")
        routes = self.rt.store.support_routes(sender, belief.id) if belief.origin == "told" else []
        if belief.origin == "derived" and self.rt.settings.trace_provenance:
            for told in told_sources(self.rt.store, sender, belief.id):
                routes.extend(self.rt.store.support_routes(sender, told.id))
        before = min(routes, key=len) if routes else ()
        return Outgoing(
            sender=sender,
            receiver=receiver,
            tick=tick,
            route=(*before, sender),
            subject=belief.subject,
            predicate=belief.predicate,
            value=belief.value,
            source_belief=belief.id,
        )

    def deliver(self, message: Outgoing) -> Belief | None:
        rt = self.rt
        observation = Observation(
            id=rt.ids.next("O"),
            kind="message",
            payload={
                "subject": message.subject,
                "predicate": message.predicate,
                "value": message.value,
                "route": list(message.route),
                "source_belief": message.source_belief,
            },
            received_by=message.receiver,
            sender=message.sender,
            received_tick=message.tick,
        )
        rt.store.add_node(observation)
        for hop, node in enumerate(message.route):
            rt.ensure_agent(node)
            rt.store.add_edge(
                Edge(kind="RELAYED_VIA", src=observation.id, dst=node, props={"hop": hop})
            )
        if rt.store.get(message.receiver, message.subject) is not None:
            rt.store.add_edge(
                Edge(
                    kind="ABOUT",
                    src=observation.id,
                    dst=message.subject,
                    props={"role": "mentioned"},
                )
            )
        if set(message.route) & rt.distrusted(message.receiver):
            return None
        belief = rt.believe(
            message.receiver,
            message.subject,
            message.predicate,
            message.value,
            "told",
            message.tick,
            observation.id,
        )
        if message.source_belief is not None:
            held = rt.copies.setdefault((message.sender, message.source_belief), [])
            if (message.receiver, belief.id) not in held:
                held.append((message.receiver, belief.id))
        return belief

    def reply(self, sender: str, receiver: str, message: Outgoing | None) -> str:
        return f"sent to {receiver}"


# ---- the runtime --------------------------------------------------------------------------------


class Runtime:
    def __init__(
        self,
        team: TeamSpec,
        pack: Pack,
        store: Store,
        client: ModelClient | None = None,
        *,
        catalogue: dict[str, NodeFactory] | None = None,
        ids: Ids | None = None,
        trace: Trace = NO_TRACE,
        network: Network | None = None,
        transport: Transport | None = None,
        log: EventLog | None = None,
    ):
        from .nodes import CATALOGUE  # the generic node types; a pack may add or replace some

        self.team = team
        self.settings = team.settings
        self.pack = pack
        self.store = store
        self.client = client
        self.ids = ids or Ids()
        self.trace = trace
        self.log = log or EventLog()
        self.network: Network = network or TeamNetwork(team)
        self.transport: Transport = transport or GraphTransport(self)
        self.tick = 0
        self.holding = False
        self.held: list[Outgoing] = []
        self.exposures: list[Exposure] = []
        self.exposed_pairs: set[tuple[str, str]] = set()  # (viewer, agent) already acted on
        # (viewer, agent) -> the routes of the claims it was blamed for, to tell a node that made
        # a lie up from one that passed it on (see `exonerate`)
        self.blame_routes: dict[tuple[str, str], list[Route]] = {}
        self.restored: list[tuple[int, str, str, str]] = []  # (tick, viewer, agent, why)
        self.turns: list[tuple[int, str, TurnResult]] = []
        self.pending: dict[str, set[str]] = {}  # node -> trigger kinds that fired since its turn
        self.after_tick: list[Callable[[int], None]] = []
        self.providers: list[ToolProvider] = []  # where nodes' own tools come from
        self.feeds: dict[str, Callable[[int], list[Item]]] = {}  # stream name -> items per tick
        self.scripts: dict[str, Callable[[Node, int], None]] = {}  # scripted nodes' scripts
        self.entities: dict[str, str] = {}  # entity id -> type, for "owns type:X" links
        # (sender, its belief) -> [(receiver, the receiver's copy)]: who holds what it passed on
        self.copies: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self.checks = 0  # checking-tool results recorded as evidence
        # (viewer, belief) -> the observations that support it, as recorded (for "why")
        self.supports: dict[tuple[str, str], list[str]] = {}
        self.closers: list[Callable[[], None]] = []  # e.g. MCP connections, closed by close()
        self.finished: Callable[[], bool] = lambda: False
        self.stopped = False
        factories = {**CATALOGUE, **(catalogue or {})}
        self.nodes: dict[str, Node] = {}
        for spec in team.nodes:
            if spec.type not in factories:
                raise ValueError(f"node {spec.id}: unknown type {spec.type!r}")
            self.nodes[spec.id] = factories[spec.type](spec, self)

    # ---- graph helpers the nodes share --------------------------------------------------------

    def ensure_agent(self, node_id: str, role: str = "") -> None:
        """Every node that can say something is an Agent in the graph, so it can be distrusted."""
        if self.store.get(node_id, node_id) is None:
            self.store.add_node(Agent(id=node_id, role=role or "source"))

    def ensure_entity(
        self, entity_id: str, type_: str, name: str = "", owner: str | None = None, **props: Any
    ) -> None:
        """Entities are shared: everyone sees the same one."""
        self.entities.setdefault(entity_id, type_)
        if self.store.get("", entity_id) is None:
            self.store.add_node(
                Entity(id=entity_id, type=type_, name=name, owner=owner, props=props)
            )

    def owned_entities(self, node: str) -> list[str]:
        """The entities `node` owns: named in an owns link, or of a type it owns."""
        found: list[str] = []
        for link in self.team.links_from(node, "owns"):
            if link.dst.startswith("type:"):
                found += [e for e, t in self.entities.items() if f"type:{t}" == link.dst]
            elif link.dst not in found:
                found.append(link.dst)
        return found

    def tools_for(self, spec: NodeSpec) -> list[ToolSpec]:
        """The node's own tools: every provided tool its spec allows."""
        found: list[ToolSpec] = []
        for provider in self.providers:
            for_node: Callable[[str], list[ToolSpec]] | None = getattr(
                provider, "tools_for_node", None
            )
            tools = for_node(spec.id) if for_node is not None else provider.list_tools()
            found += [tool for tool in tools if allowed(tool.name, spec.tools)]
        return found

    def believe(
        self,
        viewer: str,
        subject: str,
        predicate: str,
        value: Any,
        origin: Literal["observed", "told", "derived"],
        tick: int,
        observation_id: str | None = None,
        **extra: Any,
    ) -> Belief:
        """Find the viewer's live belief with this claim and origin, or make it; attach support."""
        for belief in self.store.beliefs(viewer, subject=subject, predicate=predicate):
            if (
                belief.status in ("active", "suspect")
                and belief.value == value
                and belief.origin == origin
            ):
                found = belief
                break
        else:
            found = Belief(
                id=self.ids.next("B"),
                owner=viewer,
                subject=subject,
                predicate=predicate,
                value=value,
                origin=origin,
                kind="fact" if origin == "observed" else "forecast",
                created_tick=tick,
                updated_tick=tick,
                **extra,
            )
            self.store.add_node(found)
            self.store.add_edge(
                Edge(kind="ABOUT", src=found.id, dst=subject, props={"role": "subject"})
            )
        if observation_id is not None:
            self.store.add_edge(
                Edge(kind="SUPPORTS", src=observation_id, dst=found.id, props={"tick": tick})
            )
            self.supports.setdefault((viewer, found.id), []).append(observation_id)
        return found

    def distrusted(self, viewer: str) -> set[str]:
        return {agent for v, agent in self.exposed_pairs if v == viewer}

    def distrust(
        self,
        viewer: str,
        blames: Iterable[Blame],
        tick: int,
        *,
        spread: bool = True,
        routes: Mapping[str, Sequence[Route]] | None = None,
    ) -> list[Exposure]:
        """`viewer` stops trusting each blamed node (once), and the store propagates. With team
        quarantine, an outside source it blames is distrusted by every model node too.

        `routes`: the routes of the claims each node is blamed for. With `settings.repair`, a node
        blamed only for relaying is trusted again once the claims' makers are exposed."""
        made: list[Exposure] = []
        for agent, reason in blames:
            if agent == viewer:
                continue  # its own claim came back to it: nobody else to blame
            known = self.blame_routes.setdefault((viewer, agent), [])
            known.extend(r for r in (routes or {}).get(agent, ()) if r not in known)
            if (viewer, agent) in self.exposed_pairs:
                continue
            self.exposed_pairs.add((viewer, agent))
            changes = self.store.expose(viewer, agent, tick=tick, reason=reason)
            exposure = Exposure(viewer, agent, tick, reason, changes)
            self.exposures.append(exposure)
            made.append(exposure)
            self.log.emit(
                tick,
                "exposure",
                viewer=viewer,
                agent=agent,
                reason=reason,
                routes=[list(r) for r in known],
                changes=[c.model_dump() for c in changes],
            )
            self._changed(viewer, changes, reason, tick)
            for neighbour in self.network.neighbours(viewer):
                self.wake(neighbour, "exposure")
            for node in self.nodes.values():
                node.exposed(exposure)
            if spread and self.settings.quarantine == "team" and agent not in self.nodes:
                # an outside source caught lying is blocked for the whole team at once
                for other in self.nodes.values():
                    if other.kind == "model" and other.id != viewer:
                        self.distrust(
                            other.id,
                            [(agent, f"quarantined by {viewer}: {reason}")],
                            tick,
                            spread=False,
                        )
        if self.settings.repair:
            self.exonerate(viewer, tick)
        return made

    def exonerate(self, viewer: str, tick: int) -> list[str]:
        """Trust again each node the viewer blamed only as the relay of a claim that began with a
        node it has since exposed: the claim's falsehood is explained by its maker.

        A node blamed for a claim it made itself (the route starts at it), or blamed with no route
        on record (a warning, an expired deadline), stays distrusted. A node explained only by
        another node that is itself being lifted stays distrusted too."""
        held = {a for v, a in self.exposed_pairs if v == viewer}
        lifting = {
            a
            for a in held
            if self.blame_routes.get((viewer, a))
            and all(a in r and r.index(a) > 0 for r in self.blame_routes[(viewer, a)])
        }
        while True:
            firm = held - lifting
            explained = {
                a
                for a in lifting
                if all(firm & set(r[: r.index(a)]) for r in self.blame_routes[(viewer, a)])
            }
            if explained == lifting:
                break
            lifting = explained
        for agent in sorted(lifting):
            upstream = {m for r in self.blame_routes[(viewer, agent)] for m in r[: r.index(agent)]}
            makers = ", ".join(sorted(upstream & held))
            self.restore(viewer, agent, tick, f"it only passed on a claim from {makers}")
        return sorted(lifting)

    def restore(self, viewer: str, agent: str, tick: int, reason: str) -> list[Invalidation]:
        """`viewer` trusts `agent` again: what went stale because of it is active again."""
        if (viewer, agent) not in self.exposed_pairs:
            return []
        self.exposed_pairs.discard((viewer, agent))
        self.blame_routes.pop((viewer, agent), None)
        changes = self.store.reinstate(viewer, agent, tick, reason)
        self.restored.append((tick, viewer, agent, reason))
        self.log.emit(
            tick,
            "reinstatement",
            viewer=viewer,
            agent=agent,
            reason=reason,
            changes=[c.model_dump() for c in changes],
        )
        self._changed(viewer, changes, reason, tick)
        return changes

    def retract(self, viewer: str, belief_id: str, tick: int, reason: str) -> list[Invalidation]:
        changes = self.store.retract(viewer, belief_id, tick, reason)
        self._changed(viewer, changes, reason, tick)
        return changes

    def _changed(
        self, viewer: str, changes: Sequence[Invalidation], reason: str, tick: int
    ) -> None:
        for change in changes:
            self.log.emit(
                tick,
                "change",
                viewer=viewer,
                belief=change.belief_id,
                old=change.old_status,
                new=change.new_status,
                hops=change.path_len,
                reason=reason,
            )
        if changes:
            self.wake(viewer, "change")
        if self.settings.fan_out:
            for change in changes:
                if change.new_status != "active":
                    self._fan_out(viewer, change.belief_id, reason, tick)

    def _fan_out(self, viewer: str, belief_id: str, reason: str, tick: int) -> None:
        """`viewer`'s belief changed: every copy it passed on that rests only on it is withdrawn
        (and what rests on those copies is flagged, and so on down the line). A copy that also
        arrived by a route not through `viewer` is kept: it has independent support."""
        for receiver, copy in self.copies.get((viewer, belief_id), []):
            held = self.store.belief(receiver, copy)
            if held is None or held.status not in ("active", "suspect"):
                continue
            routes = self.store.support_routes(receiver, copy)
            if any(viewer not in route for route in routes):
                continue
            try:
                self.retract(
                    receiver,
                    copy,
                    tick,
                    f"{viewer} withdrew {belief_id}, which this came from: {reason}",
                )
            except ValueError:
                continue

    def wake(self, node_id: str, reason: str) -> None:
        if node_id in self.nodes:
            self.pending.setdefault(node_id, set()).add(reason)

    # ---- messages and items -------------------------------------------------------------------

    def send(self, sender: str, receiver: str, belief: Belief) -> str:
        """A node passes one of its beliefs on. Refusals raise ValueError (the tool shows it)."""
        message = self.transport.send(sender, receiver, belief, self.tick)
        if message is not None:
            self.post(message)
        return self.transport.reply(sender, receiver, message)

    def post(self, message: Outgoing) -> None:
        """Deliver now, or hold until the turns are over."""
        if self.holding:
            self.held.append(message)
            return
        self.deliver(message)

    def deliver(self, message: Outgoing) -> Delivery:
        belief = self.transport.deliver(message)
        delivery = Delivery(message, belief)
        self.log.emit(
            message.tick,
            "message",
            sender=message.sender,
            receiver=message.receiver,
            route=list(message.route),
            subject=message.subject,
            predicate=message.predicate,
            value=message.value,
            believed=belief is not None,
            belief=belief.id if belief is not None else None,
        )
        self.wake(message.receiver, "message")
        for node in self.nodes.values():
            node.delivered(delivery)
        return delivery

    def flush(self) -> None:
        held, self.held = self.held, []
        for message in held:
            self.deliver(message)

    def route(
        self, item: Item, recipients: Sequence[str], via: Sequence[str] = ()
    ) -> dict[str, list[Belief]]:
        """Record `item` for each recipient (in order) and tell every node what was observed.
        `via`: the nodes it passed through on the way (its stream, then the router), logged so
        the console can draw the path."""
        recorded: dict[str, list[Belief]] = {}
        for viewer in recipients:
            beliefs = self.pack.record_item(viewer, item)
            recorded[viewer] = beliefs
            self.wake(viewer, "item")
            for belief in beliefs:
                for node in self.nodes.values():
                    node.observed(viewer, belief, item)
        self.log.emit(
            item.tick,
            "item",
            item=item.id,
            item_kind=item.kind,
            source=item.source,
            about=item.about,
            to=list(recipients),
            via=list(via),
            payload=item.payload,
        )
        return recorded

    def owners(self, entity_id: str) -> list[str]:
        """The nodes with an `owns` link to this entity or to its type."""
        entity = self.store.get("", entity_id)
        type_ = entity.type if isinstance(entity, Entity) else self.entities.get(entity_id)
        found: list[str] = []
        for link in self.team.links:
            if link.kind != "owns":
                continue
            if link.dst == entity_id or (type_ is not None and link.dst == f"type:{type_}"):
                if link.src not in found:
                    found.append(link.src)
        return found

    # ---- the clock ----------------------------------------------------------------------------

    def start(self) -> None:
        self.log.emit(
            0,
            "run_start",
            team=self.team.model_dump(mode="json"),
            pack=self.pack.name,
        )
        for node in self.nodes.values():
            node.start()

    def step(self) -> None:
        """Play one tick."""
        tick = self.tick
        self.log.emit(tick, "tick")
        for node in self.nodes.values():
            node.tick_start(tick)
        self.holding = self.settings.hold_messages
        for node in self.nodes.values():
            if node.wants_turn(tick):
                node.turn(tick)
                self.pending.pop(node.id, None)
        self.holding = False
        self.flush()
        for stage in STAGES:
            for node in self.nodes.values():
                node.tick_end(tick, stage)
        for hook in self.after_tick:
            hook(tick)
        self.log.emit(tick, "tick_end")
        self.tick += 1

    def close(self) -> None:
        for close in self.closers:
            close()
        self.closers.clear()

    def run(self, max_ticks: int = 100) -> None:
        self.start()
        limit = self.settings.ticks if self.settings.ticks is not None else max_ticks
        while not self.stopped and not self.finished() and self.tick < limit:
            self.step()
        self.log.emit(self.tick, "run_end")
