"""Fire dynamics, stepped one day at a time. No randomness: the world already holds every draw.

A field ignites on the earliest day a fire reaches it, which is the weighted shortest-path
distance from the initial fires. Water does not delay the fire: it halves the intensity of the
fire arriving at a watered field. An unwatered field catches fire twice as strong, up to a cap.

Attributes without an underscore (day, fields, revealed) are for reading.
Only step() changes them.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass, replace

from .field import Field, FieldState
from .world import Edge, World


class WaterRuleError(ValueError):
    """An agent tried to water on two consecutive days, or does not exist."""


@dataclass(frozen=True)
class FireRules:
    burn_days: int = 2  # days a field stays burning before it is burnt out
    growth_if_unwatered: float = 2.0  # intensity multiplier when fire spreads to an unwatered field
    growth_if_watered: float = 0.5  # intensity multiplier when fire spreads to a watered field
    min_intensity: float = 0.2  # a fire weaker than this fizzles out instead of igniting
    max_intensity: float = 4.0  # growth stops here


@dataclass(frozen=True)
class Ignition:
    """Fire reaching field `field_id` on `day` along `edge`.

    While pending, `intensity` is the strength of the fire it comes from. Once it ignites, the
    reported ignition carries the strength the field caught fire with.
    """

    field_id: int
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
    hit_while_watered: tuple[int, ...]  # fields fire reached today whose owner watered
    revealed_hidden: tuple[Edge, ...]  # hidden edges used for the first time today


class FireSim:
    def __init__(self, world: World, rules: FireRules | None = None):
        self.world = world
        self.rules = rules or FireRules()
        self.day = 0
        self.fields = [Field(f, world.owner(f)) for f in range(world.n_fields)]
        self.revealed: set[Edge] = set()
        self._last_watered_day: dict[int, int] = {}
        self._pending: dict[int, list[Ignition]] = {}
        self._out: dict[int, list[Edge]] = {}
        for edge in world.edges:
            self._out.setdefault(edge.src, []).append(edge)
        for field_id, intensity in world.initial_fires:  # already burning when the game starts
            self._ignite(field_id, 0, intensity)

    @property
    def finished(self) -> bool:
        return not self._pending and not any(f.state is FieldState.BURNING for f in self.fields)

    def upcoming(self, day: int) -> tuple[Ignition, ...]:
        """Ignitions queued for `day`. Agents cannot see this; policies that do are omniscient."""
        return tuple(self._pending.get(day, ()))

    def can_water_today(self, agent: int) -> bool:
        known = 0 <= agent < self.world.config.n_agents
        return known and self._last_watered_day.get(agent) != self.day - 1

    def step(self, agents_water_today: Collection[int] = frozenset()) -> DayReport:
        """Resolve the current day. `agents_water_today` is the set of agents that water today."""
        day = self.day
        for agent in agents_water_today:
            if not self.can_water_today(agent):
                raise WaterRuleError(f"agent {agent} cannot water on day {day}")
        for agent in agents_water_today:
            self._last_watered_day[agent] = day

        ignited, hit_while_watered, revealed = self._ignite_fields_today(
            day, frozenset(agents_water_today)
        )
        burnt_out = self._burn_out(day)

        self.day += 1
        return DayReport(day, tuple(ignited), burnt_out, tuple(hit_while_watered), tuple(revealed))
#REVIEW: 
    def _ignite_fields_today(self, day: int, agents_water_today: frozenset[int]):
        by_field: dict[int, list[Ignition]] = {}
        for arrival in self._pending.pop(day, []):
            by_field.setdefault(arrival.field_id, []).append(arrival)

        ignited: list[Ignition] = []
        hit_while_watered: list[int] = []
        revealed: list[Edge] = []
        for field_id in sorted(by_field):
            if self.fields[field_id].state is not FieldState.UNBURNT:
                continue
            # Several fires arriving together: the strongest wins, ties go to the lowest source.
            best = min(by_field[field_id], key=lambda a: (-a.intensity, a.source))
            owner_waters_today = self.fields[field_id].owner in agents_water_today
            if owner_waters_today:
                hit_while_watered.append(field_id)
            rules = self.rules
            factor = rules.growth_if_watered if owner_waters_today else rules.growth_if_unwatered
            intensity = min(best.intensity * factor, self.rules.max_intensity)
            if intensity < self.rules.min_intensity:
                continue
            ignited.append(replace(best, intensity=intensity))
            self._ignite(field_id, day, intensity)
            if best.via_hidden and best.edge not in self.revealed:
                self.revealed.add(best.edge)
                revealed.append(best.edge)
        return ignited, hit_while_watered, revealed

    def _burn_out(self, day: int) -> tuple[int, ...]:
        done = [
            f
            for f in self.fields
            if f.state is FieldState.BURNING and day - f.ignited_on >= self.rules.burn_days
        ]
        for f in done:
            f.state = FieldState.BURNT
        return tuple(f.id for f in done)

    def _ignite(self, field_id: int, day: int, intensity: float) -> None:
        f = self.fields[field_id]
        f.state, f.ignited_on, f.intensity = FieldState.BURNING, day, intensity
        for edge in self._out.get(field_id, []):
            if self.fields[edge.dst].state is FieldState.UNBURNT:
                self._schedule(Ignition(edge.dst, day + edge.weight, intensity, edge))

    def _schedule(self, ignition: Ignition) -> None:
        self._pending.setdefault(ignition.day, []).append(ignition)


# A watering policy is just a function: given the game, return the agents that water today.
WateringPolicy = Callable[[FireSim], Collection[int]]


def play(sim: FireSim, policy: WateringPolicy, max_days: int = 1000) -> list[DayReport]:
    reports = []
    while not sim.finished:
        if sim.day >= max_days:
            raise RuntimeError(f"fire still burning after {max_days} days")
        reports.append(sim.step(policy(sim)))
    return reports


def fields_saved(sim: FireSim) -> int:
    """Fields that never ignited."""
    return sum(1 for f in sim.fields if f.state is FieldState.UNBURNT)
