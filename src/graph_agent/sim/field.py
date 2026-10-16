"""One field and everything that changes about it during a game."""

from dataclasses import dataclass, field
from enum import Enum


class FieldState(Enum):
    UNBURNT = "unburnt"
    BURNING = "burning"
    BURNT = "burnt"


@dataclass
class Field:
    """One field and everything that changes about it."""

    id: int
    owner: int
    state: FieldState = FieldState.UNBURNT
    ignited_on: int | None = None  # day it last caught fire
    intensity: float | None = None  # strength it last caught fire with
    burnt_on: int | None = None  # day it last burnt out
    ignitions: list[int] = field(default_factory=list[int])  # every day it caught fire, in order
