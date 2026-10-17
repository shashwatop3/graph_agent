"""The SQL store: the same Store interface, backed by PostgreSQL and plain SQL.

This is the baseline the graph store is compared with, so it is written to be a good relational
design and not a strawman. No graph libraries (networkx and the like), only SQL.

Schema (one Postgres schema per store, so runs never share tables)
  nodes  one row per node. The columns that queries filter on or update are real, indexed columns
         (owner, subject, predicate, status, support_routes, updated_tick). Everything else lives in
         `data`, the node serialised as JSON.
  edges  one row per relationship: (kind, src, dst, props). Indexed on (kind, src) and (kind, dst),
         which are the two directions every traversal needs.

How `expose` maps to SQL (the same rules as the reference store)
  * Counting surviving routes per belief is one grouped query. A route is the array of agents an
    observation passed through, and it survives if it does not overlap (`&&`) the exposed agents.
  * The downstream walk is one `WITH RECURSIVE` query that follows DERIVED_FROM backwards and
    keeps the fewest hops per node.
"""

import json
import os
import uuid
from typing import Any, LiteralString, cast

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

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

# Longest DERIVED_FROM chain the recursive walk follows (also stops any accidental cycle).
MAX_DEPTH = 32

_CLASSES = {c.__name__: c for c in (Agent, Observation, Entity, Belief, Action, Correction)}

_SCHEMA = """
CREATE TABLE nodes (
    id             text PRIMARY KEY,
    type           text NOT NULL,
    owner          text,
    subject        text,
    predicate      text,
    status         text,
    support_routes integer,
    updated_tick   integer,
    data           jsonb NOT NULL
);
-- "this agent's beliefs about this subject" is the viewer filter plus the usual lookup
CREATE INDEX nodes_beliefs ON nodes (owner, subject, predicate) WHERE type = 'Belief';
-- "this agent's actions" and "what this agent received"
CREATE INDEX nodes_by_owner ON nodes (owner, type);

CREATE TABLE edges (
    id    bigserial PRIMARY KEY,
    kind  text NOT NULL,
    src   text NOT NULL REFERENCES nodes (id),
    dst   text NOT NULL REFERENCES nodes (id),
    props jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX edges_by_src ON edges (kind, src);
CREATE INDEX edges_by_dst ON edges (kind, dst);
"""

# For every supporting observation of every live belief of one viewer: the route (agents in hop
# order), then how many routes survive before and after the exposure. Used by expose().
_RECOUNT = """
WITH route AS (
    SELECT s.dst AS belief_id,
           s.src AS observation_id,
           coalesce(
               array_agg(r.dst ORDER BY coalesce((r.props ->> 'hop')::int, 0))
                   FILTER (WHERE r.dst IS NOT NULL),
               '{}'
           ) AS agents
    FROM edges s
    LEFT JOIN edges r ON r.kind = 'RELAYED_VIA' AND r.src = s.src
    WHERE s.kind = 'SUPPORTS'
    GROUP BY s.dst, s.src
),
counts AS (
    SELECT b.id,
           b.status,
           count(*) FILTER (WHERE NOT route.agents && %(before)s::text[]) AS alive_before,
           count(*) FILTER (WHERE NOT route.agents && %(exposed)s::text[]) AS alive_now
    FROM nodes b
    JOIN route ON route.belief_id = b.id
    WHERE b.type = 'Belief' AND b.owner = %(viewer)s AND b.status IN ('active', 'suspect')
    GROUP BY b.id, b.status
)
UPDATE nodes n
SET support_routes = counts.alive_now
FROM counts
WHERE n.id = counts.id
RETURNING n.id, counts.status, counts.alive_before, counts.alive_now
"""

# Everything derived from any of the sources, with the fewest DERIVED_FROM hops. The edge points
# from the derived node to its source, so we walk it backwards (match on dst, move to src).
# UNION (not UNION ALL) drops repeated (id, hops) pairs, and the depth limit guarantees an end.
_DOWNSTREAM = f"""
WITH RECURSIVE downstream (id, hops) AS (
    SELECT e.src, 1
    FROM edges e JOIN nodes d ON d.id = e.src
    WHERE e.kind = 'DERIVED_FROM' AND e.dst = ANY(%(sources)s) AND d.owner = %(viewer)s
  UNION
    SELECT e.src, downstream.hops + 1
    FROM downstream
    JOIN edges e ON e.kind = 'DERIVED_FROM' AND e.dst = downstream.id
    JOIN nodes d ON d.id = e.src
    WHERE d.owner = %(viewer)s AND downstream.hops < {MAX_DEPTH}
)
SELECT d.id, min(downstream.hops), d.type, d.status
FROM downstream JOIN nodes d ON d.id = downstream.id
WHERE d.id <> ALL(%(sources)s)
GROUP BY d.id, d.type, d.status
"""


class PostgresStore(Store):
    def __init__(self, dsn: str | None = None, schema: str | None = None):
        self.schema = schema or f"store_{uuid.uuid4().hex[:10]}"  # our own text, safe in SQL
        self._conn = psycopg.connect(
            dsn
            or os.environ.get(
                "POSTGRES_DSN", "postgresql://postgres:postgres@127.0.0.1:15432/graph_agent"
            ),
            autocommit=True,
        )
        self._conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self._conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        self._conn.execute(_SCHEMA)

    def analyze(self) -> None:
        """Refresh the planner's statistics. Call after loading a lot of data at once.

        Postgres plans from table statistics that it gathers in the background. Right after a bulk
        load they can be missing or stale, and the planner then sometimes picks a very slow plan
        (seen once in the benchmark: 54 s for a query that takes 1 s). A real deployment runs this
        through autovacuum; a benchmark that loads and queries immediately should do it explicitly.
        """
        self._conn.execute("ANALYZE")

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema))
            )
            self._conn.close()

    def _rows(self, query: str, **params: Any) -> list[tuple[Any, ...]]:
        # `query` is our own text (column names and %(name)s placeholders); values go in `params`
        return self._conn.execute(cast(LiteralString, query), params).fetchall()

    def _node(self, node_id: str) -> Node | None:
        """A node by id, ignoring visibility (used internally)."""
        rows = self._rows(
            "SELECT type, data, status, support_routes, updated_tick FROM nodes WHERE id = %(id)s",
            id=node_id,
        )
        if not rows:
            return None
        node_type, data, status, support_routes, updated_tick = rows[0]
        if node_type == "Belief":
            # status, support_routes and updated_tick change after creation, and only the
            # columns are updated, so they are the truth: overlay them on the stored JSON.
            data = {
                **data,
                "status": status,
                "support_routes": support_routes,
                "updated_tick": updated_tick,
            }
        return _CLASSES[node_type](**data)

    # ---- writes ------------------------------------------------------------------------------

    def add_node(self, node: Node) -> None:
        if self._node(node.id) is not None:
            raise ValueError(f"node {node.id!r} already exists")
        belief = node if isinstance(node, Belief) else None
        self._conn.execute(
            "INSERT INTO nodes (id, type, owner, subject, predicate, status, support_routes, "
            "updated_tick, data) VALUES (%(id)s, %(type)s, %(owner)s, %(subject)s, %(predicate)s, "
            "%(status)s, %(support_routes)s, %(updated_tick)s, %(data)s)",
            {
                "id": node.id,
                "type": type(node).__name__,
                "owner": getattr(node, "owner", None),
                "subject": getattr(node, "subject", None) if belief else None,
                "predicate": belief.predicate if belief else None,
                "status": belief.status if belief else None,
                "support_routes": belief.support_routes if belief else None,
                "updated_tick": belief.updated_tick if belief else None,
                "data": Jsonb(json.loads(node.model_dump_json())),
            },
        )

    def add_edge(self, edge: Edge) -> None:
        src, dst = self._node(edge.src), self._node(edge.dst)
        if src is None:
            raise ValueError(f"node {edge.src!r} does not exist")
        if dst is None:
            raise ValueError(f"node {edge.dst!r} does not exist")
        check_edge(edge, src, dst)
        self._conn.execute(
            "INSERT INTO edges (kind, src, dst, props) VALUES (%s, %s, %s, %s)",
            (edge.kind, edge.src, edge.dst, Jsonb(edge.props)),
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
        # Only add a condition for the filters that were given. Column names are our own literals.
        conditions = ["type = 'Belief'", "owner = %(viewer)s"]
        params: dict[str, Any] = {"viewer": viewer}
        for column, value in (("subject", subject), ("predicate", predicate), ("status", status)):
            if value is not None:
                conditions.append(f"{column} = %({column})s")
                params[column] = value
        ids = self._rows(
            f"SELECT id FROM nodes WHERE {' AND '.join(conditions)} ORDER BY id", **params
        )
        return [as_type(self._node(row[0]), Belief) for row in ids]

    def support_routes(self, viewer: str, belief_id: str) -> list[tuple[str, ...]]:
        if self.get(viewer, belief_id) is None:
            return []
        rows = self._rows(
            """
            SELECT coalesce(
                       array_agg(r.dst ORDER BY coalesce((r.props ->> 'hop')::int, 0))
                           FILTER (WHERE r.dst IS NOT NULL),
                       '{}')
            FROM edges s
            LEFT JOIN edges r ON r.kind = 'RELAYED_VIA' AND r.src = s.src
            WHERE s.kind = 'SUPPORTS' AND s.dst = %(id)s
            GROUP BY s.src
            """,
            id=belief_id,
        )
        return sorted(tuple(row[0]) for row in rows)

    def dependents(self, viewer: str, belief_id: str) -> dict[str, int]:
        if self.get(viewer, belief_id) is None:
            return {}
        rows = self._rows(_DOWNSTREAM, sources=[belief_id], viewer=viewer)
        return {node_id: hops for node_id, hops, _, _ in rows}

    def actions(self, viewer: str, status: ActionStatus | None = None) -> list[Action]:
        condition, params = "type = 'Action' AND owner = %(viewer)s", {"viewer": viewer}
        if status is not None:
            condition += " AND data ->> 'status' = %(status)s"
            params["status"] = status
        ids = self._rows(f"SELECT id FROM nodes WHERE {condition} ORDER BY id", **params)
        return [as_type(self._node(row[0]), Action) for row in ids]

    def observations(self, viewer: str, since_tick: int) -> list[Observation]:
        ids = self._rows(
            "SELECT id FROM nodes WHERE type = 'Observation' "
            "AND data ->> 'received_by' = %(viewer)s "
            "AND (data ->> 'received_tick')::int >= %(since)s "
            "ORDER BY (data ->> 'received_tick')::int, id",
            viewer=viewer,
            since=since_tick,
        )
        return [as_type(self._node(row[0]), Observation) for row in ids]

    def sources(self, viewer: str, node_id: str) -> list[str]:
        if self.get(viewer, node_id) is None:
            return []
        rows = self._rows(
            "SELECT dst FROM edges WHERE kind = 'DERIVED_FROM' AND src = %(id)s ORDER BY dst",
            id=node_id,
        )
        return [row[0] for row in rows]

    def changes_since(self, viewer: str, since_tick: int) -> list[Change]:
        rows = self._rows(
            """
            SELECT e.dst, e.props ->> 'new_status', (e.props ->> 'path_len')::int,
                   (e.props ->> 'tick')::int, c.data ->> 'type', c.data ->> 'target',
                   coalesce(c.data ->> 'reason', '')
            FROM edges e
            JOIN nodes c ON c.id = e.src
            JOIN nodes b ON b.id = e.dst
            WHERE e.kind = 'INVALIDATED' AND b.owner = %(viewer)s
              AND (e.props ->> 'tick')::int >= %(since)s
            ORDER BY (e.props ->> 'tick')::int, (e.props ->> 'path_len')::int, e.dst
            """,
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
                reason=reason,
            )
            for bid, status, path_len, tick, kind, target, reason in rows
        ]

    def entity_distances(
        self, seeds: list[str], max_hops: int, kind: EdgeKind = "RELATES"
    ) -> dict[str, int]:
        # One recursive query. The graph is walked in both directions, and each node keeps the
        # fewest hops; the hop limit also guarantees the recursion ends on a cyclic map.
        rows = self._rows(
            """
            WITH RECURSIVE reach (id, hops) AS (
                SELECT id, 0 FROM nodes WHERE id = ANY(%(seeds)s)
              UNION
                SELECT CASE WHEN e.src = reach.id THEN e.dst ELSE e.src END, reach.hops + 1
                FROM reach
                JOIN edges e ON e.kind = %(kind)s AND (e.src = reach.id OR e.dst = reach.id)
                WHERE reach.hops < %(max_hops)s
            )
            SELECT id, min(hops) FROM reach GROUP BY id
            """,
            seeds=list(seeds),
            kind=kind,
            max_hops=max_hops,
        )
        return dict(rows)

    def shortest_distance(self, src: str, dst: str, kind: EdgeKind = "RELATES") -> float | None:
        # Postgres has no shortest-path operator, so walk every simple path (the `path` array stops
        # a walk from revisiting a node, which also stops cycles) and take the cheapest.
        # That is fine for a field map, where there are few routes between two fields.
        if src == dst:
            return 0.0
        rows = self._rows(
            """
            WITH RECURSIVE walk (node, cost, path) AS (
                SELECT %(src)s::text, 0::float8, ARRAY[%(src)s]::text[]
              UNION ALL
                SELECT e.dst, walk.cost + coalesce((e.props ->> 'weight')::float8, 1),
                       walk.path || e.dst
                FROM walk JOIN edges e ON e.kind = %(kind)s AND e.src = walk.node
                WHERE NOT e.dst = ANY(walk.path)
            )
            SELECT min(cost) FROM walk WHERE node = %(dst)s
            """,
            src=src,
            dst=dst,
            kind=kind,
        )
        return None if rows[0][0] is None else float(rows[0][0])

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

        # 1. Recount support (this statement also refreshes the cached support_routes column).
        #    Stale = had at least one surviving route before and has none now.
        rows = self._rows(_RECOUNT, viewer=viewer, before=before, exposed=exposed)
        changes: dict[str, Invalidation] = {
            bid: Invalidation(belief_id=bid, old_status=status, new_status="stale", path_len=1)
            for bid, status, was, now in rows
            if was > 0 and now == 0
        }
        self._suspect_dependents(viewer, changes)
        self._write_changes(correction_id, changes, tick)
        return sorted(changes.values(), key=lambda c: (c.path_len, c.belief_id))

    def exposed(self, viewer: str) -> set[str]:
        rows = self._rows(
            "SELECT id, data ->> 'type', data ->> 'target' FROM nodes WHERE type = 'Correction' "
            "AND data ->> 'type' IN ('exposure', 'reinstatement') "
            "AND (data ->> 'observer' IS NULL OR data ->> 'observer' = %(viewer)s)",
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
        # refresh the cached count of routes that survive
        self._rows(_RECOUNT, viewer=viewer, before=before, exposed=sorted(set(before) - {agent_id}))
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
        count = self._rows("SELECT count(*) FROM nodes WHERE type = 'Correction'")[0][0]
        correction_id = f"C{count + 1}"
        self.add_node(Correction(id=correction_id, **fields))
        return correction_id

    def _suspect_dependents(self, viewer: str, changes: dict[str, Invalidation]) -> None:
        """Everything derived from a changed belief becomes suspect (if it was active)."""
        if not changes:
            return
        rows = self._rows(_DOWNSTREAM, sources=list(changes), viewer=viewer)
        for bid, hops, node_type, status in rows:
            if node_type == "Belief" and status == "active":
                changes[bid] = Invalidation(
                    belief_id=bid, old_status="active", new_status="suspect", path_len=1 + hops
                )

    def _write_changes(self, correction_id: str, changes: dict[str, Invalidation], tick: int):
        """Write the status changes and the INVALIDATED edges (correction -> belief), each as one
        statement over arrays, not one round trip per belief."""
        if not changes:
            return
        ids = [c.belief_id for c in changes.values()]
        statuses = [c.new_status for c in changes.values()]
        lengths = [c.path_len for c in changes.values()]
        self._conn.execute(
            "UPDATE nodes n SET status = c.status, updated_tick = %(tick)s "
            "FROM unnest(%(ids)s::text[], %(statuses)s::text[]) AS c(id, status) "
            "WHERE n.id = c.id",
            {"tick": tick, "ids": ids, "statuses": statuses},
        )
        self._conn.execute(
            "INSERT INTO edges (kind, src, dst, props) "
            "SELECT 'INVALIDATED', %(cid)s, c.id, jsonb_build_object("
            "'new_status', c.status, 'path_len', c.path_len, 'tick', %(tick)s::int) "
            "FROM unnest(%(ids)s::text[], %(statuses)s::text[], %(lengths)s::int[]) "
            "AS c(id, status, path_len)",
            {
                "cid": correction_id,
                "tick": tick,
                "ids": ids,
                "statuses": statuses,
                "lengths": lengths,
            },
        )
