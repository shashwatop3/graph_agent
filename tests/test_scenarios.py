"""The scenario suite from the experiment spec, run on every store (memory, FalkorDB, Postgres).

Each scenario builds a small graph and checks an exact expected outcome. Names follow the spec
(S01 .. S12). Three are not store behaviour, so they are covered elsewhere:
  S06 conflicting corrections  - how to resolve a conflict is an agent policy (stage S8, tools).
  S07 correction later retracted - "undo" needs a design decision first: what un-exposing an agent
                                  should do to beliefs that went stale because of it.
  S08 late-arriving old report - needs versioned beliefs, which arrive with assert_belief (S8).

Graphs use neutral names: V is the viewer, X is the agent that gets exposed, Y a trustworthy one.
"""

import pytest

from graph_agent.core.model import Action, Agent, Belief, Edge, Entity, Observation
from graph_agent.core.registry import Predicate
from stores_param import STORES

VIEWER = "V"


@pytest.fixture(params=STORES)
def store(request):
    store = request.param()
    for agent in (VIEWER, "X", "Y", "Z"):
        store.add_node(Agent(id=agent))
    store.add_node(Entity(id="E", type="thing"))
    yield store
    store.close()


def build(store, supported=None, derived=()):
    """Create beliefs and wire them up.

    supported: {belief id: [route, ...]}, each route a list of agent ids. A belief gets one
               observation per route.
    derived:   (child, parent) pairs, meaning child is DERIVED_FROM parent.
    """
    supported = supported or {}
    ids = list(supported) + [c for c, _ in derived] + [p for _, p in derived]
    for bid in dict.fromkeys(ids):
        store.add_node(Belief(id=bid, owner=VIEWER, subject="E", predicate=f"p_{bid}", value=1))
    for bid, routes in supported.items():
        for n, route in enumerate(routes):
            oid = f"O_{bid}_{n}"
            store.add_node(Observation(id=oid, kind="message", received_by=VIEWER))
            for hop, agent in enumerate(route):
                store.add_edge(Edge(kind="RELAYED_VIA", src=oid, dst=agent, props={"hop": hop}))
            store.add_edge(Edge(kind="SUPPORTS", src=oid, dst=bid))
    for child, parent in derived:
        store.add_edge(Edge(kind="DERIVED_FROM", src=child, dst=parent))


def changes(result):
    """(belief, new status, path length) for each change, easy to compare."""
    return [(c.belief_id, c.new_status, c.path_len) for c in result]


def statuses(store):
    return {b.id: b.status for b in store.beliefs(VIEWER)}


def test_s01_retraction_cascades_down_a_chain_of_depth_4(store):
    build(store, {"B0": [["X"]]}, [("B1", "B0"), ("B2", "B1"), ("B3", "B2"), ("B4", "B3")])
    assert changes(store.expose(VIEWER, "X", 1)) == [
        ("B0", "stale", 1),
        ("B1", "suspect", 2),
        ("B2", "suspect", 3),
        ("B3", "suspect", 4),
        ("B4", "suspect", 5),
    ]


@pytest.mark.parametrize("depth", [1, 3, 5])
def test_s02_cascade_depth_scales_path_length(store, depth):
    chain = [(f"B{i + 1}", f"B{i}") for i in range(depth)]
    build(store, {"B0": [["X"]]}, chain)
    result = store.expose(VIEWER, "X", 1)
    assert [c.path_len for c in result] == list(range(1, depth + 2))


def test_s03_a_diamond_changes_the_bottom_belief_once(store):
    #        B0 (stale)
    #       /          \
    #     B1            B2
    #       \          /
    #          B3
    build(store, {"B0": [["X"]]}, [("B1", "B0"), ("B2", "B0"), ("B3", "B1"), ("B3", "B2")])
    assert changes(store.expose(VIEWER, "X", 1)) == [
        ("B0", "stale", 1),
        ("B1", "suspect", 2),
        ("B2", "suspect", 2),
        ("B3", "suspect", 3),  # shortest path, reported once
    ]


def test_s04_a_cycle_in_the_dependencies_terminates(store):
    build(
        store, {"B0": [["X"]]}, [("B1", "B0"), ("B2", "B1"), ("B1", "B2")]
    )  # B1 and B2 depend on each other
    assert changes(store.expose(VIEWER, "X", 1)) == [
        ("B0", "stale", 1),
        ("B1", "suspect", 2),
        ("B2", "suspect", 3),
    ]


def test_s05_two_corrections_in_one_tick_give_the_same_result_in_either_order(store):
    # B0 has a route through X and one through Y; B2 only through X; B1 depends on B0
    build(store, {"B0": [["X"], ["Y"]], "B2": [["X"]]}, [("B1", "B0")])
    store.expose(VIEWER, "X", 5)
    store.expose(VIEWER, "Y", 5)
    one_order = statuses(store)
    assert one_order == {"B0": "stale", "B1": "suspect", "B2": "stale"}


def test_s05_the_other_order(store):
    build(store, {"B0": [["X"], ["Y"]], "B2": [["X"]]}, [("B1", "B0")])
    store.expose(VIEWER, "Y", 5)
    store.expose(VIEWER, "X", 5)
    assert statuses(store) == {"B0": "stale", "B1": "suspect", "B2": "stale"}


def test_s09_a_correction_that_changes_nothing_downstream_invalidates_nothing(store):
    # B0 is also supported by a route through Y, so exposing X must not touch it or B1
    build(store, {"B0": [["X"], ["Y"]]}, [("B1", "B0")])
    assert store.expose(VIEWER, "X", 1) == []
    assert statuses(store) == {"B0": "active", "B1": "active"}
    assert store.get(VIEWER, "B0").support_routes == 1
    assert store.expose(VIEWER, "Z", 2) == []  # an agent on no route at all


def test_s10_an_action_that_depends_on_a_stale_belief_is_reachable(store):
    build(store, {"B0": [["X"]]}, [("B1", "B0")])
    store.add_node(Action(id="ACT", owner=VIEWER, type="act", status="committed"))
    store.add_edge(Edge(kind="DERIVED_FROM", src="ACT", dst="B1"))
    store.expose(VIEWER, "X", 1)
    # expose() only changes beliefs. The action is found through dependents(), and flagging it
    # for the agent is the context compiler's job (stage S8).
    assert store.dependents(VIEWER, "B0") == {"B1": 1, "ACT": 2}
    assert store.get(VIEWER, "ACT").status == "committed"


def test_s11_an_agent_that_hears_late_ends_in_the_same_state(store):
    build(store, {"B0": [["X"]]}, [("B1", "B0")])
    store.expose(VIEWER, "X", 9)  # the correction reaches this agent six ticks late
    assert statuses(store) == {"B0": "stale", "B1": "suspect"}
    assert store.get(VIEWER, "B0").updated_tick == 9  # when it was applied, not when it happened


def test_s11_a_correction_for_one_agent_does_not_reach_another(store):
    build(store, {"B0": [["X"]]})
    other = Belief(id="Q0", owner="Y", subject="E", predicate="q", value=1)
    store.add_node(other)
    store.add_node(Observation(id="OQ", kind="message", received_by="Y"))
    store.add_edge(Edge(kind="RELAYED_VIA", src="OQ", dst="X", props={"hop": 0}))
    store.add_edge(Edge(kind="SUPPORTS", src="OQ", dst="Q0"))
    store.expose(VIEWER, "X", 3)
    assert store.get("Y", "Q0").status == "active"  # Y has not been told about X yet
    store.expose("Y", "X", 8)
    assert store.get("Y", "Q0").status == "stale"


def test_s12_a_change_within_tolerance_is_not_a_conflict(store):
    predicates = {"reading": Predicate(name="reading", tolerance=2)}
    for bid, value in [("R1", 40), ("R2", 41), ("R3", 45)]:
        store.add_node(Belief(id=bid, owner=VIEWER, subject="E", predicate="reading", value=value))
    assert [b.id for b in store.conflicts(VIEWER, "R1", predicates)] == ["R3"]  # 41 is within 2
