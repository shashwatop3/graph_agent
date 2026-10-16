"""The whole game: the fire, the message network, and the evidence the engine publishes."""

from collections.abc import Collection
from dataclasses import dataclass

from .comms import Claim, Imposter, Message, Network
from .fire import DayReport, FireRules, FireSim
from .world import World


@dataclass(frozen=True)
class Evidence:
    """Published to everyone when fire reaches a field. Both setups receive exactly this."""

    day: int
    field_id: int
    owner: int
    intensity: float


@dataclass(frozen=True)
class DayResult:
    report: DayReport
    evidence: tuple[Evidence, ...]  # fields that caught fire today (day 0 includes the start fires)


class Game:
    def __init__(
        self,
        world: World,
        rules: FireRules | None = None,
        imposters: tuple[Imposter, ...] = (),
    ):
        self.sim = FireSim(world, rules)
        self.net = Network(world.config.n_agents, imposters)

    @property
    def day(self) -> int:
        return self.sim.day

    @property
    def finished(self) -> bool:
        return self.sim.finished

    def send(
        self, sender: int, receiver: int, claim: Claim, relaying: Message | None = None
    ) -> Message | None:
        """Send a message today. The receiver has it at once."""
        return self.net.send(sender, receiver, claim, self.day, relaying)

    def step(self, agents_water_today: Collection[int] = frozenset()) -> DayResult:
        """Play one day: watering and fire, then publish the evidence."""
        day = self.day
        report = self.sim.step(agents_water_today)
        evidence = [
            Evidence(day, i.field_id, self._owner(i.field_id), i.intensity) for i in report.ignited
        ]
        if day == 0:
            start = [Evidence(0, f, self._owner(f), i) for f, i in self.sim.world.initial_fires]
            evidence = start + evidence
        return DayResult(report, tuple(evidence))

    def _owner(self, field_id: int) -> int:
        return self.sim.fields[field_id].owner
