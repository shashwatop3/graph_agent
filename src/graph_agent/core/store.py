"""The interface every store implements: a plain in-memory one, FalkorDB, and Postgres.

The in-memory store is the reference. The others must give the same answers. Every read takes the
`viewer`, so an agent can only ever read its own part of the graph.

Support and propagation rules (what `expose` does):
  * A belief's support is the set of observations that SUPPORT it. Each observation arrived by a
    route: the agents it passed through (its RELAYED_VIA edges, in hop order). Sensor and evidence
    observations have an empty route and always count.
  * Exposing agent X removes every route that passes through X. A belief that had at least one
    surviving route before and none now becomes STALE.
  * Every belief that is DERIVED_FROM a STALE belief, directly or through other beliefs, becomes
    SUSPECT (if it was ACTIVE) so its owner re-checks it.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from pydantic import BaseModel

from .model import Belief, BeliefStatus, Edge, EdgeKind, Node
from .registry import Predicate, contradicts


class Invalidation(BaseModel):
    """One belief whose status was changed by an exposure."""

    belief_id: str
    old_status: BeliefStatus
    new_status: BeliefStatus
    path_len: int  # 1 if directly stale, then +1 for each DERIVED_FROM hop away


class Store(ABC):
    def close(self) -> None:  # noqa: B027 (optional on purpose; most stores need nothing)
        """Release or delete whatever the store holds. Tests call this after each run."""

    @abstractmethod
    def add_node(self, node: Node) -> None: ...

    @abstractmethod
    def add_edge(self, edge: Edge) -> None:
        """Raises ValueError if an end does not exist or the kind cannot join those node types."""

    @abstractmethod
    def get(self, viewer: str, node_id: str) -> Node | None:
        """A copy of the node, or None if it does not exist or `viewer` may not see it."""

    @abstractmethod
    def beliefs(
        self,
        viewer: str,
        subject: str | None = None,
        predicate: str | None = None,
        status: BeliefStatus | None = None,
    ) -> list[Belief]:
        """The viewer's own beliefs, sorted by id, filtered by the arguments that are given."""

    @abstractmethod
    def support_routes(self, viewer: str, belief_id: str) -> list[tuple[str, ...]]:
        """One route per supporting observation, as agent ids in hop order. Sorted."""

    @abstractmethod
    def dependents(self, viewer: str, belief_id: str) -> dict[str, int]:
        """Beliefs and actions derived from this belief, directly or not, with their hop count."""

    @abstractmethod
    def shortest_distance(self, src: str, dst: str, kind: EdgeKind = "RELATES") -> float | None:
        """Total weight of the cheapest path from `src` to `dst` along `kind` edges, or None.

        Each edge costs its `weight` property (1 if it has none). A node is 0 away from itself.
        Entities and the RELATES edges between them are shared knowledge, so there is no viewer.
        """

    @abstractmethod
    def expose(self, viewer: str, agent_id: str, tick: int, reason: str = "") -> list[Invalidation]:
        """Record that `agent_id` is unreliable for `viewer` and propagate (see module docstring).

        Returns the beliefs whose status changed, sorted by (path_len, belief_id).
        """

    def conflicts(
        self, viewer: str, belief_id: str, predicates: Mapping[str, Predicate]
    ) -> list[Belief]:
        """The viewer's other beliefs that contradict this one."""
        belief = self.get(viewer, belief_id)
        if not isinstance(belief, Belief):
            return []
        same_claim = self.beliefs(viewer, subject=belief.subject, predicate=belief.predicate)
        return [other for other in same_claim if contradicts(belief, other, predicates)]
