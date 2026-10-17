"""Fire dynamics, stepped one day at a time. No randomness: the world already holds every draw.

A field ignites on the earliest day a fire reaches it, which is the weighted shortest-path
distance from the initial fires. Water does not delay the fire, it puts it out: a fire reaching a
field whose owner waters that day goes to zero and stops there, so the field is saved and nothing
spreads from it. An unwatered field catches fire twice as strong, up to a cap.

Optional rules make the game a long one instead of a single fire. A burnt-out field regrows after
`regrow_days` and can burn again; the world may hold random ignitions (a fire starting from
nothing on a given day); and the world's horizon ends the game on a fixed day. After watering, an
agent must rest `water_cooldown` days before it can water again.

With `dynamics="linear"` the fire is not all or nothing. Fire arrives at strength `step` (x).
Every later day a burning field grows by x if its owner does not water it and falls by x if they
do, never above `max_intensity`; at 0 it is out and the field is saved. A field that stays at full
strength for `lost_after` days is lost (burnt). A burning field spreads along its edges as before,
and keeps spreading every day it burns; an arrival only lands if the field it comes from was still
burning that morning, so putting a fire out stops it spreading. Watering a field reached by fire
that day puts the fire out on arrival. What happens to a field on a day depends only on its own
owner's watering, so `outcome` can tell an agent the result of watering before the day is played.

Attributes without an underscore (day, fields, revealed) are for reading.
Only step() changes them.
"""

import random
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from typing import Literal

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
    # "binary": the fire above. "linear": strength moves by `step` a day (see the module docstring)
    dynamics: Literal["binary", "linear"] = "binary"
    step: float = 1.0  # linear: an arriving fire's strength, and the daily rise or fall
    lost_after: int = 2  # linear: days at max_intensity before the field is lost
    # linear: fire arrives at strength `step` ("step"), or one step weaker than the field it
    # came from ("source"), so a strong fire next door is a strong fire on arrival
    arrive: Literal["step", "source"] = "step"
    # linear: when every fire is out and none is on its way, a new one starts the next day at a
    # field picked from the world's seed (at the world's starting strength), so a long game goes on
    relight: bool = False

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
    # agents whose watering today met fire at one of their fields, and agents who watered for none
    water_on_fire: tuple[int, ...] = ()
    water_wasted: tuple[int, ...] = ()
    extinguished: tuple[int, ...] = ()  # linear: fields watered down to 0 today
    strength: tuple[tuple[int, float], ...] = ()  # linear: each burning field's strength tonight


@dataclass(frozen=True)
class FieldDay:
    """What one day does to one field (linear fire), given whether its owner waters.

    `event`: "quiet" (no fire), "arrived" (caught fire), "put_out" (fire arrived and was put out),
    "grew", "fell", "out" (watered down to 0), "held" (at full strength), "lost"."""

    field_id: int
    before: float  # strength this morning (0: not burning)
    after: float  # strength tonight
    event: str
    arrival: "Ignition | None" = None  # the fire that reached it today, if any


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
        no_fire = not self._pending and not any(f.state is FieldState.BURNING for f in self.fields)
        if horizon is not None:  # the linear fire can also end early: every fire is out, and
            later = any(day >= self.day for day in self._random)  # no new fire is still to come
            over = self.rules.dynamics == "linear" and no_fire and not later
            return self.day >= horizon or over
        return no_fire

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

    def outcome(self, field_id: int, watered: bool) -> FieldDay:
        """What today does to this field (linear fire) if its owner waters or not. step() applies
        exactly this, so an agent can be told the result of its choice before the day is played."""
        rules, f, day = self.rules, self.fields[field_id], self.day
        if f.state is FieldState.BURNT:
            return FieldDay(field_id, 0.0, 0.0, "quiet")
        if f.state is FieldState.BURNING:
            before = f.intensity or 0.0
            if watered:
                after = max(0.0, before - rules.step)
                return FieldDay(field_id, before, after, "out" if after == 0 else "fell")
            after = min(before + rules.step, rules.max_intensity)
            if after >= rules.max_intensity and f.days_at_cap + 1 >= rules.lost_after:
                return FieldDay(field_id, before, after, "lost")
            return FieldDay(field_id, before, after, "held" if before == after else "grew")
        arrival = self._landing(field_id, day)
        if arrival is None:
            return FieldDay(field_id, 0.0, 0.0, "quiet")
        strength = rules.step if arrival.edge is not None else arrival.intensity  # a new fire
        if rules.arrive == "source" and arrival.edge is not None:
            strength = max(rules.step, (arrival.intensity or 0.0) - rules.step)
        if watered:
            after = max(0.0, strength - rules.step)
            if after == 0:
                return FieldDay(field_id, 0.0, 0.0, "put_out", arrival)
            return FieldDay(field_id, 0.0, after, "arrived", arrival)  # weakened, but it caught
        return FieldDay(field_id, 0.0, strength, "arrived", arrival)

    def _landing(self, field_id: int, day: int) -> "Ignition | None":
        """The fire that reaches this field today, if any: an arrival from a field that was still
        burning this morning (the strongest; ties to the lowest source), or a random ignition."""
        live = [
            a
            for a in self._pending.get(day, [])
            if a.field_id == field_id
            and (a.edge is None or self.fields[a.edge.src].state is FieldState.BURNING)
        ]
        if live:
            return min(live, key=lambda a: (-a.intensity, a.source or 0))
        if self._random.get(day) == field_id:
            return Ignition(field_id, day, self.world.config.initial_intensity, None)
        return None

    def _step_linear(self, day: int, watering: frozenset[int]) -> DayReport:
        days = [self.outcome(f.id, f.owner in watering) for f in self.fields]  # all from dawn
        self._pending.pop(day, None)
        ignited: list[Ignition] = []
        hit: list[int] = []
        revealed: list[Edge] = []
        lost: list[int] = []
        out: list[int] = []
        met_fire: set[int] = set()
        for d in days:
            f = self.fields[d.field_id]
            if d.event != "quiet" and f.owner in watering:
                met_fire.add(f.owner)
            if d.event == "put_out":
                hit.append(f.id)
            elif d.event == "arrived" and d.arrival is not None:
                ignited.append(replace(d.arrival, intensity=d.after))
                self._ignite(f.id, day, d.after)
                edge = d.arrival.edge
                if edge is not None and edge.hidden and edge not in self.revealed:
                    self.revealed.add(edge)
                    revealed.append(edge)
            elif d.event in ("grew", "fell", "held", "lost", "out"):
                f.intensity = d.after
                f.days_at_cap = f.days_at_cap + 1 if d.after >= self.rules.max_intensity else 0
                if d.event == "out":
                    f.state, f.days_at_cap = FieldState.UNBURNT, 0
                    out.append(f.id)
                elif d.event == "lost":
                    f.state, f.burnt_on = FieldState.BURNT, day
                    lost.append(f.id)
        for f in self.fields:  # a fire that burns on keeps pressing on its neighbours
            if f.state is FieldState.BURNING and f.ignited_on != day:
                for edge in self._out.get(f.id, []):
                    self._schedule(Ignition(edge.dst, day + edge.weight, f.intensity or 0.0, edge))
        regrown = self._regrow(day)
        if self.rules.relight:
            self._relight(day + 1)
        self.day += 1
        return DayReport(
            day,
            tuple(ignited),
            tuple(lost),
            tuple(hit),
            tuple(revealed),
            regrown,
            water_on_fire=tuple(sorted(met_fire)),
            water_wasted=tuple(sorted(set(watering) - met_fire)),
            extinguished=tuple(out),
            strength=tuple(
                (f.id, f.intensity or 0.0) for f in self.fields if f.state is FieldState.BURNING
            ),
        )

    def _relight(self, day: int) -> None:
        """Every fire is out and nothing is on its way: a new fire starts on `day`."""
        if any(f.state is FieldState.BURNING for f in self.fields) or day in self._random:
            return
        if any(self._pending.get(d) for d in self._pending if d >= day):
            return
        fields = [f.id for f in self.fields if f.state is FieldState.UNBURNT]
        if fields:
            self._random[day] = random.Random(self.world.seed * 7919 + day).choice(fields)

    def step(self, agents_water_today: Collection[int] = frozenset()) -> DayReport:
        """Resolve the current day. `agents_water_today` is the set of agents that water today."""
        day = self.day
        for agent in agents_water_today:
            if not self.can_water_today(agent):
                raise WaterRuleError(f"agent {agent} cannot water on day {day}")
        for agent in agents_water_today:
            self._last_watered_day[agent] = day
            self._times_watered[agent] = self._times_watered.get(agent, 0) + 1
        if self.rules.dynamics == "linear":
            return self._step_linear(day, frozenset(agents_water_today))

        ignited, hit_while_watered, revealed = self._ignite_fields_today(
            day, frozenset(agents_water_today)
        )
        burnt_out = self._burn_out(day)
        regrown = self._regrow(day)

        self.day += 1
        hit_owners = {self.fields[f].owner for f in hit_while_watered}
        return DayReport(
            day,
            tuple(ignited),
            burnt_out,
            tuple(hit_while_watered),
            tuple(revealed),
            regrown,
            water_on_fire=tuple(sorted(set(agents_water_today) & hit_owners)),
            water_wasted=tuple(sorted(set(agents_water_today) - hit_owners)),
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
            # A linear fire put out leaves the field unburnt, so it can be reached again too.
            regrows = self.rules.regrow_days is not None or self.rules.dynamics == "linear"
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
