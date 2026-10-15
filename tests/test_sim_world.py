import pytest

from graph_agent.sim.world import WorldConfig, generate_world

CONFIG = WorldConfig(n_agents=10, fields_per_agent=3, n_hidden_edges=4, n_initial_fires=2)


def test_same_seed_gives_the_same_world():
    assert generate_world(CONFIG, seed=1) == generate_world(CONFIG, seed=1)


def test_different_seeds_give_different_worlds():
    assert generate_world(CONFIG, seed=1) != generate_world(CONFIG, seed=2)


def test_spread_edges_form_one_clockwise_ring_over_all_fields():
    world = generate_world(CONFIG, seed=3)
    spread = {e.src: e for e in world.edges if not e.hidden}
    assert len(spread) == world.n_fields == 30
    low, high = CONFIG.spread_weight
    for field_id, edge in spread.items():
        assert edge.dst == (field_id + 1) % 30
        assert low <= edge.weight <= high


def test_hidden_edges_are_clockwise_jumps_that_skip_agents():
    world = generate_world(CONFIG, seed=3)
    hidden_edges = [e for e in world.edges if e.hidden]
    assert len(hidden_edges) == 4
    assert len({(e.src, e.dst) for e in world.edges}) == len(world.edges)
    for e in hidden_edges:
        span = (world.owner(e.dst) - world.owner(e.src)) % CONFIG.n_agents
        assert span >= CONFIG.min_hidden_span
        assert CONFIG.hidden_weight[0] <= e.weight <= CONFIG.hidden_weight[1]


def test_initial_fires_are_distinct_fields():
    world = generate_world(CONFIG, seed=5)
    fields = [f for f, _ in world.initial_fires]
    assert len(fields) == len(set(fields)) == 2


def test_ownership_partitions_the_fields():
    world = generate_world(CONFIG, seed=0)
    assert list(world.fields_of(2)) == [6, 7, 8]
    assert all(world.owner(f) == 2 for f in world.fields_of(2))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_agents": 2},
        {"fields_per_agent": 0},
        {"spread_weight": (0, 2)},
        {"hidden_weight": (3, 2)},
        {"min_hidden_span": 8, "n_agents": 8},
        {"n_initial_fires": 0},
    ],
)
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        WorldConfig(**kwargs)
