"""A generic pack: what any domain gets without writing its own rules.

A domain only has to name its predicates (and how each renders as a line). This pack then:

  * records an item's claims for each recipient. A claim from a source the domain trusts as ground
    truth ("observed": a sensor, the node's own calendar, a status check) is evidence; anything
    else (a mail, a message) is a told belief whose route starts at whoever said it, so that
    sender can be distrusted like any agent;
  * lets a source correct itself: a newer claim from the same source about the same thing retires
    the older one, and everything resting on the older one is flagged (one correction, every
    holder, every dependant);
  * compiles each node's context from the graph: its role, what changed, its inbox, its beliefs,
    plus any sections the domain adds.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..core.compiler import compile_context, estimate_tokens
from ..core.model import Belief, Edge, Entity, Observation
from ..core.registry import Predicate, contradicts
from .runtime import Item, Runtime
from .spec import NodeSpec

SYSTEM_PROMPT = (
    "You are one node in a team of agents that share a knowledge graph. You act only by calling "
    "tools. Your context is compiled from the graph each time you wake: it is all you know, so "
    "record what you work out (assert_belief, naming what it rests on) and pass on what others "
    "need (send). Every outward action names the beliefs it rests on (depends_on). When you are "
    "done, reply with one short sentence and no tool call."
)

# (node, tick, budget) -> extra context sections, as (heading, lines)
Section = Callable[[NodeSpec, int], Sequence[tuple[str, Sequence[str]]]]


class BasePack:
    name = "base"

    def __init__(
        self,
        predicates: Mapping[str, Predicate],
        templates: Mapping[str, str] | None = None,
        *,
        observed_sources: Sequence[str] = (),
        sections: Sequence[Section] = (),
        system_prompt: str = SYSTEM_PROMPT,
    ):
        self.predicates = dict(predicates)
        self.templates = dict(templates or {})
        self.observed_sources = set(observed_sources)  # whose items count as evidence
        self.sections = list(sections)
        self.prompt = system_prompt
        self.rt: Runtime | None = None
        # facts here change over time: evidence refutes only claims made this many ticks before
        # it at most (see policies.within); a newer check retires an older one
        self.claim_window: int | None = 1

    @property
    def runtime(self) -> Runtime:
        assert self.rt is not None, "attach the pack to a runtime first (pack.rt = runtime)"
        return self.rt

    # ---- recording ----------------------------------------------------------------------------

    def is_observed(self, item: Item) -> bool:
        """Ground truth: a system of record the domain names, or a checking tool's result."""
        return item.source in self.observed_sources or item.source.startswith("tool:")

    def record_item(self, viewer: str, item: Item) -> list[Belief]:
        rt = self.runtime
        observed = self.is_observed(item)
        observation = Observation(
            id=rt.ids.next("O"),
            kind="evidence" if observed else "message",
            payload={"item": item.id, "kind": item.kind, **item.payload},
            received_by=viewer,
            sender=None if observed else item.source,
            about_tick=item.tick,
            received_tick=item.tick,
        )
        rt.store.add_node(observation)
        if not observed:
            rt.ensure_agent(item.source, "outside source")
            rt.store.add_edge(
                Edge(kind="RELAYED_VIA", src=observation.id, dst=item.source, props={"hop": 0})
            )
        for entity in item.about:
            if rt.store.get(viewer, entity) is not None:
                rt.store.add_edge(
                    Edge(kind="ABOUT", src=observation.id, dst=entity, props={"role": "mentioned"})
                )
        if not observed and item.source in rt.distrusted(viewer):
            return []
        beliefs: list[Belief] = []
        for subject, predicate, value in item.claims:
            if rt.store.get(viewer, subject) is None:
                rt.ensure_entity(subject, "Thing", name=subject)
            belief = rt.believe(
                viewer,
                subject,
                predicate,
                value,
                "observed" if observed else "told",
                item.tick,
                observation.id,
            )
            beliefs.append(belief)
            if observed:
                self._newer_reading(viewer, belief, item)
            else:
                self._supersede(viewer, belief, item)
        return beliefs

    def _newer_reading(self, viewer: str, new: Belief, item: Item) -> None:
        """A fresh check retires an older one that says otherwise (the world moved on)."""
        rt = self.runtime
        for old in rt.store.beliefs(viewer, subject=new.subject, predicate=new.predicate):
            if (
                old.id == new.id
                or old.origin != "observed"
                or old.status not in ("active", "suspect")
            ):
                continue
            if contradicts(old, new, self.predicates):
                rt.retract(
                    viewer,
                    old.id,
                    item.tick,
                    f"a newer check ({item.source}) says {self.render(new)}",
                )

    def _supersede(self, viewer: str, new: Belief, item: Item) -> None:
        """A source changed its mind: retire what it said before about the same thing."""
        rt = self.runtime
        for old in rt.store.beliefs(viewer, subject=new.subject, predicate=new.predicate):
            if old.id == new.id or old.origin != "told" or old.status not in ("active", "suspect"):
                continue
            if not contradicts(old, new, self.predicates):
                continue
            routes = rt.store.support_routes(viewer, old.id)
            # who may update it: the entity's named authorities, or else only whoever said it
            authorities = self.authorities(new.subject) or {item.source}
            if (
                item.source in authorities
                and routes
                and all(route and route[0] in authorities for route in routes)
            ):
                rt.retract(
                    viewer,
                    old.id,
                    item.tick,
                    f"{item.source} updated it: now {self.render(new)} ({item.id})",
                )

    def authorities(self, subject: str) -> set[str]:
        """The sources allowed to update what is known about `subject` (its entity's
        "authorities"), besides whoever said it first."""
        entity = self.runtime.store.get("", subject)
        if not isinstance(entity, Entity):
            return set()
        found: list[object] = list(entity.props.get("authorities") or [])
        return {str(source) for source in found}

    # ---- reading ------------------------------------------------------------------------------

    def render(self, belief: Belief) -> str:
        template = self.templates.get(belief.predicate)
        if template is None:
            return f"{belief.subject} {belief.predicate} = {belief.value}"
        return template.format(subject=belief.subject, value=belief.value)

    def role_card(self, node: NodeSpec) -> str:
        lines = [f"You are {node.id}: {node.role or node.type}."]
        if node.goals:
            lines.append(f"Goal: {node.goals}")
        peers = self.runtime.network.neighbours(node.id)
        if peers:
            lines.append(f"You can send beliefs to: {', '.join(peers)}.")
        owned = self.runtime.owned_entities(node.id)
        if owned:
            lines.append(f"You look after: {', '.join(owned[:20])}.")
        lines.append(
            "Predicates you can use: "
            + "; ".join(
                f"{name} ({self.templates.get(name, '{subject} = {value}')})"
                for name in sorted(self.predicates)
            )
            + "."
        )
        return "\n".join(lines)

    def context(self, node: NodeSpec, tick: int, budget: int) -> str:
        extra_parts: list[str] = []
        for section in self.sections:
            for heading, lines in section(node, tick):
                if lines:
                    extra_parts.append(f"## {heading}\n" + "\n".join(lines))
        extra = "\n\n".join(extra_parts)
        last = getattr(self.runtime.nodes.get(node.id), "last_turn", None)
        since = 0 if last is None else last  # its last turn's tick too: later news that tick
        compiled = compile_context(
            self.runtime.store,
            node.id,
            since,
            role_card=self.role_card(node),
            templates=self.templates,
            budget=max(0, budget - estimate_tokens(extra)),
        )
        clock = self.clock(tick)
        return "\n\n".join(p for p in (compiled, extra, clock) if p)

    def clock(self, tick: int) -> str:
        return f"It is tick {tick}."

    def system_prompt(self, node: NodeSpec) -> str:
        return self.prompt

    def describe_refutation(self, belief: Belief, evidence: Belief) -> str:
        return f"told {self.render(belief)}; checked: {self.render(evidence)}"

    def extra(self) -> dict[str, Any]:
        return {}
