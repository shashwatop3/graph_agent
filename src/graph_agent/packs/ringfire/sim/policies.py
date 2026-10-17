"""Watering policies: plain functions that decide which agents water today.

Write your own with the same shape, `def my_policy(sim: FireSim) -> Collection[int]`, and pass it
to play(). The ones here are references for tests and for comparing strategies.
"""

from collections.abc import Collection, Mapping

from .field import FieldState
from .fire import FireSim, WateringPolicy


def never_water(sim: FireSim) -> Collection[int]:
    return frozenset()


def scripted_watering(plan: Mapping[int, Collection[int]]) -> WateringPolicy:
    """Water exactly as scripted: {day: agents}."""
    return lambda sim: frozenset(plan.get(sim.day, ()))


def water_where_fire_arrives(sim: FireSim) -> Collection[int]:
    """Omniscient upper bound: water every agent whose field is about to ignite today."""
    threatened = {
        sim.fields[a.field_id].owner
        for a in sim.upcoming(sim.day)
        if sim.fields[a.field_id].state is FieldState.UNBURNT
    }
    return frozenset(agent for agent in threatened if sim.can_water_today(agent))
