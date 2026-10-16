"""Builds a random but valid knowledge graph in any store, for parity tests.

The same seed always gives the same graph, so two stores can be filled identically and their
answers compared. Shapes covered: several routes per belief, routes of different lengths, sensor
beliefs with no route, derived beliefs that depend on one, two or no parents, diamond-shaped
dependencies, and a mix of starting statuses.
"""

import random

from graph_agent.core.model import Agent, Belief, Edge, Entity, Observation
from graph_agent.core.store import Store

VIEWER = "A1"
AGENTS = [f"A{i}" for i in range(1, 8)]


def build_random_graph(store: Store, seed: int, n_beliefs: int = 14) -> list[str]:
    """Fill `store`. Returns the ids of the beliefs created."""
    rng = random.Random(seed)
    for agent in AGENTS:
        store.add_node(Agent(id=agent))
    store.add_node(Entity(id="E1", type="thing"))

    belief_ids: list[str] = []
    observation_count = 0
    for i in range(n_beliefs):
        bid = f"B{i:02d}"
        store.add_node(
            Belief(
                id=bid,
                owner=VIEWER,
                subject="E1",
                predicate=f"p{i}",
                value=i,
                status=rng.choice(["active", "active", "active", "suspect"]),
            )
        )
        # Derived beliefs depend on 1 to 3 earlier beliefs (so the graph has no cycles).
        # The first beliefs, and some later ones, are supported by observations instead.
        derived = i >= 3 and rng.random() < 0.5
        if derived:
            for parent in rng.sample(belief_ids, k=min(len(belief_ids), rng.randint(1, 3))):
                store.add_edge(Edge(kind="DERIVED_FROM", src=bid, dst=parent))
        else:
            for _ in range(rng.randint(1, 3)):
                oid = f"O{observation_count:03d}"
                observation_count += 1
                route = rng.sample(AGENTS[1:], k=rng.randint(0, 4))  # may be empty: a sensor
                store.add_node(
                    Observation(id=oid, kind="message", received_by=VIEWER, payload={"r": route})
                )
                for hop, agent in enumerate(route):
                    store.add_edge(Edge(kind="RELAYED_VIA", src=oid, dst=agent, props={"hop": hop}))
                store.add_edge(Edge(kind="SUPPORTS", src=oid, dst=bid))
        belief_ids.append(bid)
    return belief_ids


def build_random_map(store: Store, seed: int, n: int = 14) -> list[str]:
    """A ring of places with random weights plus a few one-way chords. Returns the place ids."""
    rng = random.Random(seed)
    ids = [f"M{i}" for i in range(n)]
    for place in ids:
        store.add_node(Entity(id=place, type="place"))
    for i in range(n):
        store.add_edge(
            Edge(
                kind="RELATES",
                src=ids[i],
                dst=ids[(i + 1) % n],
                props={"weight": rng.randint(1, 4)},
            )
        )
    for _ in range(4):
        a, b = rng.sample(ids, 2)
        store.add_edge(Edge(kind="RELATES", src=a, dst=b, props={"weight": rng.randint(1, 6)}))
    return ids
