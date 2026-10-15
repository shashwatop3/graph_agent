"""Fire dynamics, stepped one day at a time. No randomness: the world already holds every draw.

A field ignites on the earliest day a fire reaches it, which is the weighted shortest-path
distance from the initial fires. Water can only push that later.

Attributes without an underscore (day, state, ignited_on, intensity, revealed) are for reading.
Only step() changes them.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from enum import Enum

from .world import Edge, World


class FieldState(Enum):
    UNBURNT = "unburnt"
    BURNING = "burning"
    BURNT = "burnt"


class WaterRuleError(ValueError):
    """An agent tried to water on two consecutive days, or does not exist."""


@dataclass(frozen=True)
class FireRules:
    burn_days: int = 2  # days a field stays burning before it is burnt out
    decay: float = 0.9  # intensity multiplier each time fire spreads along an edge
    min_intensity: float = 0.2  # a fire weaker than this fizzles out instead of igniting
    water_delay: int = 1  # days water pushes an arrival back
    water_factor: float = 0.5  # intensity multiplier when water pushes an arrival back


@dataclass(frozen=True)
class Ignition:
    """Fire reaching `field` on `day` along `edge`. Pending until that day, then reported."""

    field: int
    day: int
    intensity: float
    edge: Edge

    @property
    def source(self) -> int:
        return self.edge.src

    @property
    def via_hidden(self) -> bool:
        return self.edge.hidden


@dataclass(frozen=True)
class DayReport:
    day: int
    ignited: tuple[Ignition, ...]
    burnt_out: tuple[int, ...]
    delayed: tuple[int, ...]  # fields where water postponed an arrival today
    revealed_hidden: tuple[Edge, ...]  # hidden edges used for the first time today


class FireSim:
    def __init__(self, world: World, rules: FireRules | None = None):
        self.world = world
        self.rules = rules or FireRules()
        self.day = 0
        self.state = [FieldState.UNBURNT] * world.n_fields
        self.ignited_on: dict[int, int] = {}
        self.intensity: dict[int, float] = {}
        self.revealed: set[Edge] = set()
        self._last_water: dict[int, int] = {}
        self._pending: dict[int, list[Ignition]] = {}
        self._out: dict[int, list[Edge]] = {}
        for edge in world.edges:
            self._out.setdefault(edge.src, []).append(edge)
        for field, intensity in world.initial_fires:  # already burning when the game starts
            self._ignite(field, 0, intensity)

    @property
    def finished(self) -> bool:
        return not self._pending and FieldState.BURNING not in self.state

    def upcoming(self, day: int) -> tuple[Ignition, ...]:
        """Ignitions queued for `day`. Agents cannot see this; policies that do are omniscient."""
        return tuple(self._pending.get(day, ()))

    def can_water(self, agent: int) -> bool:
        known = 0 <= agent < self.world.config.n_agents
        return known and self._last_water.get(agent) != self.day - 1

    def step(self, water: Collection[int] = frozenset()) -> DayReport:
        """Resolve the current day. `water` is the set of agents that water today."""
        day = self.day
        for agent in water:
            if not self.can_water(agent):
                raise WaterRuleError(f"agent {agent} cannot water on day {day}")
        for agent in water:
            self._last_water[agent] = day

        ignited, delayed, revealed = self._resolve_arrivals(day, frozenset(water))
        burnt_out = self._burn_out(day)

        self.day += 1
        return DayReport(day, tuple(ignited), burnt_out, tuple(delayed), tuple(revealed))

    def _resolve_arrivals(self, day: int, watering: frozenset[int]):
        by_field: dict[int, list[Ignition]] = {}
        for arrival in self._pending.pop(day, []):
            by_field.setdefault(arrival.field, []).append(arrival)

        ignited: list[Ignition] = []
        delayed: list[int] = []
        revealed: list[Edge] = []
        for field in sorted(by_field):
            if self.state[field] is not FieldState.UNBURNT:
                continue
            arrivals = by_field[field]
            if self.world.owner(field) in watering:
                delayed.append(field)
                for a in arrivals:
                    self._schedule(
                        replace(
                            a,
                            day=day + self.rules.water_delay,
                            intensity=a.intensity * self.rules.water_factor,
                        )
                    )
                continue
            # Several fires arriving together: the strongest wins, ties go to the lowest source.
            best = min(arrivals, key=lambda a: (-a.intensity, a.source))
            if best.intensity < self.rules.min_intensity:
                continue
            ignited.append(best)
            self._ignite(field, day, best.intensity)
            if best.via_hidden and best.edge not in self.revealed:
                self.revealed.add(best.edge)
                revealed.append(best.edge)
        return ignited, delayed, revealed

    def _burn_out(self, day: int) -> tuple[int, ...]:
        done = [
            field
            for field, started in self.ignited_on.items()
            if self.state[field] is FieldState.BURNING and day - started >= self.rules.burn_days
        ]
        for field in done:
            self.state[field] = FieldState.BURNT
        return tuple(sorted(done))

    def _ignite(self, field: int, day: int, intensity: float) -> None:
        self.state[field] = FieldState.BURNING
        self.ignited_on[field] = day
        self.intensity[field] = intensity
        for edge in self._out.get(field, []):
            if self.state[edge.dst] is FieldState.UNBURNT:
                self._schedule(
                    Ignition(edge.dst, day + edge.weight, intensity * self.rules.decay, edge)
                )

    def _schedule(self, ignition: Ignition) -> None:
        self._pending.setdefault(ignition.day, []).append(ignition)


# A water policy is just a function: given the game, return the agents that water today.
Policy = Callable[[FireSim], Collection[int]]


def play(sim: FireSim, policy: Policy, max_days: int = 1000) -> list[DayReport]:
    reports = []
    while not sim.finished:
        if sim.day >= max_days:
            raise RuntimeError(f"fire still burning after {max_days} days")
        reports.append(sim.step(policy(sim)))
    return reports


def fields_saved(sim: FireSim) -> int:
    """Fields that never ignited."""
    return sum(1 for s in sim.state if s is FieldState.UNBURNT)
