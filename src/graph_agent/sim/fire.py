"""Fire dynamics, stepped one day at a time. No randomness: the world already holds every draw.

A field ignites on the earliest day a fire reaches it, which is the weighted shortest-path
distance from the initial fires. Water does not delay the fire, it puts it out: a fire reaching a
field whose owner waters that day goes to zero and stops there, so the field is saved and nothing
spreads from it. An unwatered field catches fire twice as strong, up to a cap.

Optional rules make the game a long one instead of a single fire. A burnt-out field regrows after
`regrow_days` and can burn again; the world may hold random ignitions (a fire starting from
nothing on a given day); and the world's horizon ends the game on a fixed day. After watering, an
agent must rest `water_cooldown` days before it can water again.

Attributes without an underscore (day, fields, revealed) are for reading.
Only step() changes them.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass, replace

from .field import Field, FieldState
from .world import Edge, World


class WaterRuleError(ValueError):
    """An agent tried to water before its cooldown was over, with none left, or does not exist."""


@dataclass(frozen=True)
class FireRules:
    burn_days: int = 2  # days a field stays burning before it is burnt out
    growth_if_unwatered: float = 2.0  # intensity multiplier when fire spreads to an unwatered field
    min_intensity: float = 0.2  # a fire weaker than this fizzles out instead of igniting
    max_intensity: float = 4.0  # growth stops here
    water_per_agent: int | None = None  # waterings per agent in total; None = no limit
    water_cooldown: int = 1  # days an agent must rest after watering before it can water again
    regrow_days: int | None = None  # days a burnt-out field takes to regrow; None = never
    # what a wasted watering (no fire came that day) costs, counted in burnt fields. Only the
    # score and the agents' instructions use it: the fire does not care.
    waste_penalty: float = 0.0

    def __post_init__(self):
        if self.water_cooldown < 0:
            raise ValueError("water_cooldown cannot be negative")
        if self.regrow_days is not None and self.regrow_days < 1:
            raise ValueError("regrow_days must be at least 1")


@dataclass(frozen=True)
class Ignition:
    """Fire reaching field `field_id` on `day` along `edge`.

    While pending, `intensity` is the strength of the fire it comes from. Once it ignites, the
    reported ignition carries the strength the field caught fire with. A random ignition has no
    edge: the fire came from nowhere.
    """

    field_id: int
    day: int
    intensity: float
    edge: Edge | None

    @property
    def source(self) -> int | None:
        return None if self.edge is None else self.edge.src

    @property
    def via_hidden(self) -> bool:
        return self.edge is not None and self.edge.hidden


@dataclass(frozen=True)
class DayReport:
    day: int
    ignited: tuple[Ignition, ...]
    burnt_out: tuple[int, ...]
    hit_while_watered: tuple[int, ...]  # fields fire reached today whose owner watered
    revealed_hidden: tuple[Edge, ...]  # hidden edges used for the first time today
    regrown: tuple[int, ...] = ()  # burnt fields that grew back today and can burn again


class FireSim:
    def __init__(self, world: World, rules: FireRules | None = None):
        self.world = world
        self.rules = rules or FireRules()
        self.day = 0
        self.fields = [Field(f, world.owner(f)) for f in range(world.n_fields)]
        self.revealed: set[Edge] = set()
        self._last_watered_day: dict[int, int] = {}
        self._times_watered: dict[int, int] = {}
        self._pending: dict[int, list[Ignition]] = {}
        self._out: dict[int, list[Edge]] = {}
        for edge in world.edges:
            self._out.setdefault(edge.src, []).append(edge)
        self._random = dict(world.random_ignitions)  # day -> field
        for field_id, intensity in world.initial_fires:  # already burning when the game starts
            self._ignite(field_id, 0, intensity)

    @property
    def finished(self) -> bool:
        horizon = self.world.config.horizon
        if horizon is not None:
            return self.day >= horizon
        return not self._pending and not any(f.state is FieldState.BURNING for f in self.fields)

    def upcoming(self, day: int) -> tuple[Ignition, ...]:
        """Ignitions queued for `day`. Agents cannot see this; policies that do are omniscient."""
        return tuple(self._pending.get(day, ()))

    def can_water_today(self, agent: int) -> bool:
        known = 0 <= agent < self.world.config.n_agents
        last = self._last_watered_day.get(agent)
        rested = last is None or self.day - last > self.rules.water_cooldown
        return known and rested and self.water_left(agent) != 0

    def water_left(self, agent: int) -> int | None:
        """Waterings this agent still has, or None if the rules set no limit."""
        limit = self.rules.water_per_agent
        return None if limit is None else limit - self._times_watered.get(agent, 0)

    def step(self, agents_water_today: Collection[int] = frozenset()) -> DayReport:
        """Resolve the current day. `agents_water_today` is the set of agents that water today."""
        day = self.day
        for agent in agents_water_today:
            if not self.can_water_today(agent):
                raise WaterRuleError(f"agent {agent} cannot water on day {day}")
        for agent in agents_water_today:
            self._last_watered_day[agent] = day
            self._times_watered[agent] = self._times_watered.get(agent, 0) + 1

        ignited, hit_while_watered, revealed = self._ignite_fields_today(
            day, frozenset(agents_water_today)
        )
        burnt_out = self._burn_out(day)
        regrown = self._regrow(day)

        self.day += 1
        return DayReport(
            day, tuple(ignited), burnt_out, tuple(hit_while_watered), tuple(revealed), regrown
        )
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
            best = min(by_field[field_id], key=lambda a: (-a.intensity, a.source or 0))
            owner_waters_today = self.fields[field_id].owner in agents_water_today
            if owner_waters_today:
                hit_while_watered.append(field_id)
            if owner_waters_today:
                continue  # put out: intensity 0, the field does not ignite and fire stops here
            rules = self.rules
            intensity = min(best.intensity * rules.growth_if_unwatered, rules.max_intensity)
            if intensity < self.rules.min_intensity:
                continue
            ignited.append(replace(best, intensity=intensity))
            self._ignite(field_id, day, intensity)
            if best.edge is not None and best.edge.hidden and best.edge not in self.revealed:
                self.revealed.add(best.edge)
                revealed.append(best.edge)

        # A random ignition starts at the starting strength and does not grow: nothing fed it.
        # Like any fire, it is put out if the owner happens to water that day.
        field_id = self._random.get(day)
        if field_id is not None and self.fields[field_id].state is FieldState.UNBURNT:
            if self.fields[field_id].owner in agents_water_today:
                hit_while_watered.append(field_id)
            else:
                intensity = self.world.config.initial_intensity
                ignited.append(Ignition(field_id, day, intensity, None))
                self._ignite(field_id, day, intensity)
        return ignited, hit_while_watered, revealed

    def _burn_out(self, day: int) -> tuple[int, ...]:
        done = [
            f
            for f in self.fields
            if f.state is FieldState.BURNING
            and f.ignited_on is not None
            and day - f.ignited_on >= self.rules.burn_days
        ]
        for f in done:
            f.state, f.burnt_on = FieldState.BURNT, day
        return tuple(f.id for f in done)

    def _regrow(self, day: int) -> tuple[int, ...]:
        regrow_days = self.rules.regrow_days
        if regrow_days is None:
            return ()
        done = [
            f
            for f in self.fields
            if f.state is FieldState.BURNT
            and f.burnt_on is not None
            and day - f.burnt_on >= regrow_days
        ]
        for f in done:
            f.state = FieldState.UNBURNT
        return tuple(f.id for f in done)

    def _ignite(self, field_id: int, day: int, intensity: float) -> None:
        f = self.fields[field_id]
        f.state, f.ignited_on, f.intensity = FieldState.BURNING, day, intensity
        f.ignitions.append(day)
        for edge in self._out.get(field_id, []):
            # A field that regrows may be unburnt again by the time the fire arrives, so with
            # regrowth every arrival is queued and checked when it lands.
            regrows = self.rules.regrow_days is not None
            if regrows or self.fields[edge.dst].state is FieldState.UNBURNT:
                self._schedule(Ignition(edge.dst, day + edge.weight, intensity, edge))

    def _schedule(self, ignition: Ignition) -> None:
        self._pending.setdefault(ignition.day, []).append(ignition)


# A watering policy is just a function: given the game, return the agents that water today.
WateringPolicy = Callable[[FireSim], Collection[int]]


def play(sim: FireSim, policy: WateringPolicy, max_days: int = 1000) -> list[DayReport]:
    reports: list[DayReport] = []
    while not sim.finished:
        if sim.day >= max_days:
            raise RuntimeError(f"fire still burning after {max_days} days")
        reports.append(sim.step(policy(sim)))
    return reports


def fields_saved(sim: FireSim) -> int:
    """Fields that never ignited."""
    return sum(1 for f in sim.fields if f.state is FieldState.UNBURNT)
