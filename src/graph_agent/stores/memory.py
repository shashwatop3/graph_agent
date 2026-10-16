"""The reference store: plain Python dicts and lists, no database.

It is deliberately simple and slow. Its job is to define the right answer, so the FalkorDB and
Postgres stores can be checked against it.
"""

import heapq
from collections import deque

from ..core.model import (
    Action,
    Belief,
    BeliefStatus,
    Correction,
    Edge,
    EdgeKind,
    Node,
    Observation,
    check_edge,
    visible,
)
from ..core.store import Change, Invalidation, Store


class MemoryStore(Store):
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []

    # ---- writes ------------------------------------------------------------------------------

    def add_node(self, node: Node) -> None:
        if node.id in self._nodes:
            raise ValueError(f"node {node.id!r} already exists")
        self._nodes[node.id] = node.model_copy(deep=True)

    def add_edge(self, edge: Edge) -> None:
        for end in (edge.src, edge.dst):
            if end not in self._nodes:
                raise ValueError(f"node {end!r} does not exist")
        check_edge(edge, self._nodes[edge.src], self._nodes[edge.dst])
        self._edges.append(edge.model_copy(deep=True))

    # ---- reads -------------------------------------------------------------------------------

    def get(self, viewer: str, node_id: str) -> Node | None:
        node = self._nodes.get(node_id)
        if node is None or not visible(viewer, node):
            return None
        return node.model_copy(deep=True)

    def beliefs(self, viewer, subject=None, predicate=None, status=None) -> list[Belief]:
        found = [
            n.model_copy(deep=True)
            for n in self._nodes.values()
            if isinstance(n, Belief)
            and visible(viewer, n)
            and (subject is None or n.subject == subject)
            and (predicate is None or n.predicate == predicate)
            and (status is None or n.status == status)
        ]
        return sorted(found, key=lambda b: b.id)

    def support_routes(self, viewer: str, belief_id: str) -> list[tuple[str, ...]]:
        if self.get(viewer, belief_id) is None:
            return []
        return sorted(self._route(e.src) for e in self._edges_to(belief_id, "SUPPORTS"))

    def dependents(self, viewer: str, belief_id: str) -> dict[str, int]:
        if self.get(viewer, belief_id) is None:
            return {}
        return self._walk_dependents(viewer, [belief_id])

    def actions(self, viewer, status=None) -> list[Action]:
        found = [
            n.model_copy(deep=True)
            for n in self._nodes.values()
            if isinstance(n, Action)
            and visible(viewer, n)
            and (status is None or n.status == status)
        ]
        return sorted(found, key=lambda a: a.id)

    def observations(self, viewer: str, since_tick: int) -> list[Observation]:
        found = [
            n.model_copy(deep=True)
            for n in self._nodes.values()
            if isinstance(n, Observation) and visible(viewer, n) and n.received_tick >= since_tick
        ]
        return sorted(found, key=lambda o: (o.received_tick, o.id))

    def sources(self, viewer: str, node_id: str) -> list[str]:
        if self.get(viewer, node_id) is None:
            return []
        return sorted(e.dst for e in self._edges if e.src == node_id and e.kind == "DERIVED_FROM")

    def changes_since(self, viewer: str, since_tick: int) -> list[Change]:
        found = []
        for edge in self._edges:
            if edge.kind != "INVALIDATED" or edge.props["tick"] < since_tick:
                continue
            belief, correction = self._nodes[edge.dst], self._nodes[edge.src]
            if visible(viewer, belief):
                found.append(
                    Change(
                        belief_id=edge.dst,
                        new_status=edge.props["new_status"],
                        path_len=edge.props["path_len"],
                        tick=edge.props["tick"],
                        correction_type=correction.type,
                        target=correction.target,
                        reason=correction.reason,
                    )
                )
        return sorted(found, key=lambda c: (c.tick, c.path_len, c.belief_id))

    def entity_distances(self, seeds, max_hops, kind="RELATES") -> dict[str, int]:
        distance = {s: 0 for s in seeds if s in self._nodes}
        queue = deque(distance)
        while queue:
            current = queue.popleft()
            if distance[current] == max_hops:
                continue
            for edge in self._edges:
                if edge.kind != kind or current not in (edge.src, edge.dst):
                    continue
                other = edge.dst if edge.src == current else edge.src
                if other not in distance:
                    distance[other] = distance[current] + 1
                    queue.append(other)
        return distance

    def retract(
        self, viewer: str, belief_id: str, tick: int, reason: str = ""
    ) -> list[Invalidation]:
        belief = self._nodes.get(belief_id)
        if not isinstance(belief, Belief) or not visible(viewer, belief):
            raise ValueError(f"{belief_id!r} is not one of {viewer}'s beliefs")
        if belief.status not in ("active", "suspect"):
            raise ValueError(f"{belief_id!r} is already {belief.status}")
        correction = Correction(
            id=self._next_correction_id(),
            type="retraction",
            issued_by=viewer,
            target=belief_id,
            tick=tick,
            reason=reason,
            observer=viewer,
        )
        self._nodes[correction.id] = correction
        changes = {belief_id: self._invalidate(correction, belief_id, "retracted", 1)}
        for dependent, hops in self._walk_dependents(viewer, [belief_id]).items():
            node = self._nodes[dependent]
            if isinstance(node, Belief) and node.status == "active":
                changes[dependent] = self._invalidate(correction, dependent, "suspect", 1 + hops)
        return sorted(changes.values(), key=lambda c: (c.path_len, c.belief_id))

    def shortest_distance(self, src: str, dst: str, kind: EdgeKind = "RELATES") -> float | None:
        # Dijkstra with a heap; `best` holds the cheapest known cost to each node.
        best = {src: 0.0}
        heap = [(0.0, src)]
        while heap:
            cost, node = heapq.heappop(heap)
            if node == dst:
                return cost
            if cost > best.get(node, float("inf")):
                continue  # a cheaper route to this node was already processed
            for edge in self._edges:
                if edge.kind == kind and edge.src == node:
                    new_cost = cost + edge.props.get("weight", 1)
                    if new_cost < best.get(edge.dst, float("inf")):
                        best[edge.dst] = new_cost
                        heapq.heappush(heap, (new_cost, edge.dst))
        return None

    # ---- propagation -------------------------------------------------------------------------

    def expose(self, viewer: str, agent_id: str, tick: int, reason: str = "") -> list[Invalidation]:
        before = self._exposed(viewer)
        correction = Correction(
            id=self._next_correction_id(),
            type="exposure",
            issued_by="engine",
            target=agent_id,
            tick=tick,
            reason=reason,
            observer=viewer,
        )
        self._nodes[correction.id] = correction
        exposed = before | {agent_id}

        # 1. Recount support. A belief that had a surviving route and now has none is stale.
        newly_stale: list[str] = []
        for belief in self._live_beliefs(viewer):
            routes = [self._route(e.src) for e in self._edges_to(belief.id, "SUPPORTS")]
            if not routes:
                continue  # derived belief: affected only through what it depends on
            belief.support_routes = sum(1 for r in routes if not exposed & set(r))
            had_support = any(not before & set(r) for r in routes)
            if had_support and belief.support_routes == 0:
                newly_stale.append(belief.id)

        changes = {}
        for belief_id in newly_stale:
            changes[belief_id] = self._invalidate(correction, belief_id, "stale", 1)

        # 2. Everything derived from a stale belief becomes suspect.
        for belief_id, hops in self._walk_dependents(viewer, newly_stale).items():
            node = self._nodes[belief_id]
            if isinstance(node, Belief) and node.status == "active":
                changes[belief_id] = self._invalidate(correction, belief_id, "suspect", 1 + hops)

        return sorted(changes.values(), key=lambda c: (c.path_len, c.belief_id))

    # ---- helpers -----------------------------------------------------------------------------

    def _next_correction_id(self) -> str:
        return f"C{sum(isinstance(n, Correction) for n in self._nodes.values()) + 1}"

    def _edges_to(self, node_id: str, kind: EdgeKind) -> list[Edge]:
        return [e for e in self._edges if e.dst == node_id and e.kind == kind]

    def _route(self, observation_id: str) -> tuple[str, ...]:
        hops = [e for e in self._edges if e.src == observation_id and e.kind == "RELAYED_VIA"]
        return tuple(e.dst for e in sorted(hops, key=lambda e: e.props.get("hop", 0)))

    def _exposed(self, viewer: str) -> set[str]:
        return {
            n.target
            for n in self._nodes.values()
            if isinstance(n, Correction) and n.type == "exposure" and visible(viewer, n)
        }

    def _live_beliefs(self, viewer: str) -> list[Belief]:
        """The viewer's beliefs that can still change status (the stored objects, not copies)."""
        return [
            n
            for n in self._nodes.values()
            if isinstance(n, Belief) and visible(viewer, n) and n.status in ("active", "suspect")
        ]

    def _walk_dependents(self, viewer: str, sources: list[str]) -> dict[str, int]:
        """Breadth-first walk against DERIVED_FROM edges. Returns node id -> fewest hops."""
        distance = {s: 0 for s in sources}
        queue = deque(sources)
        while queue:
            current = queue.popleft()
            for edge in self._edges_to(current, "DERIVED_FROM"):
                node = self._nodes[edge.src]
                if edge.src not in distance and visible(viewer, node):
                    distance[edge.src] = distance[current] + 1
                    queue.append(edge.src)
        return {k: v for k, v in distance.items() if k not in sources}

    def _invalidate(
        self, correction: Correction, belief_id: str, new_status: BeliefStatus, path_len: int
    ) -> Invalidation:
        belief = self._nodes[belief_id]
        change = Invalidation(
            belief_id=belief_id,
            old_status=belief.status,
            new_status=new_status,
            path_len=path_len,
        )
        belief.status = new_status
        belief.updated_tick = correction.tick
        self._edges.append(
            Edge(
                kind="INVALIDATED",
                src=correction.id,
                dst=belief_id,
                props={
                    "new_status": new_status,
                    "path_len": path_len,
                    "tick": correction.tick,
                },
            )
        )
        return change
