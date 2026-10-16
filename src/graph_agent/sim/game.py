"""The whole game: the fire, the message network, and the evidence the engine publishes."""

from collections.abc import Collection
from dataclasses import dataclass

from .comms import Claim, Imposter, Message, Network
from .fire import DayReport, FireRules, FireSim
from .world import World


@dataclass(frozen=True)
class Evidence:
    """The engine's report that fire reached a field. Every system receives exactly this."""

    day: int
    field_id: int
    owner: int
    intensity: float
    audience: tuple[int, ...] = ()  # the agents who are shown it (everyone, unless private)


@dataclass(frozen=True)
class DayResult:
    report: DayReport
    evidence: tuple[Evidence, ...]  # fields that caught fire today (day 0 includes the start fires)


class Game:
    """`private_evidence` decides who is shown evidence.

    False (public): every agent is told the moment fire reaches any field. Then everybody always
    knows where the fire is, and messages add nothing.

    True (private, as in game.md "each agent sees only its own segment"): fire in a field is shown
    only to its owner and to every agent that has been told something about that field, so it can
    check what it was told. Where the fire is otherwise travels only by messages.
    """

    def __init__(
        self,
        world: World,
        rules: FireRules | None = None,
        imposters: tuple[Imposter, ...] = (),
        private_evidence: bool = False,
    ):
        self.sim = FireSim(world, rules)
        self.net = Network(world.config.n_agents, imposters)
        self.private_evidence = private_evidence

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

    def audience(self, field_id: int, day: int) -> tuple[int, ...]:
        """Who is shown that fire reached `field_id`: see the class docstring."""
        if not self.private_evidence:
            return tuple(range(self.sim.world.config.n_agents))
        told = {m.receiver for m in self.net.log if m.claim.field_id == field_id and m.day <= day}
        return tuple(sorted({self._owner(field_id)} | told))

    def step(self, agents_water_today: Collection[int] = frozenset()) -> DayResult:
        """Play one day: watering and fire, then publish the evidence."""
        day = self.day
        report = self.sim.step(agents_water_today)
        ignitions = [(i.field_id, i.intensity) for i in report.ignited]
        if day == 0:
            ignitions = list(self.sim.world.initial_fires) + ignitions
        evidence = [
            Evidence(day, f, self._owner(f), intensity, self.audience(f, day))
            for f, intensity in ignitions
        ]
        return DayResult(report, tuple(evidence))

    def _owner(self, field_id: int) -> int:
        return self.sim.fields[field_id].owner
