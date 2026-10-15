"""Water policies, and comparing them on the same world."""

import pytest

from graph_agent.sim.fire import FireRules, FireSim, WaterRuleError, fields_saved, play
from graph_agent.sim.policies import fixed_plan, no_water, water_threatened
from graph_agent.sim.world import Edge, World, WorldConfig


def chain_world(n_edges: int, weight: int = 1) -> World:
    """Fields 0..n_edges in a line, one field per agent, fire starts at field 0."""
    config = WorldConfig(n_agents=max(3, n_edges + 1), fields_per_agent=1)
    edges = tuple(Edge(i, i + 1, weight) for i in range(n_edges))
    return World(config=config, seed=0, edges=edges, initial_fires=((0, 1.0),))


def test_no_water_and_fixed_plan():
    sim = FireSim(chain_world(3))
    plan = fixed_plan({0: {1}, 2: {1, 2}})
    assert no_water(sim) == frozenset()
    assert plan(sim) == {1}
    sim.step()
    assert plan(sim) == frozenset()
    sim.step()
    assert plan(sim) == {1, 2}


def test_water_threatened_waters_the_owner_of_the_field_about_to_ignite():
    sim = FireSim(chain_world(3, weight=2))
    assert water_threatened(sim) == frozenset()  # day 0: nothing arrives
    sim.step()
    sim.step()  # day 2: fire reaches field 1, owned by agent 1
    assert water_threatened(sim) == {1}


def test_water_threatened_skips_agents_that_watered_yesterday():
    sim = FireSim(chain_world(3))
    sim.step({1})  # fire reaches field 1 on day 1, but agent 1 watered on day 0
    assert water_threatened(sim) == frozenset()


def test_a_rejected_step_changes_nothing():
    sim = FireSim(chain_world(3))
    sim.step({1})
    with pytest.raises(WaterRuleError):
        sim.step({2, 1})  # agent 1 is not allowed, so agent 2 must not be recorded either
    assert sim.day == 1 and sim.can_water(2)


def test_water_strength_is_a_rule_setting():
    sim = FireSim(chain_world(3), FireRules(water_delay=3, water_factor=1.0))
    play(sim, fixed_plan({1: {1}}))
    assert sim.ignited_on == {0: 0, 1: 4, 2: 5, 3: 6}


def test_watering_the_arrival_day_saves_fields_where_no_water_saves_none():
    # intensity 1.0, 0.9, 0.81, ...; fires weaker than 0.4 fizzle. Water halves the intensity.
    rules = FireRules(decay=0.9, min_intensity=0.4)

    def saved(policy):
        sim = FireSim(chain_world(7), rules)
        play(sim, policy)
        return fields_saved(sim)

    assert saved(no_water) == 0
    assert saved(water_threatened) == 6  # fields 2..7 never ignite


def test_a_badly_timed_plan_saves_nothing():
    sim = FireSim(chain_world(7), FireRules(decay=0.9, min_intensity=0.4))
    play(sim, fixed_plan({0: {1}, 5: {3}}))  # not the days the fire arrives
    assert fields_saved(sim) == 0
