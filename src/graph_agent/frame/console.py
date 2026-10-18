"""What a pack gives the console, so the service needs no pack-specific code.

A pack that implements `ConsolePack` and is listed in `service/registry.py` appears in the page:
its ready-made teams, its node types and tools for the canvas, its extra run options, and a way to
start a run and read its world and score. The console shows the world through a "lens" the page
knows by name (the `lens` key of `Session.world()`).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.store import Store
from ..harness.llm import ModelClient
from .events import EventLog
from .runtime import Runtime
from .spec import TeamSpec


@dataclass(frozen=True)
class Template:
    name: str
    title: str
    description: str


@dataclass(frozen=True)
class Choice:
    value: str
    label: str


@dataclass(frozen=True)
class RunOption:
    """An extra setting the page offers when a team of this pack is run."""

    key: str
    label: str
    choices: list[Choice]


@dataclass
class PackCatalogue:
    """What the canvas offers for this pack, besides the generic node types."""

    nodes: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    tools: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    predicates: dict[str, str] = field(default_factory=dict[str, str])
    extract_prompt: str = ""  # the router's default reading instructions, when a model reads items


@dataclass
class Session:
    """A started run of a pack: its runtime, and how to read its world, score and clock."""

    runtime: Runtime
    world: Callable[[], dict[str, Any]]
    score: Callable[[], dict[str, Any]]
    clock: Callable[[int], str]


@dataclass(frozen=True)
class Recorded:
    """A recorded run the page can replay from the model cache."""

    path: str
    name: str
    options: dict[str, str]
    checks_passed: int | None = None
    checks_total: int | None = None


class ConsolePack(Protocol):
    name: str
    title: str
    cache_suffix: str  # keeps this pack's model cache apart from the others'
    options: list[RunOption]

    def templates(self) -> list[Template]: ...

    def team(self, name: str, options: dict[str, Any]) -> TeamSpec: ...

    def catalogue(self) -> PackCatalogue: ...

    def stand_in(self, team: TeamSpec) -> ModelClient:
        """The pack's scripted, free model."""
        ...

    def start(
        self,
        team: TeamSpec,
        client: ModelClient,
        store: Store,
        log: EventLog,
        options: dict[str, str],
    ) -> Session: ...

    def recorded(self) -> list[Recorded]: ...
