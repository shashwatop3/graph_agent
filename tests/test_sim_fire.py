import heapq

import pytest

from graph_agent.sim.fire import FieldState, FireRules, FireSim, WaterRuleError, play
from graph_agent.sim.policies import fixed_plan
from graph_agent.sim.world import Edge, World, WorldConfig, generate_world


def hand_world(edges, fires=((0, 1.0),), n_agents=4, fields_per_agent=1) -> World:
    config = WorldConfig(n_agents=n_agents, fields_per_agent=fields_per_agent)
    return World(config=config, seed=0, edges=tuple(edges), initial_fires=tuple(fires))


def chain(weights):
    """Fields 0..len(weights) in a line, one field per agent, edge i has weights[i] days."""
    return [Edge(i, i + 1, w) for i, w in enumerate(weights)]


def run(sim: FireSim, water_plan=None, max_days=200):
    return play(sim, fixed_plan(water_plan or {}), max_days)


def dijkstra(world: World):
    dist = {f: 0 for f, _ in world.initial_fires}
    heap = [(0, f) for f in dist]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for e in world.edges:
            if e.src == u and d + e.weight < dist.get(e.dst, float("inf")):
                dist[e.dst] = d + e.weight
                heapq.heappush(heap, (dist[e.dst], e.dst))
    return dist


def test_ignition_day_is_the_weighted_shortest_path():
    config = WorldConfig(n_agents=12, fields_per_agent=3, n_hidden_edges=5, n_initial_fires=2)
    # decay 1 and no fizzling: only distance decides who burns and when
    rules = FireRules(decay=1.0, min_intensity=0.0, burn_days=3)
    for seed in range(20):
        world = generate_world(config, seed)
        sim = FireSim(world, rules)
        run(sim)
        assert sim.ignited_on == dijkstra(world), f"seed {seed}"


def test_same_seed_gives_the_same_run():
    config = WorldConfig(n_agents=10, fields_per_agent=3, n_hidden_edges=3)

    def play(seed):
        sim = FireSim(generate_world(config, seed))
        return run(sim, {2: {1}, 5: {3}})

    assert play(7) == play(7)


def test_fire_travels_down_a_chain_at_the_edge_weights():
    sim = FireSim(hand_world(chain([2, 3, 1])))
    run(sim)
    assert sim.ignited_on == {0: 0, 1: 2, 2: 5, 3: 6}


def test_water_delays_the_arrival_and_everything_downstream():
    sim = FireSim(hand_world(chain([2, 3, 1])))
    run(sim, {2: {1}})  # agent 1 owns field 1, which the fire reaches on day 2
    assert sim.ignited_on == {0: 0, 1: 3, 2: 6, 3: 7}


def test_water_halves_intensity_but_does_not_stop_the_fire():
    rules = FireRules(decay=1.0)
    plain = FireSim(hand_world(chain([2, 3, 1])), rules)
    watered = FireSim(hand_world(chain([2, 3, 1])), rules)
    run(plain)
    run(watered, {2: {1}})
    assert watered.intensity[1] == pytest.approx(plain.intensity[1] * 0.5)
    assert 3 in watered.ignited_on


def test_water_on_the_wrong_day_changes_nothing():
    sim = FireSim(hand_world(chain([2, 3, 1])))
    run(sim, {1: {1}, 3: {1}})  # day 2 is the arrival day; neither of these hits it
    assert sim.ignited_on == {0: 0, 1: 2, 2: 5, 3: 6}


def test_an_agent_cannot_water_on_consecutive_days():
    sim = FireSim(hand_world(chain([2, 3, 1])))
    sim.step({1})
    with pytest.raises(WaterRuleError):
        sim.step({1})


def test_an_agent_can_water_every_other_day_and_others_can_water_in_between():
    sim = FireSim(hand_world(chain([2, 3, 1])))
    sim.step({1})
    sim.step({2})
    sim.step({1})


def test_unknown_agent_is_rejected():
    sim = FireSim(hand_world(chain([2])))
    with pytest.raises(WaterRuleError):
        sim.step({9})


def test_a_hidden_edge_is_revealed_the_day_fire_uses_it():
    edges = chain([3, 3, 3]) + [Edge(0, 3, 2, hidden=True)]
    sim = FireSim(hand_world(edges))
    reports = run(sim)
    assert sim.ignited_on[3] == 2
    revealed_days = [r.day for r in reports if r.revealed_hidden]
    assert revealed_days == [2]
    assert reports[2].ignited[0].via_hidden
    assert sim.revealed == {Edge(0, 3, 2, hidden=True)}


def test_a_hidden_edge_the_fire_never_uses_stays_hidden():
    edges = chain([1, 1, 1]) + [Edge(0, 3, 9, hidden=True)]  # the ring is faster
    sim = FireSim(hand_world(edges))
    run(sim)
    assert sim.revealed == set()


def test_a_hidden_edge_skips_the_agents_between():
    edges = chain([3, 3, 3]) + [Edge(0, 3, 2, hidden=True)]
    sim = FireSim(hand_world(edges))
    run(sim)
    assert sim.ignited_on[3] < sim.ignited_on[1] < sim.ignited_on[2]


def test_fields_burn_out_after_burn_days_and_never_reburn():
    sim = FireSim(hand_world(chain([1, 1, 1])), FireRules(burn_days=2))
    reports = run(sim)
    assert [r.burnt_out for r in reports if r.burnt_out] == [(0,), (1,), (2,), (3,)]
    assert all(s is FieldState.BURNT for s in sim.state)
    ignitions = [i.field for r in reports for i in r.ignited]
    assert len(ignitions) == len(set(ignitions))


def test_a_weak_fire_fizzles_instead_of_igniting():
    rules = FireRules(decay=0.5, min_intensity=0.3)
    sim = FireSim(hand_world(chain([1, 1, 1])), rules)
    run(sim)
    # intensities 1.0, 0.5, 0.25: the third field is too weak to ignite
    assert sorted(sim.ignited_on) == [0, 1]
    assert sim.state[2] is FieldState.UNBURNT


def test_simulation_terminates_even_with_heavy_watering():
    world = generate_world(WorldConfig(n_agents=8, fields_per_agent=3, n_hidden_edges=4), seed=11)
    sim = FireSim(world)
    plan = {d: set(range(d % 2, 8, 2)) for d in range(60)}  # every agent every other day
    run(sim, plan)
    assert sim.finished
