"""Watering policies, and comparing them on the same world."""

import pytest

from graph_agent.sim.fire import FireSim, WaterRuleError, fields_saved, play
from graph_agent.sim.policies import never_water, scripted_watering, water_where_fire_arrives
from graph_agent.sim.world import Edge, World, WorldConfig


def chain_world(n_edges: int, weight: int = 1) -> World:
    """Fields 0..n_edges in a line, one field per agent, fire starts at field 0."""
    config = WorldConfig(n_agents=max(3, n_edges + 1), fields_per_agent=1)
    edges = tuple(Edge(i, i + 1, weight) for i in range(n_edges))
    return World(config=config, seed=0, edges=edges, initial_fires=((0, 1.0),))


def test_no_water_and_fixed_plan():
    sim = FireSim(chain_world(3))
    plan = scripted_watering({0: {1}, 2: {1, 2}})
    assert never_water(sim) == frozenset()
    assert plan(sim) == {1}
    sim.step()
    assert plan(sim) == frozenset()
    sim.step()
    assert plan(sim) == {1, 2}


def test_water_threatened_waters_the_owner_of_the_field_about_to_ignite():
    sim = FireSim(chain_world(3, weight=2))
    assert water_where_fire_arrives(sim) == frozenset()  # day 0: nothing arrives
    sim.step()
    sim.step()  # day 2: fire reaches field 1, owned by agent 1
    assert water_where_fire_arrives(sim) == {1}


def test_water_threatened_skips_agents_that_watered_yesterday():
    sim = FireSim(chain_world(3))
    sim.step({1})  # fire reaches field 1 on day 1, but agent 1 watered on day 0
    assert water_where_fire_arrives(sim) == frozenset()


def test_a_rejected_step_changes_nothing():
    sim = FireSim(chain_world(3))
    sim.step({1})
    with pytest.raises(WaterRuleError):
        sim.step({2, 1})  # agent 1 is not allowed, so agent 2 must not be recorded either
    assert sim.day == 1 and sim.can_water_today(2)


def test_watering_the_arrival_day_saves_fields_where_no_water_saves_none():
    def saved(policy):
        sim = FireSim(chain_world(7))
        play(sim, policy)
        return fields_saved(sim)

    assert saved(never_water) == 0
    # field 1 is watered on arrival and the fire stops there, so fields 1..7 are all saved
    assert saved(water_where_fire_arrives) == 7


def test_a_badly_timed_plan_saves_nothing():
    sim = FireSim(chain_world(7))
    play(sim, scripted_watering({0: {1}, 5: {3}}))  # not the days the fire arrives
    assert fields_saved(sim) == 0
