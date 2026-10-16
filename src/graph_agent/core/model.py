"""The six node types and nine relationship types. Identical for every domain.

Domain meaning lives only in values: an Entity's `type`, a Belief's `predicate`, an Action's
`type`. The core never interprets them (except through the predicate registry, see registry.py).
"""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- allowed values ---------------------------------------------------------------------------
# Plain string types, checked when a model is created.

AgentStatus = Literal["active", "offline"]
ObservationKind = Literal["sensor", "message", "evidence"]  # seen, told, published by the engine
Origin = Literal["observed", "told", "derived"]
BeliefKind = Literal["fact", "forecast", "assessment", "plan"]
# suspect: support weakened, re-check. stale: proved wrong. superseded: a newer version exists.
# retracted: withdrawn by its source.
BeliefStatus = Literal["active", "suspect", "stale", "superseded", "retracted"]
ActionStatus = Literal["planned", "committed", "done", "cancelled"]
CorrectionType = Literal["exposure", "revision", "supersession", "retraction", "new_edge"]


# ---- nodes ------------------------------------------------------------------------------------


class Agent(Strict):
    id: str
    role: str = ""
    goals: str = ""
    status: AgentStatus = "active"
    joined_tick: int = 0


class Observation(Strict):
    """Immutable. The route it took is stored as RELAYED_VIA edges so it can be traversed."""

    id: str
    kind: ObservationKind
    payload: dict[str, Any] = Field(default_factory=dict)
    received_by: str
    sender: str | None = None  # None for sensor and evidence
    about_tick: int = 0  # when the reported thing happened
    received_tick: int = 0
    hash: str = ""  # content fingerprint, filled in when empty

    def model_post_init(self, _context) -> None:
        if not self.hash:
            blob = json.dumps(self.payload, sort_keys=True, default=str).encode()
            self.hash = hashlib.sha256(blob).hexdigest()[:16]


class Entity(Strict):
    id: str
    type: str  # from the adapter's entity list
    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    owner: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)  # not interpreted by the core


class Belief(Strict):
    id: str
    version: int = 1
    owner: str
    subject: str  # an Entity id
    predicate: str  # from the registry; decides the contradiction rule
    value: Any
    unit: str | None = None
    origin: Origin = "told"
    kind: BeliefKind = "fact"
    confidence: float = Field(default=1.0, ge=0, le=1)
    status: BeliefStatus = "active"
    valid_from: int | None = None  # None is open-ended
    valid_to: int | None = None
    created_tick: int = 0
    updated_tick: int = 0
    support_routes: int = 0  # a cache; the edges are the truth


class Action(Strict):
    id: str
    owner: str
    type: str  # from the adapter's action list
    target: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = "planned"
    reversible: bool = True


class Correction(Strict):
    id: str
    type: CorrectionType
    issued_by: str  # "engine" or an agent id
    target: str  # agent, entity or belief concerned
    tick: int
    reason: str = ""
    new_value: Any = None
    observer: str | None = None  # whose graph it applies to; None means everyone's


Node = Agent | Observation | Entity | Belief | Action | Correction


def as_type[N: Node](node: Node | None, kind: type[N]) -> N:
    """`node` as a `kind`, or TypeError if it is missing or something else (a store bug)."""
    if not isinstance(node, kind):
        raise TypeError(f"expected a {kind.__name__}, found {node!r}")
    return node


# ---- relationships ----------------------------------------------------------------------------


EdgeKind = Literal[
    "LINKED",  # Agent -> Agent
    "TRUSTS",  # Agent -> Agent
    "RELAYED_VIA",  # Observation -> Agent, prop `hop`
    "SUPPORTS",  # Observation -> Belief
    "DERIVED_FROM",  # Belief or Action -> Belief
    "ABOUT",  # Belief or Observation -> Entity
    "RELATES",  # Entity -> Entity
    "CONTRADICTS",  # Correction -> Belief
    "INVALIDATED",  # Correction -> Belief
]


class Edge(Strict):
    kind: EdgeKind
    src: str
    dst: str
    props: dict[str, Any] = Field(default_factory=dict)


# which node types each relationship may join: kind -> (source types, target types)
EDGE_RULES: dict[str, tuple[tuple[type, ...], tuple[type, ...]]] = {
    "LINKED": ((Agent,), (Agent,)),
    "TRUSTS": ((Agent,), (Agent,)),
    "RELAYED_VIA": ((Observation,), (Agent,)),
    "SUPPORTS": ((Observation,), (Belief,)),
    "DERIVED_FROM": ((Belief, Action), (Belief,)),
    "ABOUT": ((Belief, Observation), (Entity,)),
    "RELATES": ((Entity,), (Entity,)),
    "CONTRADICTS": ((Correction,), (Belief,)),
    "INVALIDATED": ((Correction,), (Belief,)),
}


def check_edge(edge: Edge, src: Node, dst: Node) -> None:
    """Raise ValueError unless `edge` joins the node types its kind allows."""
    src_types, dst_types = EDGE_RULES[edge.kind]
    if not isinstance(src, src_types) or not isinstance(dst, dst_types):
        raise ValueError(
            f"{edge.kind} cannot join {type(src).__name__} {edge.src!r} "
            f"to {type(dst).__name__} {edge.dst!r}"
        )


# ---- visibility -------------------------------------------------------------------------------


def visible(viewer: str, node: Node) -> bool:
    """Fog of war: an agent sees only what it holds or received. Enforced here, not by prompting."""
    if isinstance(node, Belief | Action):
        return node.owner == viewer
    if isinstance(node, Observation):
        return node.received_by == viewer
    if isinstance(node, Correction):
        return node.observer is None or node.observer == viewer
    return True  # agents and entities are shared
