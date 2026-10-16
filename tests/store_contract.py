"""Behaviour every Store must have. A store's test module subclasses StoreContract and implements
make_store(); the same tests then run against the in-memory, FalkorDB and Postgres stores.

The graph below is neutral on purpose (agents, a sensor, readings), because the core has no domain.

    agents A1..A8; viewer is A5, and A6 is the one that gets exposed
    O51  message, route A3 > A4 > A5          supports B12 "temperature = 40"
    O52  message, route A3 > A2 > A1 > A8 > A7 > A6   supports B12 (second route, through A6)
    O60  message, route A6                    supports B20 "pressure = 9"
    O70  sensor reading, no route             supports B30 "humidity = 55"
    B17  derived from B12                     (does not depend on A6's lone claim)
    B21  derived from B20                     one hop below the stale belief
    B22  derived from B21                     two hops below
    B40  derived from B12 and B20             one healthy parent, one stale parent
"""

import pytest

from graph_agent.core.model import (
    Agent,
    Belief,
    Edge,
    Entity,
    Observation,
)
from graph_agent.core.registry import Predicate
from graph_agent.core.store import Store

VIEWER = "A5"


def edge(kind, src, dst, **props):
    return Edge(kind=kind, src=src, dst=dst, props=props)


def message(oid, route, receiver=VIEWER):
    return Observation(
        id=oid,
        kind="message",
        payload={"route": route},
        received_by=receiver,
        sender=route[-1],
    )


def belief(bid, subject, predicate, value, owner=VIEWER, origin="told", **kw):
    return Belief(
        id=bid, owner=owner, subject=subject, predicate=predicate, value=value, origin=origin, **kw
    )


class StoreContract:
    def make_store(self) -> Store:
        raise NotImplementedError

    @pytest.fixture
    def store(self):
        store = self.make_store()
        for i in range(1, 9):
            store.add_node(Agent(id=f"A{i}"))
        store.add_node(Entity(id="E1", type="thing"))
        store.add_node(Entity(id="E2", type="thing"))

        for oid, route in [
            ("O51", ["A3", "A4", "A5"]),
            ("O52", ["A3", "A2", "A1", "A8", "A7", "A6"]),
            ("O60", ["A6"]),
        ]:
            store.add_node(message(oid, route))
            for hop, agent in enumerate(route):
                store.add_edge(edge("RELAYED_VIA", oid, agent, hop=hop))
        store.add_node(Observation(id="O70", kind="sensor", received_by=VIEWER))

        store.add_node(belief("B12", "E1", "temperature", 40))
        store.add_node(belief("B20", "E2", "pressure", 9))
        store.add_node(belief("B30", "E2", "humidity", 55, origin="observed"))
        for oid, bid in [("O51", "B12"), ("O52", "B12"), ("O60", "B20"), ("O70", "B30")]:
            store.add_edge(edge("SUPPORTS", oid, bid))

        for bid, parents in [
            ("B17", ["B12"]),
            ("B21", ["B20"]),
            ("B22", ["B21"]),
            ("B40", ["B12", "B20"]),
        ]:
            store.add_node(belief(bid, "E1", f"derived_{bid}", 1, origin="derived"))
            for parent in parents:
                store.add_edge(edge("DERIVED_FROM", bid, parent))
        yield store
        store.close()

    # ---- writes and reads -------------------------------------------------------------------

    def test_an_edge_must_join_the_node_types_its_kind_allows(self, store):
        with pytest.raises(ValueError):
            store.add_edge(edge("SUPPORTS", "B12", "B20"))  # must start at an observation
        with pytest.raises(ValueError):
            store.add_edge(edge("LINKED", "A1", "nowhere"))

    def test_adding_the_same_node_twice_is_rejected(self, store):
        with pytest.raises(ValueError):
            store.add_node(Agent(id="A1"))

    def test_an_agent_sees_only_its_own_beliefs_and_observations(self, store):
        assert store.get(VIEWER, "B12").id == "B12"
        assert store.get("A4", "B12") is None
        assert store.get("A4", "O51") is None
        assert store.get("A4", "E1").id == "E1"  # entities are shared
        assert store.beliefs("A4") == []
        assert store.support_routes("A4", "B12") == []
        assert store.dependents("A4", "B12") == {}

    def test_reads_return_copies(self, store):
        store.get(VIEWER, "B12").status = "retracted"
        assert store.get(VIEWER, "B12").status == "active"

    def test_beliefs_can_be_filtered(self, store):
        assert [b.id for b in store.beliefs(VIEWER, subject="E2")] == ["B20", "B30"]
        assert [b.id for b in store.beliefs(VIEWER, predicate="pressure")] == ["B20"]
        assert store.beliefs(VIEWER, status="stale") == []

    def test_support_routes_come_back_in_hop_order(self, store):
        assert store.support_routes(VIEWER, "B12") == [
            ("A3", "A2", "A1", "A8", "A7", "A6"),
            ("A3", "A4", "A5"),
        ]
        assert store.support_routes(VIEWER, "B30") == [()]
        assert store.support_routes(VIEWER, "B17") == []

    def test_dependents_come_back_with_their_hop_count(self, store):
        assert store.dependents(VIEWER, "B20") == {"B21": 1, "B22": 2, "B40": 1}
        assert store.dependents(VIEWER, "B12") == {"B17": 1, "B40": 1}
        assert store.dependents(VIEWER, "B22") == {}

    # ---- exposure ---------------------------------------------------------------------------

    def test_exposure_keeps_a_belief_that_has_another_route_and_staleness_spreads(self, store):
        changes = store.expose(VIEWER, "A6", tick=7, reason="evidence disagrees")
        assert [(c.belief_id, c.new_status, c.path_len) for c in changes] == [
            ("B20", "stale", 1),
            ("B21", "suspect", 2),
            ("B40", "suspect", 2),
            ("B22", "suspect", 3),
        ]
        status = {b.id: b.status for b in store.beliefs(VIEWER)}
        assert status["B12"] == "active"  # still has the route through A4
        assert status["B17"] == "active"  # depends only on B12
        assert status["B30"] == "active"  # sensor, no route to cut
        assert store.get(VIEWER, "B12").support_routes == 1
        assert store.get(VIEWER, "B20").updated_tick == 7

    def test_exposure_records_old_and_new_status(self, store):
        change = store.expose(VIEWER, "A6", tick=7)[0]
        assert change.old_status == "active"
        assert change.new_status == "stale"

    def test_exposing_the_only_route_makes_a_belief_stale(self, store):
        changes = store.expose(VIEWER, "A4", tick=7)  # B12 still has the route through A6
        assert changes == []
        changes = store.expose(VIEWER, "A6", tick=8)
        assert {c.belief_id for c in changes} >= {"B12", "B17", "B20"}
        assert store.get(VIEWER, "B12").status == "stale"
        assert store.get(VIEWER, "B17").status == "suspect"

    def test_exposing_an_agent_on_no_route_changes_nothing(self, store):
        assert store.expose(VIEWER, "A2", tick=7) == []  # A2 is only on O52; O51 still supports B12
        assert store.get(VIEWER, "B12").status == "active"
        assert store.expose(VIEWER, "A7", tick=8) == []

    def test_exposing_the_same_agent_twice_changes_nothing_the_second_time(self, store):
        assert store.expose(VIEWER, "A6", tick=7)
        assert store.expose(VIEWER, "A6", tick=8) == []

    def test_exposure_is_private_to_the_viewer(self, store):
        store.add_node(belief("X1", "E2", "pressure", 9, owner="A4"))
        store.add_node(message("OX", ["A6"], receiver="A4"))
        store.add_edge(edge("RELAYED_VIA", "OX", "A6", hop=0))
        store.add_edge(edge("SUPPORTS", "OX", "X1"))
        store.expose(VIEWER, "A6", tick=7)
        assert store.get("A4", "X1").status == "active"

    def test_stale_beliefs_are_not_changed_again(self, store):
        store.expose(VIEWER, "A6", tick=7)
        before = {b.id: (b.status, b.updated_tick) for b in store.beliefs(VIEWER)}
        store.expose(VIEWER, "A3", tick=9)  # every route of B12 passes A3
        after = {b.id: (b.status, b.updated_tick) for b in store.beliefs(VIEWER)}
        assert after["B20"] == before["B20"]  # already stale
        assert after["B12"][0] == "stale"

    # ---- contradictions ---------------------------------------------------------------------

    def test_conflicts_finds_the_viewers_contradicting_beliefs(self, store):
        predicates = {"temperature": Predicate(name="temperature", tolerance=2)}
        store.add_node(belief("B90", "E1", "temperature", 55))
        store.add_node(belief("B91", "E1", "temperature", 41))  # within tolerance of B12
        assert [b.id for b in store.conflicts(VIEWER, "B12", predicates)] == ["B90"]
        assert store.conflicts(VIEWER, "missing", predicates) == []
