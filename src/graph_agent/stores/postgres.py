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
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ..core.model import (
    Action,
    Agent,
    Belief,
    Correction,
    Edge,
    Entity,
    Node,
    Observation,
    check_edge,
    visible,
)
from ..core.store import Invalidation, Store

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
SELECT id, min(hops) FROM downstream WHERE id <> ALL(%(sources)s) GROUP BY id
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
        self._conn.execute(f"CREATE SCHEMA {self.schema}")
        self._conn.execute(f"SET search_path TO {self.schema}")
        self._conn.execute(_SCHEMA)

    def close(self) -> None:
        if not self._conn.closed:
            self._conn.execute(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE")
            self._conn.close()

    def _rows(self, sql: str, **params: Any) -> list[tuple]:
        return self._conn.execute(sql, params).fetchall()

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
        for end, found in ((edge.src, src), (edge.dst, dst)):
            if found is None:
                raise ValueError(f"node {end!r} does not exist")
        check_edge(edge, src, dst)
        self._conn.execute(
            "INSERT INTO edges (kind, src, dst, props) VALUES (%s, %s, %s, %s)",
            (edge.kind, edge.src, edge.dst, Jsonb(edge.props)),
        )

    # ---- reads -------------------------------------------------------------------------------

    def get(self, viewer: str, node_id: str) -> Node | None:
        node = self._node(node_id)
        return node if node is not None and visible(viewer, node) else None

    def beliefs(self, viewer, subject=None, predicate=None, status=None) -> list[Belief]:
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
        return [self._node(row[0]) for row in ids]

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
        return dict(self._rows(_DOWNSTREAM, sources=[belief_id], viewer=viewer))

    # ---- propagation -------------------------------------------------------------------------

    def expose(self, viewer: str, agent_id: str, tick: int, reason: str = "") -> list[Invalidation]:
        # Agents this viewer already treats as exposed, before this call.
        before = [
            row[0]
            for row in self._rows(
                "SELECT data ->> 'target' FROM nodes WHERE type = 'Correction' "
                "AND data ->> 'type' = 'exposure' "
                "AND (data ->> 'observer' IS NULL OR data ->> 'observer' = %(viewer)s)",
                viewer=viewer,
            )
        ]
        exposed = sorted({*before, agent_id})

        count = self._rows("SELECT count(*) FROM nodes WHERE type = 'Correction'")[0][0]
        correction_id = f"C{count + 1}"
        self.add_node(
            Correction(
                id=correction_id,
                type="exposure",
                issued_by="engine",
                target=agent_id,
                tick=tick,
                reason=reason,
                observer=viewer,
            )
        )

        # 1. Recount support (this statement also refreshes the cached support_routes column).
        #    Stale = had at least one surviving route before and has none now.
        rows = self._rows(_RECOUNT, viewer=viewer, before=before, exposed=exposed)
        stale = {bid: status for bid, status, was, now in rows if was > 0 and now == 0}
        changes: dict[str, Invalidation] = {
            bid: Invalidation(belief_id=bid, old_status=status, new_status="stale", path_len=1)
            for bid, status in stale.items()
        }

        # 2. Everything derived from a stale belief becomes suspect (if it was active).
        if stale:
            downstream = self._rows(_DOWNSTREAM, sources=list(stale), viewer=viewer)
            for bid, hops in downstream:
                node = self._node(bid)
                if isinstance(node, Belief) and node.status == "active" and bid not in changes:
                    changes[bid] = Invalidation(
                        belief_id=bid, old_status="active", new_status="suspect", path_len=1 + hops
                    )

        # 3. Write the status changes and the INVALIDATED edges (correction -> belief).
        for change in changes.values():
            self._conn.execute(
                "UPDATE nodes SET status = %s, updated_tick = %s WHERE id = %s",
                (change.new_status, tick, change.belief_id),
            )
            self._conn.execute(
                "INSERT INTO edges (kind, src, dst, props) VALUES ('INVALIDATED', %s, %s, %s)",
                (
                    correction_id,
                    change.belief_id,
                    Jsonb(
                        {"new_status": change.new_status, "path_len": change.path_len, "tick": tick}
                    ),
                ),
            )
        return sorted(changes.values(), key=lambda c: (c.path_len, c.belief_id))
