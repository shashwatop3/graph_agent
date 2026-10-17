"""The node catalogue: the ready-made node types a user wires together.

    schedule   code    wakes the nodes it feeds every `every` ticks
    stream     source  pulls items from a feed (a mailbox, a log, a game) and hands them on
    router     code    links each item to the entities it is about and delivers it to their owners
    agent      model   a language-model agent: triggers, its own tools, the shared graph tools
    responder  model   an agent woken by cascades: a belief it watches changed, an action was held
    checker    code    tests told beliefs against evidence, and claims whose time has passed
    warner     code    passes word of an exposed node to trusted peers; acts on a quorum
    scripted   code    runs a script each turn (test fixtures, the game's imposters)

Every node type is a class with the hooks of runtime.Node. A pack can add its own types (a game's
environment, a mailbox) by passing them to the Runtime.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from ..core.compiler import estimate_tokens
from ..core.model import Action, Belief, Edge
from ..core.tools import Toolbox
from ..harness.agent import SYSTEM_PROMPT
from ..harness.llm import Json
from .policies import blame_for_evidence
from .runtime import Blame, Delivery, Item, Node, NodeFactory, Outgoing, Runtime, Stage
from .spec import NodeSpec, Trigger, TriggerKind
from .tools import ToolSet, ToolSpec
from .turn import run_node_turn

LIVE = ("active", "suspect")


# ---- proposals: outward actions wait for a person, and are held if their basis changes -----------


@dataclass
class Proposal:
    id: str
    node: str
    tool: str
    arguments: dict[str, Any]
    basis: list[str]  # the node's beliefs it rests on
    tick: int
    # held: what it rested on changed; reviewed: held, and its node has had a turn since
    status: Literal[
        "pending", "approved", "rejected", "held", "reviewed", "done", "failed", "shadow"
    ] = "pending"
    result: str = ""
    note: str = ""
    action_id: str | None = None


@dataclass
class Approvals:
    """Outward tool calls. With approvals "auto" they run at once; with "manual" they wait for a
    person; with "shadow" they are recorded (and held if what they rest on changes) but never run:
    the way to watch what a team would do on real data."""

    rt: Runtime
    proposals: dict[str, Proposal] = field(default_factory=dict[str, Proposal])
    issued: int = 0
    handlers: dict[str, Callable[[dict[str, Any]], str]] = field(
        default_factory=dict[str, Callable[[dict[str, Any]], str]]
    )

    def submit(self, node: str, tool: ToolSpec, arguments: dict[str, Any]) -> str:
        given: list[object] = list(arguments.pop("depends_on", None) or [])
        basis = [str(b) for b in given]
        for belief_id in basis:
            belief = self.rt.store.belief(node, belief_id)
            if belief is None:
                raise ValueError(f"{belief_id} is not one of your beliefs")
            if belief.status not in LIVE:
                raise ValueError(f"{belief_id} is {belief.status}; nothing can rest on it")
        self.issued += 1
        proposal = Proposal(f"P{self.issued}", node, tool.name, arguments, basis, self.rt.tick)
        self.proposals[proposal.id] = proposal
        self.handlers[proposal.id] = tool.handler
        action = Action(
            id=self.rt.ids.next("X"),
            owner=node,
            type=tool.name,
            target=str(arguments.get("target") or arguments.get("to") or arguments.get("id") or "")
            or None,
            params=arguments,
            status="done",  # the proposal tracks its fate; the node records what it rests on
        )
        self.rt.store.add_node(action)
        for belief_id in basis:
            self.rt.store.add_edge(
                Edge(
                    kind="DERIVED_FROM", src=action.id, dst=belief_id, props={"tick": self.rt.tick}
                )
            )
        proposal.action_id = action.id
        self.rt.log.emit(
            self.rt.tick,
            "proposal",
            id=proposal.id,
            node=node,
            tool=tool.name,
            arguments=arguments,
            basis=basis,
            action=action.id,
        )
        if self.rt.settings.approvals == "auto":
            return self.decide(proposal.id, True, by="auto")
        if self.rt.settings.approvals == "shadow":
            proposal.status = "shadow"
            proposal.result = "shadow mode: recorded, not executed"
            self.rt.log.emit(
                self.rt.tick,
                "action",
                id=proposal.id,
                node=node,
                tool=tool.name,
                arguments=arguments,
                result=proposal.result,
                status="shadow",
            )
            return f"{proposal.id}: {proposal.result}"
        return f"{proposal.id}: proposed {tool.name}; it runs once a person approves it"

    def decide(self, proposal_id: str, approved: bool, by: str = "person") -> str:
        proposal = self.proposals[proposal_id]
        if proposal.status not in ("pending", "held"):
            raise ValueError(f"{proposal_id} is already {proposal.status}")
        self.rt.log.emit(self.rt.tick, "decision", id=proposal_id, approved=approved, by=by)
        self.rt.wake(proposal.node, "approval")
        if not approved:
            proposal.status = "rejected"
            return f"{proposal_id}: rejected"
        proposal.status = "approved"
        try:
            proposal.result = self.handlers[proposal_id](dict(proposal.arguments))
            proposal.status = "done"
        except (ValueError, KeyError) as error:
            proposal.result = f"error: {error.args[0] if error.args else error}"
            proposal.status = "failed"
        self.rt.log.emit(
            self.rt.tick,
            "action",
            id=proposal_id,
            node=proposal.node,
            tool=proposal.tool,
            arguments=proposal.arguments,
            result=proposal.result,
            status=proposal.status,
        )
        return f"{proposal_id}: {proposal.result}"

    def reviewed(self, node: str) -> None:
        """`node` has had a turn with its held proposals in view."""
        for proposal in self.proposals.values():
            if proposal.node == node and proposal.status == "held":
                proposal.status = "reviewed"

    def recheck(self, viewer: str, reason: str) -> list[Proposal]:
        """Hold every pending or done proposal of `viewer` whose basis is no longer sound."""
        held: list[Proposal] = []
        for proposal in self.proposals.values():
            if proposal.node != viewer or proposal.status not in (
                "pending",
                "done",
                "approved",
                "shadow",
            ):
                continue
            broken = [
                b
                for b in proposal.basis
                if (belief := self.rt.store.belief(viewer, b)) is None
                or belief.status not in LIVE
                or belief.status == "suspect"
            ]
            if not broken:
                continue
            was_done = proposal.status in ("done", "shadow")
            proposal.status = "held"
            proposal.note = (
                f"{'already carried out; ' if was_done else ''}rests on {', '.join(broken)}, "
                f"which changed: {reason}"
            )
            held.append(proposal)
            self.rt.log.emit(
                self.rt.tick,
                "held",
                id=proposal.id,
                node=viewer,
                tool=proposal.tool,
                arguments=proposal.arguments,
                broken=broken,
                was_done=was_done,
                reason=reason,
            )
            self.rt.wake(viewer, "change")
            for node in self.rt.nodes.values():
                if isinstance(node, ResponderNode) and node.watches(viewer):
                    self.rt.wake(node.id, "change")
        return held


def approvals(rt: Runtime) -> Approvals:
    found = getattr(rt, "_approvals", None)
    if found is None:
        found = Approvals(rt)
        rt._approvals = found  # type: ignore[attr-defined]  # one per runtime
        rt.log.listen(lambda e: _on_change(found, e.kind, e.data))
    return found


def _on_change(found: Approvals, kind: str, data: dict[str, Any]) -> None:
    if kind == "change" and data.get("new") in ("stale", "suspect", "retracted", "superseded"):
        found.recheck(str(data["viewer"]), str(data.get("reason", "")))


# ---- schedule, stream, router -------------------------------------------------------------------


class ScheduleNode(Node):
    kind = "source"
    description = "Wakes the nodes it feeds every `every` ticks (config: every, at)."

    def tick_start(self, tick: int) -> None:
        every = int(self.spec.config.get("every", 1))
        at = int(self.spec.config.get("at", 0))
        if tick >= at and (tick - at) % max(1, every) == 0:
            for link in self.rt.team.links_from(self.id, "feeds"):
                self.rt.wake(link.dst, "schedule")


class StreamNode(Node):
    """Pulls the tick's items from a feed (`rt.feeds[config.feed]`) and passes each to the router
    it feeds; with no router, straight to the owners of what the item is about."""

    kind = "source"
    description = "Pulls items from a feed (config: feed, when) and hands them to a router."

    def __init__(self, spec: NodeSpec, runtime: Runtime):
        super().__init__(spec, runtime)
        self.buffer: list[Item] = []

    def tick_start(self, tick: int) -> None:
        if self.spec.config.get("when") == "start":  # items arrive as the tick begins
            self._pull(tick)
            self._hand_on()

    def _pull(self, tick: int) -> None:
        feed = self.rt.feeds.get(str(self.spec.config.get("feed", self.id)))
        if feed is not None:
            self.buffer.extend(feed(tick))

    def tick_end(self, tick: int, stage: Stage) -> None:
        if self.spec.config.get("when") == "start":
            return
        if stage == "step":
            self._pull(tick)
        elif stage == "observe":
            self._hand_on()

    def _hand_on(self) -> None:
        items, self.buffer = self.buffer, []
        routers = [
            node
            for link in self.rt.team.links_from(self.id, "feeds")
            if isinstance(node := self.rt.nodes.get(link.dst), RouterNode)
        ]
        for item in items:
            if routers:
                for router in routers:
                    router.receive(item)
            else:
                self.rt.route(item, recipients(self.rt, item, None))


def recipients(rt: Runtime, item: Item, fallback: str | None) -> list[str]:
    found: list[str] = list(item.to or [])
    for entity in item.about:
        for owner in rt.owners(entity):
            if owner not in found:
                found.append(owner)
    if not found and fallback:
        found.append(fallback)
    return found


# (runtime, item) -> the item with `about` and `claims` filled in
Extractor = Callable[[Runtime, Item], Item]


class RouterNode(Node):
    """Links an item to the entities it is about (with the pack's extractor when the item does not
    say), then delivers it to their owners. Items about nothing anyone owns go to `fallback`."""

    description = "Links items to entities and delivers them to the owners (config: fallback)."

    def receive(self, item: Item) -> None:
        extract: Extractor | None = getattr(self.rt.pack, "extract", None)
        if extract is not None and (not item.about or not item.claims):
            item = extract(self.rt, item)
        self.rt.route(item, recipients(self.rt, item, self.spec.config.get("fallback")))


# ---- model agents --------------------------------------------------------------------------------


class FrameToolbox(Toolbox):
    """The core toolbox, with a retraction that goes through the runtime, so the change is logged
    and reaches every copy the node passed on. Same names, descriptions and arguments."""

    def __init__(self, runtime: Runtime, viewer: str, executor: Callable[[Action], str]):
        super().__init__(
            runtime.store,
            viewer,
            runtime.pack.predicates,
            runtime.pack.templates,
            runtime.ids,
            transport=runtime.send,
            executor=executor,
        )
        self.rt = runtime

    def retract(self, belief_id: str, reason: str = "") -> str:
        """Withdraw one of your own beliefs. Anything resting on it is flagged for re-checking."""
        try:
            changes = self.rt.retract(self.viewer, belief_id, self.now, reason)
        except (ValueError, KeyError) as error:
            return f"error: {error.args[0] if error.args else error}"
        flagged = [c.belief_id for c in changes if c.new_status == "suspect"]
        return f"retracted {belief_id}" + (
            f"; flagged for re-checking: {' '.join(flagged)}" if flagged else ""
        )


class AgentNode(Node):
    """A language-model agent. It wakes on its triggers, reads a context compiled from the graph
    (never its own history), and acts through the graph tools and its own tools."""

    kind = "model"
    description = "A model agent: role, triggers, its own tools and the shared graph tools."
    default_triggers: ClassVar[tuple[TriggerKind, ...]] = ("tick",)

    def __init__(self, spec: NodeSpec, runtime: Runtime):
        super().__init__(spec, runtime)
        self.last_turn: int | None = None
        self.box = FrameToolbox(runtime, spec.id, self._execute)

    def _execute(self, action: Action) -> str:
        execute: Callable[[Action], str] | None = getattr(self.rt.pack, "execute", None)
        if execute is None:
            return "recorded (nothing executes it)"
        return execute(action)

    def start(self) -> None:
        self.rt.ensure_agent(self.id, self.spec.role or self.spec.type)

    # ---- when it runs -------------------------------------------------------------------------

    def wants_turn(self, tick: int) -> bool:
        pending = self.rt.pending.get(self.id, set())
        triggers = self.spec.triggers or [Trigger(on=kind) for kind in self.default_triggers]
        for trigger in triggers:
            if trigger.on == "tick":
                return True
            if trigger.on == "schedule":
                every = max(1, trigger.every)
                if "schedule" in pending or (
                    tick >= trigger.at and (tick - trigger.at) % every == 0
                ):
                    return True
            elif trigger.on == "due":
                if self._due(tick, trigger.within, trigger.predicate):
                    return True
            elif trigger.on in pending:
                return True
        return False

    def _due(self, tick: int, within: int, predicate: str | None) -> bool:
        owned = set(self.rt.owned_entities(self.id))
        for belief in self.rt.store.beliefs(self.id, predicate=predicate):
            if belief.status not in LIVE or (owned and belief.subject not in owned):
                continue
            if isinstance(belief.value, int | float) and not isinstance(belief.value, bool):
                if tick <= belief.value <= tick + within:
                    return True
        return False

    # ---- the turn -----------------------------------------------------------------------------

    def tools(self) -> ToolSet:
        extra: list[ToolSpec] = []
        for tool in self.rt.tools_for(self.spec):
            if tool.outward:
                extra.append(_gated(self.rt, self.id, tool))
            elif tool.observes is not None:
                extra.append(_checking(self.rt, self.id, tool))
            else:
                extra.append(tool)
        return ToolSet(self.box, self.spec.graph_tools, extra)

    def context(self, tick: int) -> str:
        return self.rt.pack.context(self.spec, tick, self.rt.settings.budget)

    def system_prompt(self) -> str:
        prompt: Callable[[NodeSpec], str] | None = getattr(self.rt.pack, "system_prompt", None)
        return prompt(self.spec) if prompt is not None else SYSTEM_PROMPT

    def turn(self, tick: int) -> None:
        rt, trace = self.rt, self.rt.trace
        context = self.context(tick)
        tools = self.tools()
        tools.now = tick
        trace.bind(agent=self.id)
        trace.emit(
            "turn_start",
            context_tokens=estimate_tokens(context),
            context=context if trace.contexts else None,
        )
        woke = sorted(rt.pending.get(self.id, set()))
        calls: list[dict[str, Json]] = []

        def on_call(name: str, arguments: dict[str, Json], output: str, text: str) -> None:
            calls.append({"tool": name, "arguments": arguments, "result": output, "text": text})
            rt.log.emit(
                tick, "tool", node=self.id, tool=name, arguments=arguments, result=output, text=text
            )

        assert rt.client is not None, "a run with model nodes needs a model client"
        result = run_node_turn(
            rt.client,
            tools,
            context,
            rt.settings.max_steps,
            trace,
            system=self.system_prompt(),
            on_call=on_call,
        )
        rt.turns.append((tick, self.id, result))
        if getattr(rt, "_approvals", None) is not None:
            approvals(rt).reviewed(self.id)
        trace.emit(
            "turn_end",
            steps=result.steps,
            hit_step_cap=result.hit_step_cap,
            tool_calls=len(result.calls),
            tool_errors=sum(out.startswith("error") for _, _, out in result.calls),
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            final_text=result.final_text,
        )
        trace.unbind("agent")
        rt.log.emit(
            tick,
            "turn",
            node=self.id,
            woke=woke,
            context=context,
            steps=result.steps,
            calls=calls,
            text=result.final_text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
        )
        self.last_turn = tick


def _gated(rt: Runtime, node: str, tool: ToolSpec) -> ToolSpec:
    """The tool as the model sees it: it takes `depends_on` too, and calling it makes a proposal."""
    schema: dict[str, Json] = dict(tool.input_schema)
    given = schema.get("properties")
    properties: dict[str, Json] = dict(given) if isinstance(given, dict) else {}
    properties["depends_on"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": "the ids of your beliefs this action rests on; it is held if they change",
    }
    schema["properties"] = properties
    return ToolSpec(
        name=tool.name,
        description=tool.description + " (Outward: may wait for a person's approval.)",
        input_schema=schema,
        handler=lambda arguments: approvals(rt).submit(node, tool, arguments),
        outward=True,
    )


def _checking(rt: Runtime, node: str, tool: ToolSpec) -> ToolSpec:
    """A checking tool: what its result establishes is recorded as evidence for the caller."""
    observes = tool.observes
    assert observes is not None

    def handler(arguments: dict[str, Any]) -> str:
        result = tool.handler(arguments)
        claims = observes(arguments, result)
        if claims:
            rt.checks += 1
            item = Item(
                id=f"T{rt.checks}",
                kind="check",
                tick=rt.tick,
                source=f"tool:{tool.name}",
                about=sorted({subject for subject, _, _ in claims}),
                to=[node],
                payload={"tool": tool.name, "arguments": arguments},
                claims=claims,
            )
            rt.route(item, [node])
        return result

    return ToolSpec(tool.name, tool.description, tool.input_schema, handler)


class ResponderNode(AgentNode):
    """An agent that acts on cascades: it wakes when a belief of a node it watches changes, or an
    action resting on one is held. Its own beliefs are copies of what it watches."""

    description = "Wakes on cascades in the nodes it watches; replans or takes follow-up actions."
    default_triggers: ClassVar[tuple[TriggerKind, ...]] = ("change",)

    def watches(self, node: str) -> bool:
        return any(link.dst == node for link in self.rt.team.links_from(self.id, "watches"))

    def start(self) -> None:
        super().start()
        self.rt.log.listen(self._on_event)

    def _on_event(self, event: Any) -> None:
        if event.kind == "change" and self.watches(str(event.data.get("viewer"))):
            self.rt.wake(self.id, "change")


# ---- checking claims ----------------------------------------------------------------------------


class CheckerNode(Node):
    """Tests what nodes were told against what they observed, and blames by the team's policy.

    * Evidence arrives: every told belief it contradicts is refuted.
    * A message arrives that contradicts evidence the receiver already holds: caught on arrival.
    * The tick is over: the pack says which claims expired unconfirmed (a deadline that passed).

    The pack supplies the words (`describe`) and the expiry rule (`expired`); the contradiction rule
    is the predicate registry, as everywhere else.
    """

    description = "Refutes told claims that evidence contradicts, and claims that expired."

    def viewers(self) -> list[str]:
        watched = [link.dst for link in self.rt.team.links_from(self.id, "watches")]
        if watched:
            return watched
        return [n.id for n in self.rt.nodes.values() if n.kind in ("model", "scripted")]

    def _describe(self, belief: Belief, evidence: Belief) -> str:
        describe = getattr(self.rt.pack, "describe_refutation", None)
        if describe is not None:
            return describe(belief, evidence)
        return (
            f"said {belief.subject} {belief.predicate} = {belief.value}; observed {evidence.value}"
        )

    def _distrust(
        self, viewer: str, evidence: Belief, tick: int, checked_at: int | None = None
    ) -> None:
        routes: dict[str, list[tuple[str, ...]]] = {}
        blames = blame_for_evidence(
            self.rt.store,
            viewer,
            evidence,
            self.rt.pack.predicates,
            self._describe,
            self.rt.settings.blame,
            getattr(self.rt.pack, "claim_window", None),
            checked_at,
            routes,
        )
        self.rt.distrust(viewer, blames, tick, routes=routes)

    def observed(self, viewer: str, belief: Belief, item: Item) -> None:
        if viewer not in self.viewers():
            return
        if belief.origin == "observed":  # checked just now, whenever it was first recorded
            self._distrust(viewer, belief, self.rt.tick, item.tick)
            return
        # a told item that contradicts evidence the viewer already holds is caught on arrival
        same = self.rt.store.beliefs(viewer, subject=belief.subject, predicate=belief.predicate)
        for known in same:
            if known.origin == "observed" and known.status in LIVE:
                self._distrust(viewer, known, self.rt.tick)

    def delivered(self, delivery: Delivery) -> None:
        belief = delivery.belief
        if belief is None:
            return
        viewer = delivery.message.receiver
        for known in self.rt.store.beliefs(
            viewer, subject=belief.subject, predicate=belief.predicate
        ):
            if known.origin == "observed" and known.status in LIVE:
                self._distrust(viewer, known, delivery.message.tick)

    def tick_end(self, tick: int, stage: Stage) -> None:
        if stage != "after_observe":
            return
        expired: Callable[[str, int, dict[str, list[tuple[str, ...]]]], list[Blame]] | None
        expired = getattr(self.rt.pack, "expired", None)
        if expired is None:
            return
        for viewer in self.viewers():
            routes: dict[str, list[tuple[str, ...]]] = {}
            self.rt.distrust(viewer, expired(viewer, tick, routes), tick, routes=routes)


# ---- group correction ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Warning:
    """`sender` tells `receiver` that `accused` lies; `reporters` caught it first-hand."""

    sender: str
    receiver: str
    accused: str
    reporters: frozenset[str]
    day: int  # sent at the end of this tick, delivered at the end of the next


class WarnerNode(Node):
    """Group correction. A node that catches a liar first-hand (the false claim came straight from
    them, so nobody else can be to blame) warns the peers it still trusts; a warning travels one hop
    a tick. A receiver ignores a warning from someone it caught lying; once `quorum` independent
    reporters agree, it distrusts the accused too, and passes the warning on.

    The pack decides when a first-hand claim is refuted (`refuted(viewer, message, tick)`).
    """

    description = "Spreads word of exposed nodes to trusted peers; acts once a quorum agrees."

    def __init__(self, spec: NodeSpec, runtime: Runtime):
        super().__init__(spec, runtime)
        quorum = spec.config.get("quorum", runtime.settings.quorum)
        self.quorum: int | None = None if quorum is None else int(quorum)
        self.warnings: list[Warning] = []
        self._outbox: list[Warning] = []
        self.reporters: dict[tuple[str, str], set[str]] = {}
        self._first_hand: list[Delivery] = []
        self._warned: set[tuple[str, str]] = set()
        self.caught: set[tuple[str, str]] = set()

    def delivered(self, delivery: Delivery) -> None:
        if len(delivery.message.route) == 1:  # the sender made this claim itself
            self._first_hand.append(delivery)

    def tick_end(self, tick: int, stage: Stage) -> None:
        if stage == "before_observe":
            self._deliver(tick)
        elif stage == "after_observe" and self.quorum is not None:
            self._warn_about_first_hand_liars(tick)

    def _honest(self, node: str) -> bool:
        found = self.rt.nodes.get(node)
        return found is not None and found.kind != "scripted"

    def _warn_about_first_hand_liars(self, tick: int) -> None:
        refuted: Callable[[str, Outgoing, int], str | None] | None = getattr(
            self.rt.pack, "refuted", None
        )
        if refuted is None:
            return
        for delivery in self._first_hand:
            message = delivery.message
            viewer, accused = message.receiver, message.sender
            if (viewer, accused) in self._warned:
                continue
            why = refuted(viewer, message, tick)
            if why is None:
                continue
            self._warned.add((viewer, accused))
            self.caught.add((viewer, accused))
            self.rt.distrust(viewer, [(accused, why)], tick)
            self.reporters.setdefault((viewer, accused), set()).add(viewer)
            self._warn_neighbours(viewer, accused, frozenset({viewer}), tick, came_from=None)

    def _trusted_neighbours(self, viewer: str) -> list[str]:
        return [n for n in self.rt.network.neighbours(viewer) if (viewer, n) not in self.caught]

    def _warn_neighbours(
        self, viewer: str, accused: str, reporters: frozenset[str], tick: int, came_from: str | None
    ) -> None:
        for neighbour in self._trusted_neighbours(viewer):
            if neighbour in (accused, came_from):
                continue
            warning = Warning(viewer, neighbour, accused, reporters, tick)
            self.warnings.append(warning)
            self._outbox.append(warning)
            self.rt.log.emit(
                tick,
                "warning",
                sender=viewer,
                receiver=neighbour,
                accused=accused,
                reporters=sorted(reporters),
            )

    def _deliver(self, tick: int) -> None:
        due = [w for w in self._outbox if w.day < tick]
        self._outbox = [w for w in self._outbox if w.day >= tick]
        for warning in due:
            self._receive(warning, tick)

    def _receive(self, warning: Warning, tick: int) -> None:
        viewer, accused = warning.receiver, warning.accused
        if not self._honest(viewer):
            return  # a liar does not pass warnings on
        if (viewer, warning.sender) in self.caught:
            return  # from someone it has caught lying
        trusted = {r for r in warning.reporters if (viewer, r) not in self.caught}
        known = self.reporters.setdefault((viewer, accused), set())
        known |= trusted
        if (viewer, accused) in self._warned or self.quorum is None:
            return  # it has passed this on already
        if len(known) < self.quorum:
            return
        self._warned.add((viewer, accused))
        self.caught.add((viewer, accused))
        self.rt.distrust(viewer, [(accused, "warned by " + ", ".join(sorted(known)))], tick)
        self._warn_neighbours(viewer, accused, frozenset(known), tick, came_from=warning.sender)


# ---- scripted -----------------------------------------------------------------------------------

Script = Callable[[Node, int], None]


class ScriptedNode(Node):
    """Runs `rt.scripts[config.script]` on its turn, every tick. Never uses a model."""

    kind = "scripted"
    description = "Runs a script each tick (fixtures, the game's imposters)."

    def start(self) -> None:
        self.rt.ensure_agent(self.id, self.spec.role or "scripted")

    def wants_turn(self, tick: int) -> bool:
        return True

    def turn(self, tick: int) -> None:
        scripts: dict[str, Script] = getattr(self.rt, "scripts", {})
        script = scripts.get(str(self.spec.config.get("script", self.id)))
        if script is not None:
            script(self, tick)


CATALOGUE: dict[str, NodeFactory] = {
    "schedule": ScheduleNode,
    "stream": StreamNode,
    "router": RouterNode,
    "agent": AgentNode,
    "responder": ResponderNode,
    "checker": CheckerNode,
    "warner": WarnerNode,
    "scripted": ScriptedNode,
}


def catalogue_info() -> list[dict[str, str]]:
    """What the canvas shows in its palette: each node type, its kind and what it does."""
    return [
        {
            "type": name,
            "kind": str(getattr(factory, "kind", "code")),
            "description": str(getattr(factory, "description", "")),
        }
        for name, factory in CATALOGUE.items()
    ]
