"""Ground truth. Reads only what the engine recorded, never what an agent says or believes.

Every question here has one right answer, so scores and propagation checks are measured against it.
"""

from .comms import Claim, Message
from .game import Game


class Oracle:
    def __init__(self, game: Game):
        self._game = game

    # ---- who is lying -------------------------------------------------------------------------

    @property
    def imposters(self) -> frozenset[int]:
        return frozenset(self._game.net.imposters)

    def is_imposter(self, agent: int) -> bool:
        return agent in self._game.net.imposters

    # ---- what is true -------------------------------------------------------------------------

    def ignition_day(self, field_id: int) -> int | None:
        return self._game.sim.fields[field_id].ignited_on

    def claim_is_true(self, claim: Claim) -> bool | None:
        """True or False once the day has passed (or the fire is over). None while still open."""
        known = claim.day < self._game.day or self._game.sim.finished
        return self.ignition_day(claim.field_id) == claim.day if known else None

    def false_messages(self) -> list[Message]:
        """Messages whose claim turned out wrong, whoever sent them and whyever."""
        return [m for m in self._game.net.log if self.claim_is_true(m.claim) is False]

    def tainted_messages(self) -> list[Message]:
        """Messages whose content an imposter originated or changed."""
        return [m for m in self._game.net.log if m.altered_by]

    # ---- what depends on what -----------------------------------------------------------------

    def depends_on(self, message: Message) -> frozenset[int]:
        """The agents a message relies on: everyone it passed through."""
        return frozenset(message.route)

    def lost_if_exposed(self, agent: int) -> list[Message]:
        """Messages that lose their support when `agent` is exposed: those routed through it."""
        return [m for m in self._game.net.log if agent in m.route]
