"""The day's graph, as the console's setup page draws it: one free stand-in run of the day team,
reduced to the part worth seeing and timed by tick.

    uv run python -m graph_agent.packs.hualien.snapshot > viewer/console/src/setups/quakeDay.json

Kept: who reported (the sources), each report, the facts the reports support (the seismic desk's
magnitudes, depths and tsunami threats; the risk desk's claim about FabA and its sensors' reading),
what was planned from them (bulletins, fab exposures) and what ops did (published, alerted). A
belief a desk received from a teammate is drawn as the teammate's original, so an edge runs from a
plan to the facts it really rests on. Each node has the tick it appeared and every status it took;
tests/hualien/test_quake_day.py checks the committed file is what a run gives.
"""

import json
from typing import Any

from graph_agent.core.model import Belief
from graph_agent.stores.memory import MemoryStore

from .adapter import DEPTH, EXPOSURE, MAGNITUDE
from .run import run_quake
from .standin import desk_team
from .teams import day_team
from .world import BULLETIN, FAB_STATUS, TSUNAMI, Report, tick_time

FACTS = (MAGNITUDE, DEPTH, TSUNAMI)
GROUPS = ("q-2024-04-02T2358", "q-2024-04-03T0011", "q-2024-04-03T0035", "fabs", "none")


def _fact_label(b: Belief) -> str:
    if b.predicate == MAGNITUDE:
        return f"M {b.value:g}"
    if b.predicate == DEPTH:
        return f"{b.value:g} km deep"
    if b.predicate == TSUNAMI:
        return f"tsunami: {b.value}"
    if b.predicate == FAB_STATUS:
        return f"{b.subject} is {b.value}"
    if b.predicate == BULLETIN:
        return f"bulletin {b.value}"
    return f"{b.subject}: {b.value} exposure"


def _report_label(r: Report) -> str:
    if r.written:
        return r.text if len(r.text) <= 48 else f"{r.text[:46]}…"
    figures = {p: v for _, p, v in r.claims}
    return f"M {figures[MAGNITUDE]:g}, {figures[DEPTH]:g} km"


def day_graph() -> dict[str, Any]:
    store = MemoryStore()
    run = run_quake(desk_team(), store, team=day_team())
    rt, world = run.runtime, run.world
    events = rt.log.events
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node(id_: str, kind: str, group: str, label: str, born: int, **extra: Any) -> None:
        nodes.append(
            {"id": id_, "kind": kind, "group": group, "label": label, "born": born, **extra}
        )

    def statuses(owner: str, belief: Belief) -> list[list[Any]]:
        found: list[list[Any]] = [[belief.created_tick, "active"]]
        for e in events:
            if e.kind == "change" and e.data["viewer"] == owner and e.data["belief"] == belief.id:
                found.append([e.tick, e.data["new"]])
        return found

    # a teammate's copy -> the original it was sent from
    original: dict[str, str] = {}
    for viewer in ("risk", "ops"):
        for obs in store.observations(viewer, 0):
            sent = obs.payload.get("source_belief")
            if sent is None:
                continue
            for b in store.beliefs(viewer, subject=obs.payload["subject"]):
                if (
                    b.predicate == obs.payload["predicate"]
                    and b.value == obs.payload["value"]
                    and b.created_tick == obs.received_tick
                ):
                    original[b.id] = str(sent)

    def root(belief_id: str) -> str:
        while belief_id in original:
            belief_id = original[belief_id]
        return belief_id

    # sources and their reports
    sources: set[str] = set()
    for r in world.delivered:
        group = next((a for a in r.about if a in GROUPS), "fabs" if r.about else "none")
        if r.source not in sources:
            sources.add(r.source)
            node(f"s:{r.source}", "source", group, r.source, r.tick, post=r.written)
        node(
            f"r:{r.id}",
            "report",
            group,
            _report_label(r),
            r.tick,
            source=r.source,
            post=r.written,
            rumour=r.rumour,
            text=r.text,
        )
        edges.append({"src": f"s:{r.source}", "dst": f"r:{r.id}", "kind": "REPORTED"})

    # the facts the reports support
    shown: set[str] = set()
    for owner, predicates in (("seismic", FACTS), ("risk", (FAB_STATUS,))):
        for b in store.beliefs(owner):
            if b.predicate not in predicates:
                continue
            group = b.subject if b.subject in GROUPS else "fabs"
            node(
                b.id,
                "fact",
                group,
                _fact_label(b),
                b.created_tick,
                owner=owner,
                origin=b.origin,
                status=statuses(owner, b),
            )
            shown.add(b.id)
            for r in world.delivered:
                if (b.subject, b.predicate, b.value) in r.claims and b.origin == "told":
                    edges.append({"src": f"r:{r.id}", "dst": b.id, "kind": "SUPPORTS"})
            if b.origin == "observed":  # a checking tool: the fab's own sensors
                if "s:sensors" not in sources:
                    sources.add("s:sensors")
                    node("s:sensors", "source", "fabs", "FabA's sensors", b.created_tick)
                edges.append({"src": "s:sensors", "dst": b.id, "kind": "SUPPORTS"})

    # what was planned from them
    for owner, predicate in (("seismic", BULLETIN), ("risk", EXPOSURE)):
        for b in store.beliefs(owner):
            if b.predicate != predicate:
                continue
            group = b.subject if b.subject in GROUPS else "fabs"
            node(
                b.id,
                "plan",
                group,
                _fact_label(b),
                b.created_tick,
                owner=owner,
                status=statuses(owner, b),
            )
            shown.add(b.id)
            for parent in store.sources(owner, b.id):
                if root(parent) in shown:
                    edges.append({"src": root(parent), "dst": b.id, "kind": "DERIVED_FROM"})

    # what ops did
    for e in events:
        if e.kind != "proposal":
            continue
        args = e.data["arguments"]
        basis = [root(b) for b in e.data["basis"]]
        group = args.get("quake", "fabs")
        label = (
            "publish the bulletin"
            if e.data["tool"] == "bulletin_send"
            else (f"alert {args['fab']}: {args['level']}")
        )
        status: list[list[Any]] = [[e.tick, "done"]]
        for later in events:
            if later.kind == "held" and later.data["id"] == e.data["id"]:
                status.append([later.tick, "held"])
        node(e.data["id"], "action", group, label, e.tick, status=status)
        for b in basis:
            if b in shown:
                edges.append({"src": b, "dst": e.data["id"], "kind": "DERIVED_FROM"})

    return {
        "ticks": [tick_time(t) for t in range(day_team().settings.ticks or 11)],
        "groups": list(GROUPS),
        "nodes": nodes,
        "edges": edges,
        "matched": world.matched,
        "checks": run.checks,
    }


if __name__ == "__main__":
    print(json.dumps(day_graph(), indent=1, ensure_ascii=False))
