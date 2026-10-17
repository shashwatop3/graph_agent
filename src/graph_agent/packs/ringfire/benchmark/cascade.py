"""Turn run logs (trace.py) into the data the Cascade viewer plays back.

The viewer compares systems on one game: the same scenario played by, say, the graph memory and a
prompt-only baseline. Each log becomes one `RunView`: the world day by day, every message with its
route and whether an imposter altered it, each trust cut, what every agent read back from its tools
and said at the end of its turn, and, for graph systems, every belief with the chain that explains
it.

A belief's chain is what the viewer shows when you ask "why does A15 hold this?":
  * where it came from: the routes that SUPPORT it (each a list of agents it was RELAYED_VIA), or
    the beliefs it was DERIVED_FROM, or "seen directly";
  * which exposures cut those routes, on which day and why, and when it went stale;
  * what was derived from it;
  * who it was passed on to, and the belief it became in each receiver's memory.

Everything is read from the log; nothing is recomputed from the game rules. Logs written before the
`beliefs` snapshot carried `created_tick` and `sources` are still read: those two then come from the
agents' `assert_belief` calls, and a belief no call created takes the day of the closest earlier id
(ids come from one counter, so they are in creation order).
"""

import json
import re
from pathlib import Path
from typing import Any, TypedDict

# One log line. Its fields depend on its kind (see trace.py), so it stays loosely typed here and
# every value is converted where it is read.
Event = dict[str, Any]

STEP_RESULT_CHARS = 400  # a tool's answer can be a long listing; the viewer needs the start

# The built page (viewer/cascade in this pack, `npm run build`) and the tag in it that receives
# the data.
TEMPLATE = Path(__file__).resolve().parents[1] / "viewer" / "cascade.html"
DATA_TAG = '<script id="cascade-data" type="application/json">__CASCADE_DATA__</script>'


class DayView(TypedDict):
    day: int
    ignited: list[int]  # fields that caught fire
    burnt_out: list[int]
    regrown: list[int]  # burnt fields that grew back (the long game)
    saved: list[int]  # fields the fire reached on a day they were watered
    watered: list[int]  # agents who watered
    links_added: list[list[int]]


class MessageView(TypedDict):
    day: int
    sender: int
    receiver: int
    route: list[int]  # every agent the claim passed through, the first one included
    field: int
    claim_day: int
    altered: bool  # an imposter changed or invented the claim on its way


class ExposureView(TypedDict):
    day: int
    viewer: int
    distrusted: int
    reason: str
    changed: list[str]  # belief ids whose status changed


class StepView(TypedDict):
    tool: str
    arguments: dict[str, Any]
    result: str
    error: bool


class TurnView(TypedDict):
    final: str
    steps: list[StepView]


class CutView(TypedDict):
    day: int
    agent: int
    reason: str


class SentView(TypedDict):
    day: int
    to: int


class BecameView(TypedDict):
    agent: int
    id: str


class BeliefView(TypedDict):
    id: str
    field: int
    value: Any  # the arrival day; an agent can assert anything, such as "unknown"
    origin: str  # told, observed or derived
    status: str  # at the end of the game
    born: int  # the day it was created
    history: list[list[Any]]  # [day, new status] for every change an exposure made
    routes: list[list[int]]  # supporting routes; [] in the list is a direct observation
    sources: list[str]  # DERIVED_FROM
    dependents: list[str]  # derived from this one
    cuts: list[CutView]  # exposures of an agent on one of its routes
    sent: list[SentView]
    became: list[BecameView]
    true: bool | None  # what the oracle says about the claim


class RunView(TypedDict):
    system: str
    model: str
    days: list[DayView]
    messages: list[MessageView]
    exposures: list[ExposureView]
    turns: dict[str, TurnView]  # "agent|day", e.g. "15|2"
    beliefs: dict[str, list[BeliefView]]  # agent number -> beliefs; empty with no belief store
    score: dict[str, Any]


class ScenarioView(TypedDict):
    seed: int
    n_agents: int
    fields_per_agent: int
    n_fields: int
    imposters: dict[str, str]  # agent number -> behaviour
    start_links: list[list[int]]  # links beyond the ring at the start


class CascadeData(TypedDict):
    scenario: ScenarioView
    runs: dict[str, RunView]  # label -> run, in the order given


def read_log(path: str | Path) -> list[Event]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _agent(name: Any) -> int:
    """'A15' or 15 -> 15."""
    return int(str(name).removeprefix("A"))


def _field(subject: Any) -> int:
    return int(str(subject).removeprefix("F"))


def scenario_view(events: list[Event]) -> ScenarioView:
    start = events[0]
    if start["kind"] != "game_start":
        raise ValueError("a run log starts with game_start")
    scenario: dict[str, Any] = start["scenario"]
    world: dict[str, Any] = scenario["world"]
    return {
        "seed": int(scenario.get("seed", 0)),
        "n_agents": int(world["n_agents"]),
        "fields_per_agent": int(world.get("fields_per_agent", 1)),
        "n_fields": int(start["n_fields"]),
        "imposters": {str(k): str(v) for k, v in dict(start["imposters"]).items()},
        "start_links": [sorted(int(a) for a in link) for link in scenario.get("links", [])],
    }


def run_view(events: list[Event]) -> RunView:
    start = events[0]
    days: list[DayView] = []
    messages: list[MessageView] = []
    exposures: list[ExposureView] = []
    turns: dict[str, TurnView] = {}
    current: TurnView | None = None
    scenario = scenario_view(events)
    n = scenario["n_agents"]
    # links known so far: the ring and the starting shortcuts; anything else was built in the game
    links = {tuple(sorted((a, (a + 1) % n))) for a in range(n)}
    links |= {tuple(link) for link in scenario["start_links"]}
    score: dict[str, Any] = {}

    for e in events:
        kind = e["kind"]
        if kind == "turn_start":
            current = {"final": "", "steps": []}
            turns[f"{_agent(e['agent'])}|{e['day']}"] = current
        elif kind == "tool_result" and current is not None:
            current["steps"].append(
                {
                    "tool": str(e["tool"]),
                    "arguments": dict(e.get("arguments") or {}),
                    "result": str(e["result"])[:STEP_RESULT_CHARS],
                    "error": bool(e["error"]),
                }
            )
        elif kind == "turn_end" and current is not None:
            current["final"] = str(e.get("final_text") or "")
            current = None
        elif kind == "message" and not e.get("held"):  # a held message is logged again on delivery
            messages.append(
                {
                    "day": int(e["day"]),
                    "sender": int(e["sender"]),
                    "receiver": int(e["receiver"]),
                    "route": [int(a) for a in e["route"]],
                    "field": int(e["field"]),
                    "claim_day": int(e["claim_day"]),
                    "altered": bool(e["altered_by"]),
                }
            )
        elif kind == "day_end":
            now = {tuple(sorted(int(a) for a in link)) for link in e.get("links", [])}
            fresh = sorted(now - links)
            links |= now
            days.append(
                {
                    "day": int(e["day"]),
                    "ignited": [int(i[0]) for i in e["ignited"]],
                    "burnt_out": [int(f) for f in e["burnt_out"]],
                    "regrown": [int(f) for f in e.get("regrown", [])],
                    "saved": [int(f) for f in e["hit_while_watered"]],
                    "watered": [int(a) for a in e["watered"]],
                    "links_added": [list(link) for link in fresh],
                }
            )
        elif kind == "exposure":
            exposures.append(
                {
                    "day": int(e["day"]),
                    "viewer": _agent(e["viewer"]),
                    "distrusted": _agent(e["distrusted"]),
                    "reason": str(e.get("reason") or ""),
                    "changed": [str(c[0]) for c in e["changes"]],
                }
            )
        elif kind == "score":
            score = {k: v for k, v in e.items() if k not in ("t", "kind")}

    return {
        "system": str(start["system"]),
        "model": str(start.get("model", "")),
        "days": days,
        "messages": messages,
        "exposures": exposures,
        "turns": turns,
        "beliefs": belief_chains(events),
        "score": score,
    }


RECORDED = re.compile(r"recorded (B\d+)")


def belief_chains(events: list[Event]) -> dict[str, list[BeliefView]]:
    """Every belief in the end-of-game snapshot, with its chain. Empty for a log without one."""
    snapshot = [e for e in events if e["kind"] == "beliefs"]
    if not snapshot:
        return {}
    number = {str(b["belief"]): int(str(b["belief"]).removeprefix("B")) for b in snapshot}
    owner = {str(b["belief"]): _agent(b["agent"]) for b in snapshot}

    # what the agents' own tool calls say: creation day, parents, and sends by belief id
    born: dict[str, int] = {}
    sources: dict[str, list[str]] = {}
    sent: dict[str, list[SentView]] = {}
    for e in events:
        if e["kind"] != "tool_result" or e.get("error"):
            continue
        arguments: dict[str, Any] = dict(e.get("arguments") or {})
        found = RECORDED.match(str(e["result"]))
        if e["tool"] == "assert_belief" and found:
            born[found[1]] = int(e["day"])
            parents: list[Any] = arguments.get("depends_on") or []
            sources[found[1]] = [str(s) for s in parents]
        sent_ok = str(e["result"]).startswith("sent to")
        if e["tool"] == "send" and sent_ok and "belief_id" in arguments:
            sent.setdefault(str(arguments["belief_id"]), []).append(
                {"day": int(e["day"]), "to": _agent(arguments["to"])}
            )
    for b in snapshot:  # the snapshot itself, when the log has it, is the better record
        if "created_tick" in b:
            born[str(b["belief"])] = int(b["created_tick"])
        if "sources" in b:
            sources[str(b["belief"])] = [str(s) for s in b["sources"]]

    # Imposters pass messages on without a toolbox; the engine logs those as imposter_relay. Tie
    # each one to the told belief in the imposter's memory that carries the same claim.
    for e in events:
        if e["kind"] == "imposter_relay" and e.get("delivered"):
            for b in snapshot:
                if (
                    owner[str(b["belief"])] == int(e["imposter"])
                    and b["origin"] == "told"
                    and _field(b["subject"]) == int(e["field"])
                    and b["value"] == e["claim_day"]
                ):
                    sent.setdefault(str(b["belief"]), []).append(
                        {"day": int(e["day"]), "to": int(e["to"])}
                    )

    # a told belief is born the day its first supporting message was delivered
    delivered = [e for e in events if e["kind"] == "message" and not e.get("held")]
    for b in snapshot:
        bid = str(b["belief"])
        if bid in born or b["origin"] != "told":
            continue
        days = [
            int(m["day"])
            for m in delivered
            if int(m["receiver"]) == owner[bid]
            and int(m["field"]) == _field(b["subject"])
            and m["claim_day"] == b["value"]
            and [int(a) for a in m["route"]] in [[_agent(a) for a in r] for r in b["routes"]]
        ]
        if days:
            born[bid] = min(days)
    last = 0
    for bid in sorted(number, key=number.__getitem__):  # anything left: the closest earlier id
        last = born.setdefault(bid, last)

    exposures = [e for e in events if e["kind"] == "exposure"]
    chains: dict[str, list[BeliefView]] = {}
    for b in sorted(snapshot, key=lambda b: number[str(b["belief"])]):
        bid, agent = str(b["belief"]), owner[str(b["belief"])]
        routes = [[_agent(a) for a in r] for r in b["routes"]]
        history = [
            [int(x["day"]), str(c[2])]
            for x in exposures
            if _agent(x["viewer"]) == agent
            for c in x["changes"]
            if c[0] == bid
        ]
        cuts: list[CutView] = [
            {"day": int(x["day"]), "agent": _agent(x["distrusted"]), "reason": str(x["reason"])}
            for x in exposures
            if _agent(x["viewer"]) == agent and any(_agent(x["distrusted"]) in r for r in routes)
        ]
        # the belief each receiver formed from it: same claim, a route that ends with this agent
        became: list[BecameView] = (
            [
                {"agent": owner[str(o["belief"])], "id": str(o["belief"])}
                for o in snapshot
                if o["origin"] == "told"
                and o["subject"] == b["subject"]
                and o["value"] == b["value"]
                and any(r and _agent(r[-1]) == agent for r in o["routes"])
            ]
            if bid in sent
            else []
        )
        chains.setdefault(str(agent), []).append(
            {
                "id": bid,
                "field": _field(b["subject"]),
                "value": b["value"],
                "origin": str(b["origin"]),
                "status": str(b["status"]),
                "born": born[bid],
                "history": history,
                "routes": routes,
                "sources": sources.get(bid, []),
                "dependents": sorted(
                    (d for d, parents in sources.items() if bid in parents and d in owner),
                    key=number.__getitem__,
                ),
                "cuts": cuts,
                "sent": sent.get(bid, []),
                "became": became,
                "true": b.get("claim_true"),
            }
        )
    return chains


def cascade_data(logs: dict[str, str | Path]) -> CascadeData:
    """The viewer's data for one game played by several systems: label -> log path.

    The logs must be of the same scenario, or the comparison would mean nothing."""
    if not logs:
        raise ValueError("give at least one run log")
    runs: dict[str, RunView] = {}
    first: tuple[str, Any] | None = None  # (label, scenario as logged)
    for label, path in logs.items():
        events = read_log(path)
        if first is None:
            first = (label, events[0]["scenario"])
        elif events[0]["scenario"] != first[1]:
            raise ValueError(f"{label} is a different game from {first[0]}")
        runs[label] = run_view(events)
    return {"scenario": scenario_view(read_log(next(iter(logs.values())))), "runs": runs}


def write_viewer(data: CascadeData, path: str | Path, template: str | Path = TEMPLATE) -> Path:
    """A self-contained page that plays `data` back: it opens by double-click, no server needed."""
    page = Path(template).read_text()
    if page.count(DATA_TAG) != 1:
        raise ValueError(f"{template} is not the built Cascade page (run npm run build)")
    # "<" escaped, so nothing in the data can end the script tag or open a comment inside it
    payload = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page.replace(DATA_TAG, DATA_TAG.replace("__CASCADE_DATA__", payload)))
    return out
