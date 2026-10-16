"""Every store must give exactly the same answers as the reference store.

Random graphs, random exposures; after each exposure compare what expose() returned and the state
of every belief. This is what keeps the benchmark honest: the graph and SQL setups differ in how
they compute, never in what they compute.
"""

import random

import pytest

from graph_agent.stores.falkor import FalkorStore
from graph_agent.stores.memory import MemoryStore
from random_graph import AGENTS, VIEWER, build_random_graph

pytestmark = pytest.mark.integration

# Stores compared against MemoryStore. S5 adds the Postgres store here.
OTHER_STORES = {"falkor": FalkorStore}


def snapshot(store, belief_ids):
    """Everything about the viewer's beliefs that a caller could observe."""
    return {
        b.id: (b.status, b.support_routes, b.updated_tick) for b in store.beliefs(VIEWER)
    } | {
        f"routes:{bid}": store.support_routes(VIEWER, bid) for bid in belief_ids
    } | {
        f"deps:{bid}": store.dependents(VIEWER, bid) for bid in belief_ids
    }


@pytest.mark.parametrize("name", OTHER_STORES)
@pytest.mark.parametrize("seed", range(25))
def test_store_matches_the_reference_store(name, seed):
    reference, other = MemoryStore(), OTHER_STORES[name]()
    try:
        ids = build_random_graph(reference, seed)
        assert build_random_graph(other, seed) == ids
        assert snapshot(other, ids) == snapshot(reference, ids)

        rng = random.Random(1000 + seed)
        for tick, agent in enumerate(rng.sample(AGENTS[1:], k=4), start=1):
            expected = reference.expose(VIEWER, agent, tick)
            assert other.expose(VIEWER, agent, tick) == expected, f"exposing {agent}"
            assert snapshot(other, ids) == snapshot(reference, ids), f"after exposing {agent}"
    finally:
        other.close()
