"""The shapes shared by the game loop, the backends and the agent loop, so each boundary is typed.

`SendFn` and `ExecuteFn` are what the game hands a backend so its tools can reach the game.
`Tools` (now in harness/agent.py) is what the agent loop needs from a toolbox.
"""

from collections.abc import Callable
from typing import Protocol

from graph_agent.core.model import Action
from graph_agent.core.store import Exposure
from graph_agent.harness.agent import Tools

from ..sim.comms import Message
from ..sim.game import DayResult, Game

# (sender, receiver, field number, day, relay) -> text for the model. Raises ValueError to refuse.
SendFn = Callable[[int, int, int, int, bool], str]
# (action) -> text for the model. Raises ValueError to refuse.
ExecuteFn = Callable[[Action], str]


class Backend(Protocol):
    name: str

    @property
    def exposures(self) -> list[Exposure]: ...

    def start(self, game: Game) -> None: ...

    def message(self, message: Message) -> None: ...

    def day(self, game: Game, result: DayResult) -> None: ...

    def context(self, number: int, day: int, budget: int) -> str: ...

    def toolbox(self, number: int, send: SendFn, execute: ExecuteFn) -> Tools: ...


# (game, backend, day) -> None, called after every day is played.
AfterDay = Callable[[Game, Backend, int], None]
