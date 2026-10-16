"""The shapes shared by the game loop, the backends and the agent loop, so each boundary is typed.

`SendFn` and `ExecuteFn` are what the game hands a backend so its tools can reach the game.
`Tools` is what the agent loop needs from a toolbox, whichever backend built it.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

from ..core.model import Action

# (sender, receiver, field number, day, relay) -> text for the model. Raises ValueError to refuse.
SendFn = Callable[[int, int, int, int, bool], str]
# (action) -> text for the model. Raises ValueError to refuse.
ExecuteFn = Callable[[Action], str]
# (game, backend, day) -> None, called after every day is played.
AfterDay = Callable[..., None]


class Tools(Protocol):
    """One agent's tools for one turn. The loop shows the model `names` and calls them by name."""

    names: Sequence[str]
    now: int
