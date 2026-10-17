"""The linear fire: strength rises or falls by a fixed step a day, up to a cap.

Fire arrives at strength x (1). Unwatered it grows by x a day, watered it falls by x; at 0 it is
out. A field at full strength (5) for 2 days is lost. It spreads only from a field still burning.
"""

from test_sim_fire import chain, hand_world

from graph_agent.packs.ringfire.sim.field import FieldState
from graph_agent.packs.ringfire.sim.fire import FireRules, FireSim

LINEAR = FireRules(
    dynamics="linear",
    step=1.0,
    max_intensity=5.0,
    lost_after=2,
    water_per_agent=None,
    water_cooldown=0,
)


def sim_on(edges, fires=((0, 1.0),), n_agents=4) -> FireSim:
    return FireSim(hand_world(edges, fires, n_agents=n_agents), LINEAR)


def strength(sim: FireSim, field: int) -> float:
    f = sim.fields[field]
    return f.intensity or 0.0 if f.state is FieldState.BURNING else 0.0


def test_an_unwatered_fire_grows_by_the_step_each_day_up_to_the_cap():
    sim = sim_on([], fires=((0, 1.0),), n_agents=3)
    seen = []
    for _ in range(4):
        sim.step()
        seen.append(strength(sim, 0))
    assert seen == [2.0, 3.0, 4.0, 5.0]


def test_a_field_at_full_strength_for_two_days_is_lost():
    sim = sim_on([], fires=((0, 4.0),), n_agents=3)
    first = sim.step()  # 4 -> 5, one day at full strength
    assert first.burnt_out == () and strength(sim, 0) == 5.0
    second = sim.step()  # a second day at 5: lost
    assert second.burnt_out == (0,)
    assert sim.fields[0].state is FieldState.BURNT


def test_watering_lowers_a_fire_by_the_step_and_at_zero_it_is_out():
    sim = sim_on([], fires=((0, 2.0),), n_agents=3)
    sim.step({0})
    assert strength(sim, 0) == 1.0
    report = sim.step({0})
    assert report.extinguished == (0,)
    assert sim.fields[0].state is FieldState.UNBURNT
    assert sim.finished


def test_watering_on_the_day_fire_arrives_puts_it_out_on_arrival():
    sim = sim_on(chain([1, 1]), n_agents=3)
    report = sim.step()  # day 0: field 0 burns, fire due at field 1 on day 1
    report = sim.step({1})
    assert report.hit_while_watered == (1,)
    assert sim.fields[1].state is FieldState.UNBURNT
    assert report.water_on_fire == (1,)


def test_fire_spreads_only_from_a_field_still_burning_that_morning():
    sim = sim_on(chain([2, 1]), n_agents=3)  # field 0 reaches field 1 on day 2
    sim.step({0})  # day 0: 1 -> 0, out before it can spread
    sim.step()
    report = sim.step()  # day 2: nothing lands, field 0 was no longer burning
    assert report.ignited == ()
    assert sim.fields[1].state is FieldState.UNBURNT


def test_a_fire_that_keeps_burning_spreads_at_the_arriving_strength():
    sim = sim_on(chain([1, 1]), n_agents=3)
    sim.step()  # day 0: field 0 grows to 2
    report = sim.step()  # day 1: fire reaches field 1 at strength 1
    assert [(i.field_id, i.intensity) for i in report.ignited] == [(1, 1.0)]


def test_water_on_a_day_without_fire_is_wasted_and_water_on_fire_is_not():
    sim = sim_on(chain([1, 1]), n_agents=3)
    report = sim.step({0, 2})  # field 0 burns; field 2 has no fire
    assert report.water_on_fire == (0,)
    assert report.water_wasted == (2,)


def test_the_outcome_of_a_choice_is_known_before_the_day_is_played():
    sim = sim_on(chain([1, 1]), n_agents=3)
    sim.step()
    told = sim.outcome(1, watered=True), sim.outcome(1, watered=False)
    assert [(o.event, o.after) for o in told] == [("put_out", 0.0), ("arrived", 1.0)]
    sim.step({1})
    assert sim.fields[1].state is FieldState.UNBURNT  # what it was told happened


def test_strength_of_every_burning_field_is_reported_each_night():
    sim = sim_on(chain([1, 1]), n_agents=3)
    sim.step()
    report = sim.step()
    assert report.strength == ((0, 3.0), (1, 1.0))


def test_the_binary_fire_is_unchanged_by_default():
    sim = FireSim(hand_world(chain([1, 1]), n_agents=3))
    sim.step()
    report = sim.step({1})
    assert report.hit_while_watered == (1,)
    assert report.water_on_fire == (1,) and report.extinguished == () and report.strength == ()


def test_a_fire_that_burns_on_keeps_reaching_its_neighbour_every_day():
    sim = sim_on(chain([1, 1]), fires=((0, 1.0),), n_agents=3)
    sim.step()  # day 0: field 0 burns on (it grows to 2, then 3, then 4)
    assert sim.step({1}).hit_while_watered == (1,)  # day 1: put out on arrival
    assert sim.step({1}).hit_while_watered == (1,)  # day 2: field 0 still burns, so again
    report = sim.step()  # day 3: not watered this time, it catches
    assert [i.field_id for i in report.ignited] == [1]


def test_a_game_with_a_horizon_ends_early_once_every_fire_is_out():
    world = hand_world(chain([1, 1]), fires=((0, 1.0),), n_agents=3, horizon=10)
    sim = FireSim(world, LINEAR)
    sim.step({0})  # out on day 0, before it spreads
    sim.step()  # its arrival on day 1 does not land: field 0 no longer burns
    assert sim.finished
