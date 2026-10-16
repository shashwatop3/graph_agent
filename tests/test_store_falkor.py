"""FalkorStore must pass the same contract as the reference store, plus a few checks that look
inside the graph itself. Needs FalkorDB: docker compose up -d --wait
"""

import pytest

from graph_agent.stores.falkor import FalkorStore
from store_contract import StoreContract

pytestmark = pytest.mark.integration


class TestFalkorStore(StoreContract):
    def make_store(self):
        return FalkorStore()

    # ---- things the Store interface cannot see: the stored graph itself ----------------------

    def test_exposure_writes_invalidated_edges_from_the_correction(self, store):
        store.expose("A5", "A6", tick=7, reason="evidence disagrees")
        rows = store._run(
            "MATCH (c:Correction)-[r:INVALIDATED]->(b:Belief) "
            "RETURN c.target, c.observer, b.id, r.new_status, r.path_len, r.tick ORDER BY b.id"
        )
        assert rows == [
            ["A6", "A5", "B20", "stale", 1, 7],
            ["A6", "A5", "B21", "suspect", 2, 7],
            ["A6", "A5", "B22", "suspect", 3, 7],
            ["A6", "A5", "B40", "suspect", 2, 7],
        ]

    def test_values_of_any_type_round_trip_through_json_properties(self, store):
        from graph_agent.core.model import Belief

        for i, value in enumerate([40, 2.5, "text", True, [1, 2], {"a": {"b": 1}}]):
            store.add_node(Belief(id=f"V{i}", owner="A5", subject="E1", predicate="p", value=value))
            assert store.get("A5", f"V{i}").value == value

    def test_relationship_properties_must_be_scalars(self, store):
        from graph_agent.core.model import Edge

        with pytest.raises(ValueError):
            store.add_edge(Edge(kind="TRUSTS", src="A1", dst="A2", props={"bad": [1, 2]}))

    def test_stores_do_not_share_state_across_graph_names(self):
        one, two = FalkorStore(), FalkorStore()
        try:
            from graph_agent.core.model import Agent

            one.add_node(Agent(id="A1"))
            assert two.get("A1", "A1") is None
        finally:
            one.close()
            two.close()
