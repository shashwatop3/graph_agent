"""The team file: which nodes there are, what wakes each one, what it may use, how they are linked.

A team is what the user draws on the canvas, saved as JSON. The runtime builds the live nodes
from it, so a team file and the canvas describe exactly the same thing.

    {
      "name": "my week",
      "pack": "life",
      "settings": {"mode": "lockstep", "budget": 4000},
      "nodes": [
        {"id": "mail", "type": "stream", "label": "Mailbox", "config": {"feed": "mail"}},
        {"id": "travel", "type": "agent", "role": "Travel agent",
         "triggers": [{"on": "item"}, {"on": "change"}], "tools": ["flight.status"]}
      ],
      "links": [
        {"kind": "feeds", "src": "mail", "dst": "router"},
        {"kind": "owns", "src": "travel", "dst": "type:Trip"},
        {"kind": "talks_to", "src": "travel", "dst": "calendar"}
      ]
    }

Links between nodes are the team's setup. They are kept apart from the nine edge kinds of the
belief graph, which no user edits by hand.
"""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# What can wake a node:
#   tick      every tick of the clock (lockstep: every agent, every day)
#   schedule  every `every` ticks, starting at tick `at`
#   item      an item from a stream reached it (routed to an entity it owns, or addressed to it)
#   message   another node sent it a belief
#   change    a belief of its own changed status (a correction reached it)
#   due       one of its live beliefs about an entity it owns falls due within `within` ticks
#   exposure  someone it talks to was exposed as unreliable
#   approval  a person approved or rejected one of its proposed actions
TriggerKind = Literal[
    "tick", "schedule", "item", "message", "change", "due", "exposure", "approval"
]

LinkKind = Literal["feeds", "owns", "talks_to", "watches"]

Mode = Literal["lockstep", "wake"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Trigger(Strict):
    on: TriggerKind
    every: int = 1  # schedule: every this many ticks
    at: int = 0  # schedule: the first tick
    within: int = 1  # due: how many ticks ahead counts as due
    predicate: str | None = None  # due: only beliefs with this predicate


class NodeSpec(Strict):
    id: str
    type: str  # a name from the node catalogue (nodes.CATALOGUE) or from a pack
    label: str = ""
    role: str = ""  # agents: who it is, in one line
    goals: str = ""  # agents: what it is for
    triggers: list[Trigger] = Field(default_factory=list[Trigger])
    tools: list[str] = Field(default_factory=list[str])  # its own tools; "mail.*" allows a group
    graph_tools: list[str] | None = None  # None: all of the shared graph tools
    config: dict[str, Any] = Field(default_factory=dict[str, Any])
    position: tuple[float, float] | None = None  # where it sits on the canvas


class LinkSpec(Strict):
    kind: LinkKind
    src: str
    dst: str  # a node id; for "owns", an entity id or "type:<EntityType>"
    props: dict[str, Any] = Field(default_factory=dict[str, Any])


class Settings(Strict):
    mode: Mode = "lockstep"  # lockstep: every triggered node runs every tick; wake: only on news
    budget: int = 4000  # context tokens per agent turn
    max_steps: int = 6  # model rounds per turn
    hold_messages: bool = True  # deliver messages when the tick's turns are over
    blame: Literal["direct_teller", "whole_route", "first_hop"] = "direct_teller"
    # when the real source of a lie is caught, nodes blamed only for passing it on are trusted again
    repair: bool = False
    # a message about a conclusion carries the route of the claims the conclusion rests on, so a
    # node that concludes from a lie and passes it on is not taken for its maker
    trace_provenance: bool = False
    quorum: int | None = None  # warnings: how many reporters before a node acts on one
    ticks: int | None = None  # stop after this many ticks (None: when the environment is done)
    # outward tools (send mail, pay, book): "auto" runs them at once, "manual" waits for a person
    approvals: Literal["auto", "manual", "shadow"] = "auto"
    # when a belief changes, withdraw the copies other nodes got of it from this node
    fan_out: bool = True
    # an outside source one node catches lying: distrusted by that node only, or by the team
    quarantine: Literal["self", "team"] = "self"
    # played in the console: at least this many seconds between two ticks (live data: how often
    # it is read, and so how long a run lasts)
    pace: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict[str, Any])  # for the pack


class TeamSpec(Strict):
    name: str
    pack: str = ""
    description: str = ""
    settings: Settings = Field(default_factory=Settings)
    nodes: list[NodeSpec] = Field(default_factory=list[NodeSpec])
    links: list[LinkSpec] = Field(default_factory=list[LinkSpec])

    @model_validator(mode="after")
    def _check(self) -> "TeamSpec":
        ids = [n.id for n in self.nodes]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"node ids must be unique: {', '.join(duplicates)}")
        known = set(ids)
        for link in self.links:
            if link.src not in known:
                raise ValueError(f"{link.kind} link from unknown node {link.src!r}")
            if link.kind != "owns" and link.dst not in known:
                raise ValueError(f"{link.kind} link to unknown node {link.dst!r}")
        return self

    def node(self, node_id: str) -> NodeSpec:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def links_from(self, node_id: str, kind: LinkKind) -> list[LinkSpec]:
        return [link for link in self.links if link.src == node_id and link.kind == kind]


def load_team(path: str | Path) -> TeamSpec:
    return TeamSpec.model_validate_json(Path(path).read_text())


def save_team(team: TeamSpec, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    data = team.model_dump(mode="json", exclude_defaults=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n")
