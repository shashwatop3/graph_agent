"""Your own agents, in a few lines: each one's name, its job, what it looks after, which apps.

    {
      "name": "My assistant",
      "agents": [
        {"name": "inbox", "job": "Read my mail. Tell the others what matters to them.",
         "apps": ["google_*gmail*"]},
        {"name": "calendar", "job": "Watch my calendar and say when plans clash.",
         "looks_after": ["Event"], "apps": ["google_get_events"]},
        {"name": "tasks", "job": "Put what I promised into Todoist, due when it is due.",
         "looks_after": ["Promise"], "apps": ["todoist_*"], "carries_out": true}
      ]
    }

That is the whole file. `team_of` turns it into a team (spec.py) the console shows and runs:

  * a stream for every feed of your connections (connections.py), and a router that sends each
    item to the agents looking after what it is about (the rest go to `unowned`, by default the
    first agent);
  * every agent may send beliefs to every other, unless it lists `talks_to`;
  * an agent that `carries_out` is woken by what its teammates send it and by changes to what they
    believe, not by mail: least privilege, the node that acts reads no mail;
  * a checker that tests what the team was told against what was checked, and stops trusting a
    sender caught lying;
  * outward actions are only recorded ("shadow") until you say otherwise: "manual" asks you for
    each, "auto" runs them.

`things` are the kinds of thing the team keeps track of and what can be said about each
(`{"Invoice": ["due", "amount"]}`): its own, none by default (a personal team's are THINGS);
`reading` says how to read what comes in (how to name the things
an item is about, so that two sources' reports of one thing meet).

`streams` are live data on the open internet that need no account: `{"preset": "usgs-quakes"}`
(public_streams.py), with filters of yours added (`"keep": {"title": "Taiwan"}`), or a stream
in full (frame/streams.py). Each is a stream node like a feed's, its items routed the same way. A
team with streams is played one poll every `pace` seconds (30 unless it says), so a run of 24
polls watches for twelve minutes.
"""

import fnmatch
import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from graph_agent.frame.connections import Connection
from graph_agent.frame.spec import LinkSpec, NodeSpec, Settings, TeamSpec, Trigger
from graph_agent.frame.streams import Stream, stream_of

from .public_streams import PUBLIC

# kinds of thing a personal team (mail, calendar, tasks) tracks, and what can be said about each
THINGS: dict[str, list[str]] = {
    "Event": ["starts", "ends", "place", "status"],
    "Promise": ["due", "status"],
    "Task": ["due", "status"],
    "Trip": ["departs", "arrives", "status"],
    "Bill": ["due", "amount", "status"],
    "Person": ["email"],
}
RESERVED = {"router", "checker", "me"}
WAKE = [
    Trigger(on="item"),
    Trigger(on="message"),
    Trigger(on="change"),
    Trigger(on="exposure"),
    Trigger(on="approval"),
]
DOER = [Trigger(on="message"), Trigger(on="change"), Trigger(on="approval")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentSetup(Strict):
    name: str
    job: str  # what it is for, in your words
    looks_after: list[str] = Field(default_factory=list[str])  # kinds of thing: "Event"
    apps: list[str] = Field(default_factory=list[str])  # its tools: "todoist_*"
    talks_to: list[str] | None = None  # None: every other agent
    carries_out: bool = False  # it acts on the plans teammates send it, and reads no mail
    role: str = ""  # one line; by default made from its name and what it looks after


class Setup(Strict):
    name: str = "My agents"
    agents: list[AgentSetup]
    things: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    unowned: str | None = None  # gets the items nobody looks after (default: the first agent)
    approvals: Literal["auto", "manual", "shadow"] = "shadow"
    polls: int = 24  # how many times the feeds are read before the run stops
    streams: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    pace: int | None = None  # seconds between two polls when played (None: 30 with streams)
    # how to read what comes in, for the model that lists each item's claims: how to name the
    # things it is about, so two sources' reports of one thing meet ("a quake: q-<place>-<date>")
    reading: str = ""


def things_of(setup: Setup) -> dict[str, list[str]]:
    """The kinds of thing the team keeps track of: its own, each fact once."""
    return {kind: list(dict.fromkeys(facts)) for kind, facts in setup.things.items()}


def streams_of(entries: Sequence[dict[str, Any]]) -> list[Stream]:
    """A team's streams (raises ValueError saying, in words, what is wrong with one)."""
    found: list[Stream] = []
    for n, entry in enumerate(entries, 1):
        name = entry.get("name") or entry.get("preset") or f"number {n}"
        try:
            found.append(stream_of(entry, PUBLIC))
        except ValidationError as error:
            first = error.errors()[0]
            reason = str(first["msg"]).removeprefix("Value error, ")
            where = ".".join(str(part) for part in first["loc"])
            if not reason.startswith("stream "):  # the stream's own checks name it already
                reason = f"stream {name}: " + (f"{where}: {reason}" if where else reason)
            raise ValueError(reason) from None
        except ValueError as error:
            raise ValueError(f"stream {name}: {error}") from None
    return found


def problems(
    setup: Setup, connections: Sequence[Connection], tools: Sequence[str] = ()
) -> list[str]:
    """What is wrong with the setup, in words a person can act on ([] when it is fine). `tools`:
    the connections' tool names, when known, to catch an app pattern that matches nothing."""
    found: list[str] = []
    names = [a.name for a in setup.agents]
    streams: list[Stream] = []
    try:
        streams = streams_of(setup.streams)
    except ValueError as error:
        found.append(str(error))
    fed = [feed.name for c in connections for feed in c.feeds] + [s.name for s in streams]
    for name in sorted({n for n in fed if fed.count(n) > 1}):
        found.append(f'two feeds or streams are named {name!r}: rename one ("name": ...)')
    feeds = {f"{name}-feed" for name in fed}
    kinds = things_of(setup)
    if not setup.agents:
        found.append("add at least one agent")
    for agent in setup.agents:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", agent.name):
            found.append(f"agent {agent.name!r}: use a short lowercase name (letters, digits, -)")
        if agent.name in RESERVED or agent.name in feeds:
            found.append(f"agent {agent.name!r}: that name is taken; pick another")
        if names.count(agent.name) > 1:
            found.append(f"two agents are named {agent.name!r}")
        if not agent.job.strip():
            found.append(f"agent {agent.name}: say what its job is, in a sentence or two")
        for kind in agent.looks_after:
            if kind not in kinds:
                known = f", or use one of {', '.join(sorted(kinds))}" if kinds else ""
                found.append(
                    f"agent {agent.name}: the team keeps track of no {kind!r}; add it to the "
                    f"kinds of thing{known}"
                )
        for peer in agent.talks_to or []:
            if peer not in names:
                found.append(f"agent {agent.name}: talks_to {peer!r}, who is not an agent")
        for pattern in agent.apps:
            if tools and not any(fnmatch.fnmatchcase(t, pattern) for t in tools):
                found.append(f"agent {agent.name}: no app tool matches {pattern!r}")
    if setup.unowned is not None and setup.unowned not in names:
        found.append(f"unowned: {setup.unowned!r} is not an agent")
    if setup.agents and all(a.carries_out for a in setup.agents):
        found.append("every agent carries_out: at least one must read what comes in")
    return found


def team_of(setup: Setup, connections: Sequence[Connection]) -> TeamSpec:
    """The team the setup describes. Raises ValueError listing its problems, if any."""
    wrong = problems(setup, connections)
    if wrong:
        raise ValueError("; ".join(wrong))
    readers = [a for a in setup.agents if not a.carries_out]
    unowned = setup.unowned or readers[0].name
    live = streams_of(setup.streams)
    streams = [
        NodeSpec(
            id=f"{feed.name}-feed",
            type="stream",
            label=connection.label or connection.name,
            config={"feed": feed.name},
        )
        for connection in connections
        for feed in connection.feeds
    ] + [
        NodeSpec(
            id=f"{s.name}-feed",
            type="stream",
            label=s.label or s.name,
            config={"feed": s.name},
        )
        for s in live
    ]
    pace = setup.pace if setup.pace is not None else (30 if live else 0)
    router = NodeSpec(id="router", type="router", label="Router", config={"fallback": unowned})
    agents = [
        NodeSpec(
            id=a.name,
            type="responder" if a.carries_out else "agent",
            label=a.name.replace("-", " ").title(),
            role=a.role or _role(a),
            goals=a.job,
            triggers=DOER if a.carries_out else WAKE,
            tools=list(a.apps),
        )
        for a in setup.agents
    ]
    links = [LinkSpec(kind="feeds", src=s.id, dst="router") for s in streams]
    for a in setup.agents:
        links += [LinkSpec(kind="owns", src=a.name, dst=f"type:{k}") for k in a.looks_after]
        peers = a.talks_to if a.talks_to is not None else [p.name for p in setup.agents]
        links += [LinkSpec(kind="talks_to", src=a.name, dst=p) for p in peers if p != a.name]
        if a.carries_out:
            links += [LinkSpec(kind="watches", src=a.name, dst=r.name) for r in readers if r != a]
    reads = [c.name for c in connections] + [s.name for s in live]
    return TeamSpec(
        name=setup.name,
        pack="apps",
        description=f"{len(agents)} agents on " + (", ".join(reads) or "no apps"),
        settings=Settings(
            mode="wake",
            ticks=setup.polls,
            budget=3500,
            max_steps=8,
            blame="first_hop",
            repair=True,
            trace_provenance=True,
            quarantine="team",
            approvals=setup.approvals,
            pace=pace,
            # the streams go with the team, so one edited on the canvas still reads them
            extra={
                "things": things_of(setup),
                **({"streams": setup.streams} if live else {}),
                **({"reading": setup.reading} if setup.reading else {}),
            },
        ),
        nodes=[*streams, router, *agents, NodeSpec(id="checker", type="checker", label="Checker")],
        links=links,
    )


def _role(agent: AgentSetup) -> str:
    if agent.carries_out:
        return f"{agent.name}: carries out the team's plans"
    if agent.looks_after:
        return f"{agent.name}: looks after {', '.join(agent.looks_after)}"
    return f"{agent.name}: reads what comes in that nobody else looks after"
