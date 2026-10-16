"""The tools an agent can call. The same eight, with the same names and behaviour, whichever store
backs them: only the backend differs between the graph setup and the SQL setup.

    recall          list what I believe, filtered
    explain         why do I hold this belief: its routes, what it came from, what depends on it
    traverse        which entities are near this one
    shortest_path   cost of the cheapest path between two entities
    assert_belief   record something I worked out, saying what it depends on
    retract         withdraw one of my beliefs
    send            tell another agent one of my beliefs
    act             commit to an action

Every tool returns text, which is what the model reads. A bad call (unknown id, missing
dependency, ...) returns a line starting "error:" and changes nothing, so the model can correct
itself and the run does not crash.

`send` and `act` reach outside the knowledge graph (they affect the game), so the harness passes in
the functions that do that. The core knows nothing about what a message or an action means.
"""

from collections.abc import Callable, Mapping, Sequence
from functools import wraps
from typing import Any, Concatenate, cast, get_args

from .compiler import render_belief
from .ids import Ids
from .model import Action, Belief, BeliefStatus, Edge, Entity
from .registry import Predicate
from .store import Store

_LIVE = ("active", "suspect")

# (sender, receiver, belief) -> text for the model. Raise ValueError to refuse.
Transport = Callable[[str, str, Belief], str]
# (action) -> text for the model. Raise ValueError to refuse.
Executor = Callable[[Action], str]

TOOL_NAMES = (
    "recall",
    "explain",
    "traverse",
    "shortest_path",
    "assert_belief",
    "retract",
    "send",
    "act",
)


def _tool[**P](
    method: Callable[Concatenate["Toolbox", P], str],
) -> Callable[Concatenate["Toolbox", P], str]:
    """Turn a refusal (ValueError, KeyError) into an "error:" line instead of an exception."""

    @wraps(method)
    def wrapper(self: "Toolbox", *args: P.args, **kwargs: P.kwargs) -> str:
        try:
            return method(self, *args, **kwargs)
        except (ValueError, KeyError) as error:
            return f"error: {error.args[0] if error.args else error}"

    return wrapper


class Toolbox:
    """One agent's tools. `ids` must be the same Ids the adapter uses, or the two would hand out
    the same id (B1, B2, ...) for different nodes."""

    names = TOOL_NAMES  # which tools this toolbox offers (a model is shown exactly these)

    def __init__(
        self,
        store: Store,
        viewer: str,
        predicates: Mapping[str, Predicate],
        templates: Mapping[str, str],
        ids: Ids,
        transport: Transport | None = None,
        executor: Executor | None = None,
    ):
        self.store = store
        self.viewer = viewer
        self.predicates = predicates
        self.templates = templates
        self.ids = ids
        self.transport = transport
        self.executor = executor
        self.now = 0  # the harness sets this to the current tick each turn

    # ---- helpers -------------------------------------------------------------------------------

    def _belief(self, belief_id: str) -> Belief:
        belief = self.store.get(self.viewer, belief_id)
        if not isinstance(belief, Belief):
            raise ValueError(f"{belief_id} is not one of your beliefs")
        return belief

    def _line(self, belief: Belief) -> str:
        routes = self.store.support_routes(self.viewer, belief.id)
        return render_belief(belief, routes, self.templates)

    # ---- reading -------------------------------------------------------------------------------

    @_tool
    def recall(
        self, subject: str | None = None, predicate: str | None = None, status: str | None = None
    ) -> str:
        """List your beliefs, filtered. Without `status`, only the ones that are still live."""
        if status is not None and status not in get_args(BeliefStatus):
            raise ValueError(f"status must be one of {', '.join(get_args(BeliefStatus))}")
        found = self.store.beliefs(
            self.viewer, subject, predicate, cast(BeliefStatus | None, status)
        )
        if status is None:
            found = [b for b in found if b.status in _LIVE]
        if not found:
            return "nothing matches"
        return "\n".join(self._line(b) for b in found[:30]) + (
            f"\n(+{len(found) - 30} more)" if len(found) > 30 else ""
        )

    @_tool
    def explain(self, belief_id: str) -> str:
        """Why you hold a belief: what it says, how it reached you, what it came from, what rests
        on it, and what has happened to it."""
        belief = self._belief(belief_id)
        lines = [self._line(belief)]
        for source in self.store.sources(self.viewer, belief_id):
            parent = self.store.belief(self.viewer, source)
            lines.append(f"  derived from {source} ({parent.status if parent else 'unknown'})")
        for dependent, hops in self.store.dependents(self.viewer, belief_id).items():
            node = self.store.get(self.viewer, dependent)
            kind = "belief" if isinstance(node, Belief) else "action"
            state = node.status if isinstance(node, Belief | Action) else "unknown"
            lines.append(f"  {kind} {dependent} ({state}) rests on it, {hops} step(s) down")
        for change in self.store.changes_since(self.viewer, 0):
            if change.belief_id == belief_id:
                lines.append(
                    f"  tick {change.tick}: became {change.new_status} because of "
                    f"{change.correction_type} of {change.target}"
                    + (f" ({change.reason})" if change.reason else "")
                )
        return "\n".join(lines)

    @_tool
    def traverse(self, entity: str, hops: int = 2) -> str:
        """The entities within `hops` steps of `entity`, nearest first (up to 6 steps)."""
        found = self.store.entity_distances([entity], min(max(hops, 1), 6))
        if entity not in found:
            raise ValueError(f"unknown entity {entity}")
        rings: dict[int, list[str]] = {}
        for node_id, distance in sorted(found.items()):
            rings.setdefault(distance, []).append(node_id)
        return "\n".join(f"{d} step(s): {' '.join(ids)}" for d, ids in sorted(rings.items()))

    @_tool
    def shortest_path(self, src: str, dst: str) -> str:
        """The cost of the cheapest path from one entity to another along known connections."""
        cost = self.store.shortest_distance(src, dst)
        return f"no known path from {src} to {dst}" if cost is None else f"cost {cost:g}"

    # ---- writing -------------------------------------------------------------------------------

    @_tool
    def assert_belief(
        self,
        subject: str,
        predicate: str,
        value: Any,
        depends_on: Sequence[str],
        confidence: float = 1.0,
        unit: str | None = None,
    ) -> str:
        """Record something you worked out. You must say which of your beliefs it depends on, so
        that if one of them is corrected this belief is flagged too."""
        if predicate not in self.predicates:
            raise ValueError(f"unknown predicate {predicate}; known: {sorted(self.predicates)}")
        if not isinstance(self.store.get(self.viewer, subject), Entity):
            raise ValueError(f"unknown entity {subject}")
        if not depends_on:
            raise ValueError("depends_on is required: name the beliefs this rests on")
        for source_id in depends_on:
            if self._belief(source_id).status not in _LIVE:
                raise ValueError(f"{source_id} is no longer sound, so nothing can rest on it")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

        belief = Belief(
            id=self.ids.next("B"),
            owner=self.viewer,
            subject=subject,
            predicate=predicate,
            value=value,
            unit=unit,
            origin="derived",
            kind="assessment",
            confidence=confidence,
            created_tick=self.now,
            updated_tick=self.now,
        )
        self.store.add_node(belief)
        self.store.add_edge(
            Edge(kind="ABOUT", src=belief.id, dst=subject, props={"role": "subject"})
        )
        for source_id in depends_on:
            self.store.add_edge(
                Edge(
                    kind="DERIVED_FROM",
                    src=belief.id,
                    dst=source_id,
                    props={"via": "assert_belief", "tick": self.now},
                )
            )
        reply = f"recorded {belief.id}"
        for other in self.store.conflicts(self.viewer, belief.id, self.predicates):
            reply += f"\nnote: conflicts with {self._line(other)}"
        return reply

    @_tool
    def retract(self, belief_id: str, reason: str = "") -> str:
        """Withdraw one of your own beliefs. Anything resting on it is flagged for re-checking."""
        changes = self.store.retract(self.viewer, belief_id, self.now, reason)
        flagged = [c.belief_id for c in changes if c.new_status == "suspect"]
        return f"retracted {belief_id}" + (
            f"; flagged for re-checking: {' '.join(flagged)}" if flagged else ""
        )

    # ---- reaching the game ---------------------------------------------------------------------

    @_tool
    def send(self, to: str, belief_id: str) -> str:
        """Tell another agent one of your live beliefs. They will see the route it took."""
        if self.transport is None:
            raise ValueError("sending is not available")
        belief = self._belief(belief_id)
        if belief.status not in _LIVE:
            raise ValueError(f"{belief_id} is {belief.status}; do not pass it on")
        return self.transport(self.viewer, to, belief)

    @_tool
    def act(
        self,
        type: str,
        target: str | None = None,
        params: dict[str, Any] | None = None,
        depends_on: Sequence[str] = (),
    ) -> str:
        """Commit to an action. Name the beliefs it depends on, to be warned if they change."""
        for source_id in depends_on:
            self._belief(source_id)
        action = Action(
            id=self.ids.next("X"),
            owner=self.viewer,
            type=type,
            target=target,
            params=params or {},
            status="committed",
        )
        if self.executor is not None:
            reply = self.executor(
                action
            )  # may refuse by raising ValueError, before anything is stored
        else:
            reply = "recorded (nothing executes it)"
        self.store.add_node(action)
        for source_id in depends_on:
            self.store.add_edge(
                Edge(kind="DERIVED_FROM", src=action.id, dst=source_id, props={"tick": self.now})
            )
        return f"{action.id}: {reply}"
