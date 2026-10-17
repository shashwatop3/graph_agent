import heapq

import pytest

from graph_agent.packs.ringfire.sim.field import FieldState
from graph_agent.packs.ringfire.sim.fire import FireRules, FireSim, WaterRuleError, play
from graph_agent.packs.ringfire.sim.policies import scripted_watering
from graph_agent.packs.ringfire.sim.world import Edge, World, WorldConfig, generate_world


def hand_world(
    edges, fires=((0, 1.0),), n_agents=4, fields_per_agent=1, horizon=None, random_ignitions=()
) -> World:
    config = WorldConfig(n_agents=n_agents, fields_per_agent=fields_per_agent, horizon=horizon)
    return World(
        config=config,
        seed=0,
        edges=tuple(edges),
        initial_fires=tuple(fires),
        random_ignitions=tuple(random_ignitions),
    )


def ring(n):
    """Fields 0..n-1 in a closed loop, one field per agent, every edge one day."""
    return [Edge(i, (i + 1) % n, 1) for i in range(n)]


def chain(weights):
    """Fields 0..len(weights) in a line, one field per agent, edge i has weights[i] days."""
    return [Edge(i, i + 1, w) for i, w in enumerate(weights)]


def run(sim: FireSim, watering_plan=None, max_days=200):
    return play(sim, scripted_watering(watering_plan or {}), max_days)


def ignition_days(sim: FireSim) -> dict[int, int]:
    return {f.id: f.ignited_on for f in sim.fields if f.ignited_on is not None}


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
    config = WorldConfig(
        n_agents=12,
        fields_per_agent=3,
        spread_weight=(1, 3),
        hidden_weight=(1, 2),
        n_hidden_edges=5,
        n_initial_fires=2,
    )
    # constant intensity and no fizzling: only distance decides who burns and when
    rules = FireRules(growth_if_unwatered=1.0, min_intensity=0.0, burn_days=3)
    for seed in range(20):
        world = generate_world(config, seed)
        sim = FireSim(world, rules)
        run(sim)
        assert ignition_days(sim) == dijkstra(world), f"seed {seed}"


def test_same_seed_gives_the_same_run():
    config = WorldConfig(n_agents=10, fields_per_agent=3, n_hidden_edges=3)

    def play(seed):
        sim = FireSim(generate_world(config, seed))
        return run(sim, {2: {1}, 5: {3}})

    assert play(7) == play(7)


def test_fire_travels_down_a_chain_at_the_edge_weights():
    sim = FireSim(hand_world(chain([2, 3, 1])))
    run(sim)
    assert ignition_days(sim) == {0: 0, 1: 2, 2: 5, 3: 6}


def test_fire_doubles_when_unwatered_and_is_put_out_when_watered():
    plain = FireSim(hand_world(chain([2, 3, 1])))
    watered = FireSim(hand_world(chain([2, 3, 1])))
    run(plain)
    run(watered, {2: {1}})
    assert plain.fields[1].intensity == 2.0  # 1.0 * growth_if_unwatered
    assert watered.fields[1].ignited_on is None  # put out: intensity 0, the field never ignites
    assert 3 not in ignition_days(watered)  # and nothing spreads on from it


def test_intensity_never_exceeds_the_cap():
    sim = FireSim(hand_world(chain([1] * 5), n_agents=6), FireRules(max_intensity=3.0))
    run(sim)
    # 1.0 doubles to 2.0, then would be 4.0 but is capped at 3.0 from there on
    assert [f.intensity for f in sim.fields] == [1.0, 2.0, 3.0, 3.0, 3.0, 3.0]


def test_water_on_the_wrong_day_changes_nothing():
    sim = FireSim(hand_world(chain([2, 3, 1])))
    run(sim, {1: {1}, 3: {1}})  # day 2 is the arrival day; neither of these hits it
    assert ignition_days(sim) == {0: 0, 1: 2, 2: 5, 3: 6}


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
    assert sim.fields[3].ignited_on == 2
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
    assert sim.fields[3].ignited_on < sim.fields[1].ignited_on < sim.fields[2].ignited_on


def test_fields_burn_out_after_burn_days_and_never_reburn():
    sim = FireSim(hand_world(chain([1, 1, 1])), FireRules(burn_days=2))
    reports = run(sim)
    assert [r.burnt_out for r in reports if r.burnt_out] == [(0,), (1,), (2,), (3,)]
    assert all(f.state is FieldState.BURNT for f in sim.fields)
    ignitions = [i.field_id for r in reports for i in r.ignited]
    assert len(ignitions) == len(set(ignitions))


def test_a_weak_fire_fizzles_instead_of_igniting():
    rules = FireRules(growth_if_unwatered=0.5, min_intensity=0.3)
    sim = FireSim(hand_world(chain([1, 1, 1])), rules)
    run(sim)
    # intensities 1.0, 0.5, 0.25: the third field is too weak to ignite
    assert sorted(ignition_days(sim)) == [0, 1]
    assert sim.fields[2].state is FieldState.UNBURNT


def test_simulation_terminates_even_with_heavy_watering():
    world = generate_world(WorldConfig(n_agents=8, fields_per_agent=3, n_hidden_edges=4), seed=11)
    sim = FireSim(world)
    plan = {d: set(range(d % 2, 8, 2)) for d in range(60)}  # every agent every other day
    run(sim, plan)
    assert sim.finished


def test_an_agent_can_water_only_as_often_as_its_budget_allows():
    sim = FireSim(hand_world(chain([1] * 5), n_agents=6), FireRules(water_per_agent=2))
    assert sim.water_left(1) == 2
    sim.step({1})
    sim.step()
    sim.step({1})  # the second and last watering
    assert sim.water_left(1) == 0 and sim.water_left(2) == 2  # only agent 1 used any
    sim.step()
    assert not sim.can_water_today(1)  # rested, but none left
    with pytest.raises(WaterRuleError):
        sim.step({1})


def test_without_a_budget_there_is_no_limit():
    sim = FireSim(hand_world(chain([1] * 5), n_agents=6))
    assert sim.water_left(1) is None


# ---- the long game: regrowth, random ignitions, cooldown, horizon -----------------------------


def test_without_regrowth_a_ring_fire_goes_round_once_and_dies():
    sim = FireSim(hand_world(ring(6), n_agents=6))
    run(sim)
    assert [f.ignitions for f in sim.fields] == [[0], [1], [2], [3], [4], [5]]


def test_a_regrown_field_burns_again_when_the_fire_comes_round():
    # F0 burns out on day 2 and regrows on day 4, so the fire from F5 on day 6 finds it unburnt
    rules = FireRules(burn_days=2, regrow_days=2)
    sim = FireSim(hand_world(ring(6), n_agents=6, horizon=13), rules)
    reports = run(sim)
    assert sim.fields[0].ignitions == [0, 6, 12]
    assert sim.fields[0].ignited_on == 12  # the latest
    assert reports[4].regrown == (0,)


def test_fire_reaching_a_field_that_has_not_regrown_yet_does_nothing():
    # ring of 4: the fire is back at F0 on day 4, the day F0 regrows, which is too late
    rules = FireRules(burn_days=2, regrow_days=2)
    sim = FireSim(hand_world(ring(4), horizon=12), rules)
    run(sim)
    assert [f.ignitions for f in sim.fields] == [[0], [1], [2], [3]]


def test_the_horizon_ends_the_game_on_that_day_even_while_fire_burns():
    rules = FireRules(regrow_days=2)
    sim = FireSim(hand_world(ring(6), n_agents=6, horizon=15), rules)
    reports = run(sim)
    assert len(reports) == 15 and sim.day == 15 and sim.finished
    assert any(f.state is FieldState.BURNING for f in sim.fields)


def test_a_random_ignition_starts_a_fire_from_nowhere_at_the_starting_strength():
    world = hand_world(chain([1]), n_agents=4, horizon=6, random_ignitions=[(3, 3)])
    sim = FireSim(world)
    reports = run(sim)
    (ignition,) = reports[3].ignited
    assert (ignition.field_id, ignition.intensity, ignition.edge) == (3, 1.0, None)
    assert ignition.source is None and not ignition.via_hidden
    assert sim.fields[3].ignitions == [3]


def test_a_random_ignition_is_put_out_if_the_owner_waters_that_day():
    world = hand_world(chain([1]), n_agents=4, horizon=6, random_ignitions=[(3, 3)])
    sim = FireSim(world)
    reports = run(sim, {3: {3}})
    assert reports[3].hit_while_watered == (3,)
    assert sim.fields[3].ignitions == []


def test_a_random_ignition_on_a_field_already_burning_changes_nothing():
    world = hand_world(chain([1, 1]), n_agents=4, horizon=6, random_ignitions=[(1, 1)])
    sim = FireSim(world)
    run(sim)
    assert sim.fields[1].ignitions == [1]  # once, from the spread


def test_a_cooldown_of_two_days_means_watering_every_third_day_at_most():
    sim = FireSim(hand_world(chain([5])), FireRules(water_cooldown=2))
    sim.step({1})  # day 0
    assert not sim.can_water_today(1)  # day 1
    sim.step()
    assert not sim.can_water_today(1)  # day 2
    sim.step()
    assert sim.can_water_today(1)  # day 3
    sim.step({1})


def test_watering_during_the_cooldown_is_refused():
    sim = FireSim(hand_world(chain([5])), FireRules(water_cooldown=2))
    sim.step({1})
    sim.step()
    with pytest.raises(WaterRuleError):
        sim.step({1})


def test_no_cooldown_allows_watering_every_day():
    sim = FireSim(hand_world(chain([5])), FireRules(water_cooldown=0))
    for _ in range(3):
        sim.step({1})


def test_rules_reject_nonsense():
    with pytest.raises(ValueError):
        FireRules(water_cooldown=-1)
    with pytest.raises(ValueError):
        FireRules(regrow_days=0)
