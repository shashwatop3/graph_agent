"""Record a finished game as plain JSON, and write the viewer page that plays it back.

The replay holds what a viewer needs and nothing it has to recompute: the ring, the paths fire can
take, and for every day the fires that started, the messages sent (with their true route and
whether an imposter altered them), the shortcut links built, the waterings, and each correction
with the beliefs it changed. The viewer is a single static HTML file with the replay embedded, so
it opens by double-click and needs no server.
"""

import json
from pathlib import Path
from typing import TypedDict

from graph_agent.core.store import Invalidation
from graph_agent.harness.llm import ModelClient

from .. import adapter as ringfire
from ..sim.game import Game
from ..sim.scenario import Scenario
from ..sim.world import WorldConfig
from .backend import GraphBackend
from .game import GameResult, run_game
from .scoring import ScoreRow, score_game
from .types import Backend

TEMPLATE = Path(__file__).resolve().parents[1] / "viewer" / "template.html"


class IgnitedRecord(TypedDict):
    field: int
    intensity: float
    audience: list[int]


class MessageRecord(TypedDict):
    sender: int
    receiver: int
    route: list[int]
    field: int
    claim_day: int
    altered_by: list[int]


class ChangeRecord(TypedDict):
    belief: str
    status: str
    path: int
    text: str


class ExposureRecord(TypedDict):
    viewer: int
    agent: int
    reason: str
    changes: list[ChangeRecord]


class DayRecord(TypedDict):
    day: int
    ignited: list[IgnitedRecord]
    via_hidden: list[list[int]]
    burnt_out: list[int]
    watered: list[int]
    links_added: list[list[int]]
    messages: list[MessageRecord]
    exposures: list[ExposureRecord]


class FieldRecord(TypedDict):
    id: int
    owner: int


class EdgeRecord(TypedDict):
    src: int
    dst: int
    weight: int
    hidden: bool


class Replay(TypedDict):
    system: str
    n_agents: int
    fields: list[FieldRecord]
    edges: list[EdgeRecord]
    imposters: dict[str, str]
    start_links: list[list[int]]
    days: list[DayRecord]
    score: ScoreRow


def _claim_text(backend: Backend, viewer: str, change: Invalidation) -> str:
    """What a changed belief said, in words. Falls back to its id when there is no store."""
    if not isinstance(backend, GraphBackend):
        return change.belief_id
    belief = backend.store.belief(viewer, change.belief_id)
    if belief is None:
        return change.belief_id
    template = ringfire.TEMPLATES.get(belief.predicate, "{predicate}({subject}) = {value}")
    return template.format(
        subject=belief.subject,
        value=belief.value,
        unit=belief.unit or "",
        predicate=belief.predicate,
    )


def build_replay(
    result: GameResult, backend: Backend, links_added: dict[int, list[list[int]]], score: ScoreRow
) -> Replay:
    game = result.game
    world = game.sim.world
    watered: dict[int, list[int]] = {}
    for day, agent, turn in result.turns:
        if any(
            name == "act" and out.endswith("you will water your fields today")
            for name, _, out in turn.calls
        ):
            watered.setdefault(day, []).append(int(agent[1:]))

    days: list[DayRecord] = []
    for day_result in result.days:
        day = day_result.report.day
        days.append(
            {
                "day": day,
                "ignited": [
                    {"field": e.field_id, "intensity": e.intensity, "audience": list(e.audience)}
                    for e in day_result.evidence
                ],
                "via_hidden": [[e.src, e.dst] for e in day_result.report.revealed_hidden],
                "burnt_out": list(day_result.report.burnt_out),
                "watered": sorted(watered.get(day, [])),
                "links_added": links_added.get(day, []),
                "messages": [
                    {
                        "sender": m.sender,
                        "receiver": m.receiver,
                        "route": list(m.route),
                        "field": m.claim.field_id,
                        "claim_day": m.claim.day,
                        "altered_by": list(m.altered_by),
                    }
                    for m in game.net.log
                    if m.day == day
                ],
                "exposures": [
                    {
                        "viewer": int(e.viewer[1:]),
                        "agent": int(e.agent[1:]),
                        "reason": e.reason,
                        "changes": [
                            {
                                "belief": c.belief_id,
                                "status": c.new_status,
                                "path": c.path_len,
                                "text": _claim_text(backend, e.viewer, c),
                            }
                            for c in e.changes
                        ],
                    }
                    for e in backend.exposures
                    if e.day == day
                ],
            }
        )
    return {
        "system": backend.name,
        "n_agents": world.config.n_agents,
        "fields": [{"id": f, "owner": world.owner(f)} for f in range(world.n_fields)],
        "edges": [
            {"src": e.src, "dst": e.dst, "weight": e.weight, "hidden": e.hidden}
            for e in world.edges
        ],
        "imposters": {str(a): b.value for a, b in game.net.imposters.items()},
        "start_links": [sorted(link) for link in game.net.links],
        "days": days,
        "score": score,
    }


def record_replay(
    scenario: Scenario,
    backend: Backend,
    client: ModelClient,
    *,
    budget: int = 4000,
    max_days: int = 100,
    max_steps: int = 6,
) -> Replay:
    """Play the scenario on `backend` with `client` and return the replay."""
    links_added: dict[int, list[list[int]]] = {}
    n = scenario["world"].get("n_agents", WorldConfig().n_agents)
    # the links the game starts with: the ring, plus any the scenario lists
    seen = {frozenset((a, (a + 1) % n)) for a in range(n)}
    seen |= {frozenset(link) for link in scenario.get("links", [])}

    def note_new_links(game: Game, _backend: Backend, day: int) -> None:
        fresh = sorted(sorted(link) for link in game.net.links - seen)
        if fresh:
            links_added[day] = fresh
            seen.update(game.net.links)

    result = run_game(
        scenario,
        backend,
        client,
        budget=budget,
        max_days=max_days,
        max_steps=max_steps,
        after_day=note_new_links,
    )
    return build_replay(result, backend, links_added, score_game(result, backend))


def write_viewer(replay: Replay, path: str | Path) -> Path:
    """A self-contained HTML page that plays `replay` back."""
    html = TEMPLATE.read_text().replace("__REPLAY__", json.dumps(replay).replace("</", "<\\/"))
    out = Path(path)
    out.write_text(html)
    return out
