"""Micro-benchmark: how long does `expose` take on FalkorDB and on Postgres?

Run:  uv run python benchmarks/propagation.py            (full)
      uv run python benchmarks/propagation.py --quick    (small sizes, about a minute)

The graph is a layered dependency graph:
  level 0      `width` beliefs, each supported by one observation routed through agent X
  level 1..D   `width` beliefs each, every belief derived from 2 random beliefs of the level above
So exposing X turns all of level 0 stale and everything below it suspect: width * (depth + 1)
changes, through up to 2^depth distinct dependency paths. That second number is the point: it is
what separates a good traversal from a naive one.

What is timed: the `expose` call (route recount, downstream walk, writes) and one `dependents`
call. Building the graph is not timed. Each measurement uses a fresh store and the first call is
a warm-up that is thrown away. Both databases run in Docker on the same machine; the results are
about relative behaviour, not absolute speed.

Three contenders:
  falkor           FalkorStore as shipped (one Cypher query per DERIVED_FROM level)
  postgres         PostgresStore as shipped (one WITH RECURSIVE query)
  falkor-paths     the obvious Cypher alternative, one variable-length path pattern. Shown only to
                   measure why FalkorStore does not use it; each query is cut off after 20 s.
"""

import argparse
import random
import statistics
import time
from pathlib import Path

from graph_agent.core.model import Agent, Belief, Edge, Entity, Observation
from graph_agent.stores.falkor import FalkorStore
from graph_agent.stores.postgres import PostgresStore

VIEWER = "V"
PATH_QUERY_TIMEOUT_MS = 20_000


def build_layered_graph(store, width: int, depth: int, seed: int = 0) -> list[str]:
    """Fill `store` as described in the module docstring. Returns the level-0 belief ids."""
    rng = random.Random(seed)
    for agent in (VIEWER, "X"):
        store.add_node(Agent(id=agent))
    store.add_node(Entity(id="E", type="thing"))
    levels: list[list[str]] = []
    for level in range(depth + 1):
        ids = [f"L{level}_{i}" for i in range(width)]
        for bid in ids:
            store.add_node(Belief(id=bid, owner=VIEWER, subject="E", predicate=bid, value=1))
        if level == 0:
            for bid in ids:
                oid = f"O_{bid}"
                store.add_node(Observation(id=oid, kind="message", received_by=VIEWER))
                store.add_edge(Edge(kind="RELAYED_VIA", src=oid, dst="X", props={"hop": 0}))
                store.add_edge(Edge(kind="SUPPORTS", src=oid, dst=bid))
        else:
            for bid in ids:
                for parent in rng.sample(levels[-1], k=min(2, width)):
                    store.add_edge(Edge(kind="DERIVED_FROM", src=bid, dst=parent))
        levels.append(ids)
    return levels[0]


def paths_downstream(store: FalkorStore, sources: list[str]) -> int:
    """The variable-length-path version of the downstream walk. Returns the node count."""
    rows = store._graph.query(
        "MATCH p = (d)-[:DERIVED_FROM*1..32]->(s:Belief) "
        "WHERE s.id IN $sources AND NOT d.id IN $sources "
        "AND all(n IN nodes(p) WHERE n.owner = $viewer) "
        "RETURN d.id, min(length(p))",
        {"sources": sources, "viewer": VIEWER},
        timeout=PATH_QUERY_TIMEOUT_MS,
    ).result_set
    return len(rows)


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - start, result


def run_once(store, width: int, depth: int, seed: int, use_paths: bool):
    """Build one graph in `store` and time it. Returns (expose seconds, dependents seconds,
    number of changes). With use_paths, only the path-pattern walk is timed."""
    level0 = build_layered_graph(store, width, depth, seed)
    if hasattr(store, "analyze"):
        store.analyze()  # Postgres: refresh planner statistics after the bulk load
    if use_paths:
        timed(paths_downstream, store, level0[:1])  # warm-up, thrown away
        seconds, _ = timed(paths_downstream, store, level0)
        return seconds, None, None
    timed(store.dependents, VIEWER, level0[0])  # warm-up, thrown away
    deps_seconds, _ = timed(store.dependents, VIEWER, level0[0])
    expose_seconds, changes = timed(store.expose, VIEWER, "X", 1)
    return expose_seconds, deps_seconds, len(changes)


def measure(make_store, width: int, depth: int, reps: int, use_paths: bool = False):
    """Median seconds for expose and for dependents, and the number of changes (None on timeout)."""
    runs = []
    for rep in range(reps):
        store = make_store()
        try:
            runs.append(run_once(store, width, depth, rep, use_paths))
        except Exception as error:  # a query was cut off by its timeout
            if "timed out" in str(error).lower():
                return None, None, None
            raise
        finally:
            store.close()
    expose = statistics.median(r[0] for r in runs)
    deps = None if runs[0][1] is None else statistics.median(r[1] for r in runs)
    return expose, deps, runs[-1][2]


def fmt(seconds):
    if seconds is None:
        return "timeout"
    return f"{seconds * 1000:,.0f} ms" if seconds < 10 else f"{seconds:,.1f} s"


def run_table(title, configs, include_paths):
    """configs: (width, depth, repetitions) rows."""
    lines = [
        f"### {title}",
        "",
        "| width | depth | beliefs | changes | falkor | postgres |"
        + (" falkor-paths (walk only) |" if include_paths else ""),
        "|---|---|---|---|---|---|" + ("---|" if include_paths else ""),
    ]
    for width, depth, reps in configs:
        print(f"  width={width} depth={depth} ...", flush=True)
        f_exp, _, f_n = measure(FalkorStore, width, depth, reps)
        p_exp, _, p_n = measure(PostgresStore, width, depth, reps)
        assert f_n == p_n == width * (depth + 1), (f_n, p_n)  # both did the same work
        beliefs = width * (depth + 1)
        row = f"| {width} | {depth} | {beliefs:,} | {f_n:,} | {fmt(f_exp)} | {fmt(p_exp)} |"
        if include_paths:
            path_exp, _, _ = measure(FalkorStore, width, depth, 1, use_paths=True)
            row += f" {fmt(path_exp)} |"
        lines.append(row)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    if args.quick:
        depth_configs = [(20, d, 2) for d in (2, 6, 10)]
        size_configs = [(w, 4, 2) for w in (50, 200)]
    else:
        depth_configs = [(50, d, 3) for d in (2, 4, 8, 12, 16, 20)]
        # the largest graphs take minutes to build, so they are measured fewer times
        size_configs = [(100, 6, 3), (500, 6, 3), (2000, 6, 3), (5000, 6, 3), (10000, 6, 1)]

    print("depth scaling")
    depth_table = run_table(
        f"Time to expose, by depth (width {depth_configs[0][0]}, 2 parents per belief)",
        depth_configs,
        include_paths=True,
    )
    print("size scaling")
    size_table = run_table(
        f"Time to expose, by graph size (depth {size_configs[0][1]}, 2 parents per belief)",
        size_configs,
        include_paths=False,
    )
    note = "Median over the repetitions set in the script, fresh store each repetition."
    report = f"{depth_table}\n\n{size_table}\n\n{note}\n"
    print("\n" + report)
    out = Path(__file__).resolve().parents[1] / "runs" / "propagation.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report)
    print(f"saved to {out}")


if __name__ == "__main__":
    main()
