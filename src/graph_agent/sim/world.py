"""The static world: a ring of agents, the fields they own, and the edges fire can travel along.

Everything random happens here, once, from a seed. After generation the world is immutable and
the fire simulation (fire.py) is fully deterministic.
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    """Fire can travel src -> dst, taking `weight` days.

    A hidden edge joins two fields that are neighbours in reality but not on the ring, and
    agents do not know it exists.
    """

    src: int
    dst: int
    weight: int
    hidden: bool = False


@dataclass(frozen=True)
class WorldConfig:
    n_agents: int = 8
    fields_per_agent: int = 3
    spread_weight: tuple[int, int] = (1, 1)  # burn time in days, inclusive range
    n_hidden_edges: int = 2
    hidden_weight: tuple[int, int] = (1, 1)
    min_hidden_span: int = 2  # a hidden edge skips at least this many agents (clockwise)
    n_initial_fires: int = 1
    initial_intensity: float = 1.0

    def __post_init__(self):
        if self.n_agents < 3:
            raise ValueError("n_agents must be at least 3")
        if self.fields_per_agent < 1:
            raise ValueError("fields_per_agent must be at least 1")
        for name in ("spread_weight", "hidden_weight"):
            low, high = getattr(self, name)
            if not 1 <= low <= high:
                raise ValueError(f"{name} must satisfy 1 <= low <= high")
        if self.n_hidden_edges and not 1 <= self.min_hidden_span <= self.n_agents - 1:
            raise ValueError("min_hidden_span must be between 1 and n_agents - 1")
        if not 1 <= self.n_initial_fires <= self.n_agents * self.fields_per_agent:
            raise ValueError("n_initial_fires must be between 1 and the number of fields")


@dataclass(frozen=True)
class World:
    config: WorldConfig
    seed: int
    edges: tuple[Edge, ...]
    initial_fires: tuple[tuple[int, float], ...]  # (field_id, intensity), ignite on day 0

    @property
    def n_fields(self) -> int:
        return self.config.n_agents * self.config.fields_per_agent

    def owner(self, field_id: int) -> int:
        return field_id // self.config.fields_per_agent

    def fields_of(self, agent: int) -> range:
        m = self.config.fields_per_agent
        return range(agent * m, (agent + 1) * m)


def generate_world(config: WorldConfig, seed: int) -> World:
    rng = random.Random(seed)
    n_fields = config.n_agents * config.fields_per_agent

    # Visible spread edges: one clockwise ring through all fields.
    edges = [
        Edge(f, (f + 1) % n_fields, rng.randint(*config.spread_weight)) for f in range(n_fields)
    ]

    # Hidden neighbour edges: clockwise jumps that skip at least min_hidden_span agents.
    taken = {(e.src, e.dst) for e in edges}
    hidden_edges: list[Edge] = []
    attempts = 0
    while len(hidden_edges) < config.n_hidden_edges:
        attempts += 1
        if attempts > 1000 * max(1, config.n_hidden_edges):
            raise ValueError("could not place the requested number of hidden edges")
        src = rng.randrange(n_fields)
        dst = rng.randrange(n_fields)
        span = (dst // config.fields_per_agent - src // config.fields_per_agent) % config.n_agents
        if span < config.min_hidden_span or (src, dst) in taken:
            continue
        taken.add((src, dst))
        hidden_edges.append(Edge(src, dst, rng.randint(*config.hidden_weight), hidden=True))

    starts = sorted(rng.sample(range(n_fields), config.n_initial_fires))
    return World(
        config=config,
        seed=seed,
        edges=tuple(edges + hidden_edges),
        initial_fires=tuple((f, config.initial_intensity) for f in starts),
    )
