"""The graph store: the same Store interface, backed by FalkorDB and Cypher.

How the model maps onto the graph
  * Every node gets two labels: `Node` (so one index on `id` finds any node) and its own type
    (`Belief`, `Observation`, ...). Properties are the model's fields.
  * FalkorDB properties must be scalars, so fields that hold arbitrary values (a belief's `value`,
    an observation's `payload`, ...) are stored as JSON text and decoded on the way out. A field
    that is None is simply not stored.
  * Each of the nine relationship kinds is a relationship type of the same name. Their properties
    (`hop`, `path_len`, ...) must be scalars.

What is done by the database and what is not
  * The expensive part of `expose` (counting surviving routes per belief, and walking
    DERIVED_FROM edges backwards to find everything downstream of a stale belief) is Cypher.
  * Python only decides which beliefs became stale, because that needs the "before" and "after"
    counts side by side, and assembles the result list.

One FalkorDB graph holds one run. Use a different `graph_name` for a different run.
"""

import json
import os
import uuid
from collections.abc import Callable
from typing import Any, Protocol, cast

from falkordb import FalkorDB  # pyright: ignore[reportMissingTypeStubs]  # no type information

from ..core.model import (
    Action,
    ActionStatus,
    Agent,
    Belief,
    BeliefStatus,
    Correction,
    Edge,
    EdgeKind,
    Entity,
    Node,
    Observation,
    as_type,
    check_edge,
    visible,
)
from ..core.store import Change, Invalidation, Store, fold_exposed, plan_reinstatement

# Longest DERIVED_FROM chain the downstream walk will follow. Real chains are a handful of hops.
MAX_DEPTH = 32

_CLASSES: dict[str, Callable[..., Node]] = {
    c.__name__: c for c in (Agent, Observation, Entity, Belief, Action, Correction)
}

# Fields stored as JSON text, per node type (they can hold maps, lists or any value).
_JSON_FIELDS = {
    "Observation": ("payload",),
    "Entity": ("aliases", "props"),
    "Belief": ("value",),
    "Action": ("params",),
    "Correction": ("new_value",),
}


def _to_properties(node: Node) -> dict[str, Any]:
    """Model -> flat scalar properties."""
    data = node.model_dump()
    for name in _JSON_FIELDS.get(type(node).__name__, ()):
        data[name] = json.dumps(data[name], sort_keys=True)
    return {k: v for k, v in data.items() if v is not None}  # FalkorDB cannot store null


class DbNode(Protocol):
    """What we use of a node the FalkorDB client returns (the client has no type information)."""

    labels: list[str]
    properties: dict[str, Any]


def _from_node(db_node: DbNode) -> Node:
    """FalkorDB node -> model."""
    label = next(label for label in db_node.labels if label in _CLASSES)
    data = dict(db_node.properties)
    for name in _JSON_FIELDS.get(label, ()):
        data[name] = json.loads(data[name])
    return _CLASSES[label](**data)


class FalkorStore(Store):
    def __init__(
        self,
        graph_name: str | None = None,
        host: str | None = None,
        port: int | None = None,
        reset: bool = True,
        keep: bool = False,
    ):
        self._db = FalkorDB(
            host=host or os.environ.get("FALKORDB_HOST", "127.0.0.1"),
            port=port or int(os.environ.get("FALKORDB_PORT", "16379")),
        )
        self.graph_name = graph_name or f"store_{uuid.uuid4().hex[:10]}"
        self.keep = keep  # leave the graph in FalkorDB on close (a space that persists)
        if reset:
            self._drop()
        self._graph: Any = self._db.select_graph(self.graph_name)  # the client has no types
        # Indexes: every lookup by id, and "all beliefs of one agent" (the viewer filter).
        self._run("CREATE INDEX FOR (n:Node) ON (n.id)")
        self._run("CREATE INDEX FOR (b:Belief) ON (b.owner)")
        self._run("CREATE INDEX FOR (o:Observation) ON (o.received_by)")
        self._run("CREATE INDEX FOR (a:Action) ON (a.owner)")

    def close(self) -> None:
        if not self.keep:
            self._drop()

    def query(self, cypher: str, **params: Any) -> list[list[Any]]:
        """Run a read-only Cypher query against this run's graph (the console shows these)."""
        return [list(row) for row in self._graph.ro_query(cypher, params).result_set]

    def _drop(self) -> None:
        try:
            self._db.select_graph(self.graph_name).delete()
        except Exception:  # the graph does not exist yet
            pass

    def _run(self, query: str, **params: Any) -> list[list[Any]]:
        return cast(list[list[Any]], self._graph.query(query, params).result_set)

    def _node(self, node_id: str) -> Node | None:
        """A node by id, ignoring visibility (used internally)."""
        rows = self._run("MATCH (n:Node {id: $id}) RETURN n", id=node_id)
        return _from_node(rows[0][0]) if rows else None

    # ---- writes ------------------------------------------------------------------------------

    def add_node(self, node: Node) -> None:
        if self._node(node.id) is not None:
            raise ValueError(f"node {node.id!r} already exists")
        label = type(node).__name__  # taken from our own class names, so safe to put in the query
        self._run(f"CREATE (n:Node:{label}) SET n = $props", props=_to_properties(node))

    def add_edge(self, edge: Edge) -> None:
        src, dst = self._node(edge.src), self._node(edge.dst)
        if src is None:
            raise ValueError(f"node {edge.src!r} does not exist")
        if dst is None:
            raise ValueError(f"node {edge.dst!r} does not exist")
        check_edge(edge, src, dst)
        if not all(isinstance(v, str | int | float | bool) for v in edge.props.values()):
            raise ValueError("relationship properties must be scalars")
        # edge.kind is one of nine fixed names (checked by the model), so it is safe in the query
        self._run(
            f"MATCH (a:Node {{id: $src}}), (b:Node {{id: $dst}}) "
            f"CREATE (a)-[r:{edge.kind}]->(b) SET r = $props",
            src=edge.src,
            dst=edge.dst,
            props=edge.props,
        )

    # ---- reads -------------------------------------------------------------------------------

    def get(self, viewer: str, node_id: str) -> Node | None:
        node = self._node(node_id)
        return node if node is not None and visible(viewer, node) else None

    def beliefs(
        self,
        viewer: str,
        subject: str | None = None,
        predicate: str | None = None,
        status: BeliefStatus | None = None,
    ) -> list[Belief]:
        # Only add a condition for the filters that were given.
        conditions = ["b.owner = $viewer"]
        params: dict[str, Any] = {"viewer": viewer}
        for column, value in (("subject", subject), ("predicate", predicate), ("status", status)):
            if value is not None:
                conditions.append(f"b.{column} = ${column}")
                params[column] = value
        rows = self._run(
            f"MATCH (b:Belief) WHERE {' AND '.join(conditions)} RETURN b ORDER BY b.id", **params
        )
        return [as_type(_from_node(row[0]), Belief) for row in rows]

    def support_routes(self, viewer: str, belief_id: str) -> list[tuple[str, ...]]:
        if self.get(viewer, belief_id) is None:
            return []
        # One row per supporting observation; a sensor observation has no RELAYED_VIA edges, which
        # OPTIONAL MATCH turns into a single [null, null] pair that is dropped below.
        rows = self._run(
            "MATCH (o:Observation)-[:SUPPORTS]->(b:Belief {id: $id}) "
            "OPTIONAL MATCH (o)-[r:RELAYED_VIA]->(a:Agent) "
            "RETURN o.id, collect([r.hop, a.id])",
            id=belief_id,
        )
        routes: list[tuple[str, ...]] = []
        for _, hops in rows:
            ordered = sorted((hop, agent) for hop, agent in hops if agent is not None)
            routes.append(tuple(agent for _, agent in ordered))
        return sorted(routes)

    def dependents(self, viewer: str, belief_id: str) -> dict[str, int]:
        if self.get(viewer, belief_id) is None:
            return {}
        return {
            node_id: hops for node_id, (hops, _, _) in self._downstream(viewer, [belief_id]).items()
        }

    def _downstream(
        self, viewer: str, sources: list[str]
    ) -> dict[str, tuple[int, str, str | None]]:
        """Everything derived from any of `sources`: node id -> (fewest hops, node type, status).

        DERIVED_FROM points from the derived node to what it came from, so "downstream" means
        walking those edges backwards. It is a breadth-first search done one level per query: the
        frontier goes in as a list, the next frontier comes out. Only the viewer's own nodes are
        followed, as with the reference store.

        Why not one variable-length pattern, `(d)-[:DERIVED_FROM*1..32]->(s)`? That enumerates every
        path, and the number of paths grows exponentially when beliefs have several parents (a
        layered graph with two parents each has 2^depth paths). Measured in benchmarks/.
        """
        found: dict[str, tuple[int, str, str | None]] = {}
        seen = set(sources)
        frontier = list(sources)
        for hops in range(1, MAX_DEPTH + 1):
            if not frontier:
                break
            rows = self._run(
                "MATCH (s:Node)<-[:DERIVED_FROM]-(d) "
                "WHERE s.id IN $frontier AND d.owner = $viewer "
                "RETURN DISTINCT d.id, labels(d), d.status",
                frontier=frontier,
                viewer=viewer,
            )
            frontier: list[str] = []
            for node_id, labels, status in rows:
                if node_id not in seen:
                    seen.add(node_id)
                    label = next(name for name in labels if name != "Node")
                    found[node_id] = (hops, label, status)
                    frontier.append(node_id)
        return found

    def actions(self, viewer: str, status: ActionStatus | None = None) -> list[Action]:
        condition, params = "a.owner = $viewer", {"viewer": viewer}
        if status is not None:
            condition += " AND a.status = $status"
            params["status"] = status
        rows = self._run(f"MATCH (a:Action) WHERE {condition} RETURN a ORDER BY a.id", **params)
        return [as_type(_from_node(row[0]), Action) for row in rows]

    def observations(self, viewer: str, since_tick: int) -> list[Observation]:
        rows = self._run(
            "MATCH (o:Observation {received_by: $viewer}) WHERE o.received_tick >= $since "
            "RETURN o ORDER BY o.received_tick, o.id",
            viewer=viewer,
            since=since_tick,
        )
        return [as_type(_from_node(row[0]), Observation) for row in rows]

    def sources(self, viewer: str, node_id: str) -> list[str]:
        if self.get(viewer, node_id) is None:
            return []
        rows = self._run(
            "MATCH (n:Node {id: $id})-[:DERIVED_FROM]->(p) RETURN p.id ORDER BY p.id", id=node_id
        )
        return [row[0] for row in rows]

    def changes_since(self, viewer: str, since_tick: int) -> list[Change]:
        rows = self._run(
            "MATCH (c:Correction)-[r:INVALIDATED]->(b:Belief {owner: $viewer}) "
            "WHERE r.tick >= $since "
            "RETURN b.id, r.new_status, r.path_len, r.tick, c.type, c.target, c.reason "
            "ORDER BY r.tick, r.path_len, b.id",
            viewer=viewer,
            since=since_tick,
        )
        return [
            Change(
                belief_id=bid,
                new_status=status,
                path_len=path_len,
                tick=tick,
                correction_type=kind,
                target=target,
                reason=reason or "",
            )
            for bid, status, path_len, tick, kind, target, reason in rows
        ]

    def entity_distances(
        self, seeds: list[str], max_hops: int, kind: EdgeKind = "RELATES"
    ) -> dict[str, int]:
        # Breadth-first, one query per hop, ignoring edge direction (the pattern has no arrow).
        rows = self._run("MATCH (n:Node) WHERE n.id IN $seeds RETURN n.id", seeds=list(seeds))
        distance = {row[0]: 0 for row in rows}
        frontier = list(distance)
        for hops in range(1, max_hops + 1):
            if not frontier:
                break
            rows = self._run(
                f"MATCH (s:Node)-[:{kind}]-(n) WHERE s.id IN $frontier RETURN DISTINCT n.id",
                frontier=frontier,
            )
            frontier = [row[0] for row in rows if row[0] not in distance]
            distance.update({node_id: hops for node_id in frontier})
        return distance

    def shortest_distance(self, src: str, dst: str, kind: EdgeKind = "RELATES") -> float | None:
        if src == dst:
            return 0.0  # the procedure returns no path from a node to itself
        # algo.SPpaths is FalkorDB's weighted shortest path. A relationship without a `weight`
        # property costs 1, the same default as the reference store.
        rows = self._run(
            "MATCH (a:Node {id: $src}), (b:Node {id: $dst}) "
            f"CALL algo.SPpaths({{sourceNode: a, targetNode: b, relTypes: ['{kind}'], "
            "weightProp: 'weight', pathCount: 1}) YIELD pathWeight RETURN pathWeight",
            src=src,
            dst=dst,
        )
        return float(rows[0][0]) if rows else None

    # ---- propagation -------------------------------------------------------------------------

    def expose(self, viewer: str, agent_id: str, tick: int, reason: str = "") -> list[Invalidation]:
        # Agents this viewer already treats as exposed, before this call.
        before = sorted(self.exposed(viewer))
        exposed = sorted({*before, agent_id})

        correction_id = self._new_correction(
            type="exposure",
            issued_by="engine",
            target=agent_id,
            tick=tick,
            reason=reason,
            observer=viewer,
        )

        # 1. Recount support for every live belief that has supporting observations. A route is
        #    the list of agents its observation passed through; it survives if none is exposed.
        #    This also refreshes the cached `support_routes` count in the same query.
        rows = self._run(
            "MATCH (b:Belief {owner: $viewer}) WHERE b.status IN ['active', 'suspect'] "
            "MATCH (o:Observation)-[:SUPPORTS]->(b) "
            "OPTIONAL MATCH (o)-[:RELAYED_VIA]->(a:Agent) "
            "WITH b, o, collect(a.id) AS route "
            "WITH b, "
            "  sum(CASE WHEN size([x IN route WHERE x IN $before]) = 0 THEN 1 ELSE 0 END) "
            "    AS alive_before, "
            "  sum(CASE WHEN size([x IN route WHERE x IN $exposed]) = 0 THEN 1 ELSE 0 END) "
            "    AS alive_now "
            "SET b.support_routes = alive_now "
            "RETURN b.id, b.status, alive_before, alive_now",
            viewer=viewer,
            before=before,
            exposed=exposed,
        )
        # Stale = had at least one surviving route before and has none now.
        changes: dict[str, Invalidation] = {
            bid: Invalidation(belief_id=bid, old_status=status, new_status="stale", path_len=1)
            for bid, status, was, now in rows
            if was > 0 and now == 0
        }
        self._suspect_dependents(viewer, changes)
        self._write_changes(correction_id, changes, tick)
        return sorted(changes.values(), key=lambda c: (c.path_len, c.belief_id))

    def exposed(self, viewer: str) -> set[str]:
        rows = self._run(
            "MATCH (c:Correction) WHERE c.type IN ['exposure', 'reinstatement'] "
            "AND (c.observer IS NULL OR c.observer = $viewer) RETURN c.id, c.type, c.target",
            viewer=viewer,
        )
        return fold_exposed((row[0], row[1], row[2]) for row in rows)

    def reinstate(
        self, viewer: str, agent_id: str, tick: int, reason: str = ""
    ) -> list[Invalidation]:
        before = sorted(self.exposed(viewer))
        if agent_id not in before:
            return []
        changes = plan_reinstatement(self, viewer, agent_id)
        correction_id = self._new_correction(
            type="reinstatement",
            issued_by="engine",
            target=agent_id,
            tick=tick,
            reason=reason,
            observer=viewer,
        )
        self._write_changes(correction_id, changes, tick)
        self._run(  # refresh the cached count of routes that survive
            "MATCH (b:Belief {owner: $viewer}) WHERE b.status IN ['active', 'suspect'] "
            "MATCH (o:Observation)-[:SUPPORTS]->(b) "
            "OPTIONAL MATCH (o)-[:RELAYED_VIA]->(a:Agent) "
            "WITH b, o, collect(a.id) AS route "
            "WITH b, sum(CASE WHEN size([x IN route WHERE x IN $exposed]) = 0 THEN 1 ELSE 0 END) "
            "  AS alive "
            "SET b.support_routes = alive",
            viewer=viewer,
            exposed=sorted(set(before) - {agent_id}),
        )
        return sorted(changes.values(), key=lambda c: (c.path_len, c.belief_id))

    def retract(
        self, viewer: str, belief_id: str, tick: int, reason: str = ""
    ) -> list[Invalidation]:
        belief = self.get(viewer, belief_id)
        if not isinstance(belief, Belief):
            raise ValueError(f"{belief_id!r} is not one of {viewer}'s beliefs")
        if belief.status not in ("active", "suspect"):
            raise ValueError(f"{belief_id!r} is already {belief.status}")
        correction_id = self._new_correction(
            type="retraction",
            issued_by=viewer,
            target=belief_id,
            tick=tick,
            reason=reason,
            observer=viewer,
        )
        changes = {
            belief_id: Invalidation(
                belief_id=belief_id, old_status=belief.status, new_status="retracted", path_len=1
            )
        }
        self._suspect_dependents(viewer, changes)
        self._write_changes(correction_id, changes, tick)
        return sorted(changes.values(), key=lambda c: (c.path_len, c.belief_id))

    # ---- steps shared by expose and retract ----------------------------------------------------

    def _new_correction(self, **fields: Any) -> str:
        correction_id = f"C{self._run('MATCH (c:Correction) RETURN count(c)')[0][0] + 1}"
        self.add_node(Correction(id=correction_id, **fields))
        return correction_id

    def _suspect_dependents(self, viewer: str, changes: dict[str, Invalidation]) -> None:
        """Everything derived from a changed belief becomes suspect (if it was active)."""
        if not changes:
            return
        for bid, (hops, label, status) in self._downstream(viewer, list(changes)).items():
            if label == "Belief" and status == "active":
                changes[bid] = Invalidation(
                    belief_id=bid, old_status="active", new_status="suspect", path_len=1 + hops
                )

    def _write_changes(self, correction_id: str, changes: dict[str, Invalidation], tick: int):
        """Write all status changes and the INVALIDATED edges (correction -> belief) at once."""
        if not changes:
            return
        self._run(
            "UNWIND $changes AS ch "
            # match on :Node, not :Belief: the id index is on :Node, and a :Belief match would
            # scan every belief once per change
            "MATCH (c:Node {id: $cid}), (b:Node {id: ch.id}) "
            "SET b.status = ch.status, b.updated_tick = $tick "
            "CREATE (c)-[:INVALIDATED {new_status: ch.status, path_len: ch.path_len, "
            "tick: $tick}]->(b)",
            changes=[
                {"id": c.belief_id, "status": c.new_status, "path_len": c.path_len}
                for c in changes.values()
            ],
            cid=correction_id,
            tick=tick,
        )
