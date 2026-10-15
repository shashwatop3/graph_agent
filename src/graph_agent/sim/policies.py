"""Water policies: plain functions that decide which agents water today.

Write your own with the same shape, `def my_policy(sim: FireSim) -> Collection[int]`, and pass it
to play(). The ones here are references for tests and for comparing strategies.
"""

from collections.abc import Collection, Mapping

from .fire import FieldState, FireSim, Policy


def no_water(sim: FireSim) -> Collection[int]:
    return frozenset()


def fixed_plan(plan: Mapping[int, Collection[int]]) -> Policy:
    """Water exactly as scripted: {day: agents}."""
    return lambda sim: frozenset(plan.get(sim.day, ()))


def water_threatened(sim: FireSim) -> Collection[int]:
    """Omniscient upper bound: water every agent whose field is about to ignite today."""
    threatened = {
        sim.world.owner(a.field)
        for a in sim.upcoming(sim.day)
        if sim.state[a.field] is FieldState.UNBURNT
    }
    return frozenset(agent for agent in threatened if sim.can_water(agent))
