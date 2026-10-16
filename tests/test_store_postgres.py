"""PostgresStore must pass the same contract as the reference store, plus a few checks that look
inside the tables. Needs Postgres: docker compose up -d --wait
"""

import pytest

from graph_agent.stores.postgres import PostgresStore
from store_contract import StoreContract

pytestmark = pytest.mark.integration


class TestPostgresStore(StoreContract):
    def make_store(self):
        return PostgresStore()

    # ---- things the Store interface cannot see: the stored tables themselves -----------------

    def test_exposure_writes_invalidated_edges_from_the_correction(self, store):
        store.expose("A5", "A6", tick=7, reason="evidence disagrees")
        rows = store._rows(
            "SELECT c.data ->> 'target', c.data ->> 'observer', e.dst, e.props ->> 'new_status', "
            "(e.props ->> 'path_len')::int, (e.props ->> 'tick')::int "
            "FROM edges e JOIN nodes c ON c.id = e.src WHERE e.kind = 'INVALIDATED' "
            "ORDER BY e.dst"
        )
        assert rows == [
            ("A6", "A5", "B20", "stale", 1, 7),
            ("A6", "A5", "B21", "suspect", 2, 7),
            ("A6", "A5", "B22", "suspect", 3, 7),
            ("A6", "A5", "B40", "suspect", 2, 7),
        ]

    def test_values_of_any_type_round_trip(self, store):
        from graph_agent.core.model import Belief

        for i, value in enumerate([40, 2.5, "text", True, [1, 2], {"a": {"b": 1}}]):
            store.add_node(Belief(id=f"V{i}", owner="A5", subject="E1", predicate="p", value=value))
            assert store.get("A5", f"V{i}").value == value

    def test_status_changes_live_in_the_columns_not_the_stored_json(self, store):
        store.expose("A5", "A6", tick=7)
        status, data_status = store._rows(
            "SELECT status, data ->> 'status' FROM nodes WHERE id = 'B20'"
        )[0]
        assert (status, data_status) == ("stale", "active")  # the JSON is the creation-time copy
        assert store.get("A5", "B20").status == "stale"  # reads use the column

    def test_stores_do_not_share_tables_across_schemas(self):
        from graph_agent.core.model import Agent

        one, two = PostgresStore(), PostgresStore()
        try:
            one.add_node(Agent(id="A1"))
            assert two.get("A1", "A1") is None
        finally:
            one.close()
            two.close()
