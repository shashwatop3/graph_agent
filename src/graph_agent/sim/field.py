"""One field and everything that changes about it during a game."""

from dataclasses import dataclass
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
    ignited_on: int | None = None  # day it caught fire
    intensity: float | None = None  # strength it caught fire with
